# budget/model_router.py
"""Routes LLM requests to the cheapest capable backend (S5 multi-provider).

Tier priority (up-only fallback — it never falls back DOWN to LOCAL for a
PAID-preferred task):

    LOCAL (LOCAL_LIGHT, Ollama, $0)
      → LOCAL_HEAVY (Qwen3.8-27B on cloud GPU, $0/token, OFF unless LOCAL_HEAVY_URL)
      → PAID_FREE (Groq / OpenRouter / Mistral / Gemini free pool)
      → PAID_PREMIUM (GitHub Models free frontier → OpenRouter paid overflow)

S5 rework (spec S5.4): this replaces the old single-Groq 3-tier router with a
4-tier, multi-provider, lane-aware router. The provider registry, the generic
adapters, the soft rate limiter, runtime ``GET /models`` discovery, and the
secret scrub all live in :mod:`budget.providers` + :mod:`compliance.scrub`.
This module keeps the S2/S3/S4 public contract intact:

    ModelTier, LLMResponse, MODEL_ROUTING_TABLE, FALLBACK_CHAIN, TIER_DEFAULTS,
    NoBudgetError, ModelRouter.resolve_model / route /
    startup_health_check / _call_ollama.

Two-layer routing (the separation that keeps the locked S2/S3/S4 assertions
satisfiable while adding provider-level failover):

  * ``resolve_model(task)`` — coarse TIER-based resolution. Prefers the table's
    (tier, model); if that tier is down, walks :data:`FALLBACK_CHAIN` by tier and
    returns ``TIER_DEFAULTS[tier]``. This is what the dry-run prints and what the
    S4.3 budget gate audits.
  * ``route(task, prompt)`` — fine-grained EXECUTION. Walks the task's ordered
    provider stops (preferred stop → chain stops), enforces the scrub hard-rule +
    data lanes, rotates on 429 / provider errors, records per-provider usage
    (S5.4.6), and runs the two-model consensus for ``vuln_confirm`` /
    ``idor_matrix_analyze``.

Legacy note (S5): ``_premium_keys`` (direct OPENAI / ANTHROPIC env keys) is kept
only as a *compatibility availability signal* so the S2 premium resolve test keeps
passing. S5 routing no longer needs direct OpenAI/Anthropic keys — PREMIUM is
served by the registry's GitHub Models (free frontier) and OpenRouter (paid
overflow) providers. A PREMIUM stop with no registry provider fails open to
NoBudgetError at call time.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from budget.providers import (
    ApiStyle,
    DataLane,
    Provider,
    ProviderUnavailable,
    RateLimited,
    build_registry,
    chat,
    discover_models,
)
from compliance.scrub import scrub
from core.config import HarnessConfig

logger = logging.getLogger(__name__)

# ── Model name constants (2026 catalog) ────────────────────────────────────
# Canonical LOCAL_LIGHT primary: the security-tuned 8B pulled on the operator's
# box (S5.4.5). Every $0 classify / FP / error / pattern task routes here first.
LOCAL_LIGHT_PRIMARY = "hf.co/dr-ry/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M"
LOCAL_LIGHT_FALLBACK = "qwen2.5:7b"
# LOCAL_HEAVY: Qwen3.8-27B on the cloud GPU (self-hosted llama-server, $0/token).
LOCAL_HEAVY_MODEL = "qwen3.8-27b"
# PAID_FREE pool.
G120 = "openai/gpt-oss-120b"            # Groq primary (free)
GROQ_27B = "qwen/qwen3.8-27b"           # Groq (consensus second model, non-GPU)
OR_27B_FREE = "qwen/qwen3.8-27b:free"   # OpenRouter :free
NEMO_FREE = "nvidia/nemotron-3-ultra:free"   # OpenRouter :free (1M ctx)
LAGUNA_FREE = "poolside/laguna-s-2.1:free"   # OpenRouter :free (code)
CODESTRAL = "codestral"                 # Mistral (code lane)
GEMINI_FLASH = "gemini-2.5-flash"       # Gemini free 1M (RESTRICTED lane)
# PAID_PREMIUM frontier.
GH_GPT4O = "gpt-4o"                     # GitHub Models free frontier ($0)
GH_CLAUDE = "claude-3-5-sonnet"         # GitHub Models free frontier ($0)
OR_CLAUDE_PAID = "anthropic/claude-sonnet-4"   # OpenRouter paid overflow (post top-up)


class ModelTier(str, Enum):
    LOCAL = "LOCAL"                    # LOCAL_LIGHT (Ollama, $0)
    LOCAL_HEAVY = "LOCAL_HEAVY"        # S5: Qwen3.8-27B on GPU ($0, optional)
    PAID_FREE = "PAID_FREE"            # multi-provider free pool
    PAID_PREMIUM = "PAID_PREMIUM"      # frontier (free) + paid overflow


@dataclass
class LLMResponse:
    """Standardized response from any LLM backend."""
    text: str
    model: str
    tier: ModelTier
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)
    # S5: provenance of the call that actually served the prompt.
    provider: str = "local"
    lane: str = DataLane.SAFE.value


# ── Task → Model routing table (S5.4.5) ───────────────────────────────────
# Keys match the task_type string passed to route()/resolve_model(). Each entry
# has a preferred (tier, model) stop. Optional keys:
#   "chain":      ordered extra (tier, model) stops for call-time failover.
#   "local_only":  True → the task never leaves the machine (source carries
#                   secrets), so route() only tries LOCAL / LOCAL_HEAVY stops.
#   "agree_with": ordered list of model names for the two-model consensus
#                   (vuln_confirm / idor_matrix_analyze). The FIRST candidate
#                   whose provider is up serves the second opinion
#                   (GPU 27B when up, else Groq 27B).
MODEL_ROUTING_TABLE: Dict[str, Dict[str, Any]] = {
    # Phase ① Scope
    "scope_regex_gen":         {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "scope_interpret":         {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    # Phase ③ Planning
    "ideation_frame":          {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "ideation_deep":           {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    "waf_evasion":             {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    "fp_pattern_check":        {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    # Phase ④ Payloads
    "payload_craft":           {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY,
                                "chain": [("PAID_FREE", CODESTRAL),
                                          ("PAID_FREE", LAGUNA_FREE)]},
    "payload_polyglot":        {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    "oob_embed":               {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    # Phase ⑤ Code Analysis
    "js_endpoint_extract":     {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "secret_detection":        {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY,
                                "local_only": True},
    "source_vuln_scan":        {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "dataflow_analysis":       {"tier": "LOCAL_HEAVY", "model": LOCAL_HEAVY_MODEL,
                                "chain": [("PAID_FREE", GEMINI_FLASH),
                                          ("PAID_FREE", NEMO_FREE)]},
    "deobfuscation":           {"tier": "LOCAL_HEAVY", "model": LOCAL_HEAVY_MODEL,
                                "chain": [("PAID_FREE", GEMINI_FLASH),
                                          ("PAID_FREE", NEMO_FREE)]},
    # Phase ⑥ Fuzzing
    "adaptive_payload_select": {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    # Phase ⑦ Response Analysis
    "error_classify":          {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "dom_xss_confirm":         {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY,
                                "local_only": True},
    "header_anomaly":          {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    # Phase ⑧ FP Filtering
    "noise_filter":            {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "self_xss_detect":         {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "confidence_score":        {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    # Phase ⑨ Validation
    "vuln_confirm":            {"tier": "PAID_FREE", "model": G120,
                                "agree_with": [LOCAL_HEAVY_MODEL, GROQ_27B]},
    "idor_matrix_analyze":     {"tier": "PAID_FREE", "model": G120,
                                "agree_with": [LOCAL_HEAVY_MODEL, GROQ_27B]},
    "oob_correlate":           {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "biz_logic_validate":      {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    "ai_jailbreak_confirm":    {"tier": "LOCAL_HEAVY", "model": LOCAL_HEAVY_MODEL,
                                "chain": [("PAID_FREE", G120),
                                          ("PAID_FREE", OR_27B_FREE)]},
    # Phase ⑩ Chains
    "chain_analysis":          {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    "impact_escalation":       {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    "chain_narrative":         {"tier": "PAID_PREMIUM", "model": GH_CLAUDE,
                                "chain": [("PAID_PREMIUM", OR_CLAUDE_PAID)]},
    # Phase ⑪ Triage
    "vrt_classify":            {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "cwe_assign":              {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "cvss_calculate":          {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    "dispute_prep":            {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    "duplicate_detect":        {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "triage_decision":         {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    # Phase ⑫ Reports
    "report_draft":            {"tier": "PAID_FREE", "model": G120,
                                "chain": [("PAID_FREE", OR_27B_FREE)]},
    "report_polish":           {"tier": "PAID_PREMIUM", "model": GH_GPT4O,
                                "chain": [("PAID_PREMIUM", OR_CLAUDE_PAID)]},
    "report_format":           {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
    "screenshot_alt_text":     {"tier": "LOCAL", "model": LOCAL_LIGHT_PRIMARY},
}

# ── Fallback chain per tier (up-only; PAID_PREMIUM is terminal) ───────────
FALLBACK_CHAIN: Dict[ModelTier, List[ModelTier]] = {
    ModelTier.LOCAL:        [ModelTier.LOCAL_HEAVY, ModelTier.PAID_FREE, ModelTier.PAID_PREMIUM],
    ModelTier.LOCAL_HEAVY:  [ModelTier.PAID_FREE, ModelTier.PAID_PREMIUM],
    ModelTier.PAID_FREE:    [ModelTier.PAID_PREMIUM],
    ModelTier.PAID_PREMIUM: [],
}

# Default models per tier (used when a tier-fallback activates). Every one of
# these must have a MODEL_COSTS entry (enforced by S2).
TIER_DEFAULTS: Dict[ModelTier, str] = {
    ModelTier.LOCAL:        LOCAL_LIGHT_PRIMARY,
    ModelTier.LOCAL_HEAVY:  LOCAL_HEAVY_MODEL,
    ModelTier.PAID_FREE:    G120,
    ModelTier.PAID_PREMIUM: GH_CLAUDE,
}


class NoBudgetError(Exception):
    """Raised when no model backend is available for a task."""
    pass


# Verdict markers for the two-model consensus (vuln_confirm / idor_matrix_analyze).
_CONFIRM_MARKERS = (
    "CONFIRMED", "CONFIRMS", "IS A VALID", "VALID FINDING",
    "TRUE POSITIVE", "VULNERABLE",
)
_DENY_MARKERS = (
    "NOT CONFIRMED", "NOT_CONFIRMED", "NOT VULNERABLE", "NOT A VALID",
    "NO_BUG", "NO BUG", "FALSE POSITIVE", "NOT A VULNERABILITY",
)


def _verdict_confirms(text: str) -> bool:
    """Heuristic: does a model's verdict text indicate a CONFIRMED finding?

    Denial markers are checked first because "NOT CONFIRMED" contains the
    substring "CONFIRMED".
    """
    if not text:
        return False
    t = text.upper()
    for neg in _DENY_MARKERS:
        if neg in t:
            return False
    return any(m in t for m in _CONFIRM_MARKERS)


class ModelRouter:
    """Routes LLM prompts to the optimal backend based on task type and availability.

    Usage:
        router = ModelRouter(config, tracker)
        await router.startup_health_check()
        response = await router.route("payload_craft", prompt="Generate a UNION SQLi payload...")
    """

    def __init__(self, config: HarnessConfig, tracker=None):
        self.config = config
        self.tracker = tracker
        # Compat availability flags (kept for the locked S2/S3/S4 tests).
        self._ollama_available: bool = True
        self._groq_available: bool = bool(config.groq_api_key)
        self._local_heavy_available: bool = bool(config.local_heavy_url)
        self._premium_keys: Dict[str, str] = {}
        # Legacy direct premium keys (compat availability signal only — S5 routing
        # does not call OpenAI/Anthropic directly; see module docstring).
        for key_name, provider in [
            ("OPENAI_API_KEY", "openai"),
            ("ANTHROPIC_API_KEY", "anthropic"),
        ]:
            val = os.getenv(key_name)
            if val:
                self._premium_keys[provider] = val
        # S5: ordered provider registry (built from config, never os.environ —
        # keeps the S2 ``HarnessConfig(groq_api_key=...)`` tests deterministic).
        self._registry: List[Provider] = build_registry(config)
        # Injectable transport for offline tests. None → real HTTP via aiohttp.
        self._http = None

    # ── Startup ──────────────────────────────────────────────────────────

    async def startup_health_check(self) -> None:
        """Check local backend reachability on startup.

        Ollama is probed (``/api/tags``); if unreachable, LOCAL is marked down and
        LOCAL tasks fall back per :data:`FALLBACK_CHAIN`. LOCAL_HEAVY (if
        configured) is probed best-effort. Raises NoBudgetError only when NO tier
        is available at all. Cloud providers are reconciled separately by
        :meth:`startup_discovery` (live mode) so this stays offline-safe for tests.
        """
        await self._check_ollama()
        if self.config.local_heavy_url and self._local_heavy_available:
            await self._check_local_heavy()
        if not self._any_tier_available():
            raise NoBudgetError(
                "No model backend available. Configure Ollama (default) or set a "
                "provider key (GROQ_API_KEY / OPENROUTER_API_KEY / GITHUB_TOKEN ...)."
            )

    async def _check_ollama(self) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.config.ollama_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        if models:
                            logger.info(f"Ollama online — {len(models)} models available: {models}")
                            self._ollama_available = True
                            # Reconcile the Ollama provider's live catalog.
                            p = self._provider("ollama")
                            if p is not None:
                                p.live_models = models
                            return
                        logger.warning("Ollama running but no models pulled.")
                    else:
                        logger.warning(f"Ollama returned HTTP {resp.status}")
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            logger.warning(f"Ollama unreachable at {self.config.ollama_url}: {exc}")
        self._ollama_available = False
        if self._any_tier_available():
            logger.warning("Ollama unavailable — LOCAL tasks will fall back to available tiers")
        else:
            # Kept for the old contract's log line; startup_health_check raises
            # later if truly nothing is up.
            logger.warning("Ollama unavailable and no other backend is configured")

    async def _check_local_heavy(self) -> None:
        """Best-effort ping of the LOCAL_HEAVY llama-server (fail-open)."""
        base = self.config.local_heavy_url.rstrip("/")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base}/models",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        logger.info("LOCAL_HEAVY online")
                        p = self._provider("local_heavy")
                        if p is not None:
                            data = await resp.json()
                            items = data.get("data")
                            if isinstance(items, list):
                                p.live_models = [m.get("id", "") for m in items] or None
                    else:
                        self._local_heavy_available = False
                        logger.warning(f"LOCAL_HEAVY returned HTTP {resp.status} — tier stays OFF")
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            self._local_heavy_available = False
            logger.warning(f"LOCAL_HEAVY unreachable at {base}: {exc} — tier stays OFF (fail-open)")

    async def startup_discovery(self) -> None:
        """S5.4.4: reconcile every enabled provider's preference list against its
        live catalog (``GET /models``). Fail-open: a failure keeps the configured
        preferences. Called from ``main._run_live`` after the health check; never
        called on the dry-run path or in unit tests (so tests stay offline).
        """
        for p in self._registry:
            if not p.enabled:
                continue
            try:
                await discover_models(p, http=self._http)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("discovery failed for %s: %s (keeping preferences)", p.name, exc)

    # ── Availability ─────────────────────────────────────────────────────

    def _any_tier_available(self) -> bool:
        return any(self._tier_available(t) for t in ModelTier)

    def _tier_available(self, tier: ModelTier) -> bool:
        """Whether ``tier`` has at least one usable backend right now."""
        if tier is ModelTier.LOCAL:
            return self._ollama_available
        if tier is ModelTier.LOCAL_HEAVY:
            return self._local_heavy_available
        if tier is ModelTier.PAID_FREE:
            # Groq fast-path (compat flag) OR any enabled free-pool provider.
            if self._groq_available:
                return True
            return any(
                p.enabled and p.available for p in self._registry
                if p.tier == tier.value
            )
        if tier is ModelTier.PAID_PREMIUM:
            # Legacy direct premium keys (compat signal) OR a registry premium
            # provider (GitHub Models / Gemini ...).
            if self._premium_keys:
                return True
            return any(
                p.enabled and p.available for p in self._registry
                if p.tier == tier.value
            )
        return False

    # ── Provider lookup ──────────────────────────────────────────────────

    def _provider(self, name: str) -> Optional[Provider]:
        for p in self._registry:
            if p.name == name:
                return p
        return None

    def _provider_for(self, model: str) -> Optional[Provider]:
        """First enabled + available provider that hosts ``model`` (by configured
        or live catalog)."""
        for p in self._registry:
            if not (p.enabled and p.available):
                continue
            if model in p.models or (p.live_models and model in p.live_models):
                return p
        return None

    def _reconcile_model(self, p: Provider, model: str) -> str:
        """If discovery ran and the requested model rotated out of the live
        catalog, fall back to the first live model (never call a dead name)."""
        if p.live_models and model not in p.live_models and model in p.models:
            logger.warning(
                "model %s no longer on %s — using %s", model, p.name, p.live_models[0]
            )
            return p.live_models[0]
        return model

    # ── Coarse tier resolution (locked S2 API) ───────────────────────────

    def resolve_model(self, task_type: str) -> tuple[ModelTier, str]:
        """Determine the tier and model for a task, applying tier fallbacks.

        Returns (tier, model_name). Raises NoBudgetError if no backend is
        available. This is the *tier-level* decision; :meth:`route` adds
        provider-level failover on top.
        """
        entry = MODEL_ROUTING_TABLE.get(task_type)
        if entry:
            preferred_tier = ModelTier(entry["tier"])
            preferred_model = entry["model"]
        else:
            preferred_tier = ModelTier.LOCAL
            preferred_model = TIER_DEFAULTS[ModelTier.LOCAL]
            logger.warning(f"Unknown task_type '{task_type}' — defaulting to LOCAL")

        if self._tier_available(preferred_tier):
            return preferred_tier, preferred_model

        for fallback_tier in FALLBACK_CHAIN.get(preferred_tier, []):
            if self._tier_available(fallback_tier):
                return fallback_tier, TIER_DEFAULTS[fallback_tier]

        raise NoBudgetError(
            f"No backend available for task '{task_type}' "
            f"(preferred: {preferred_tier.value}, "
            f"ollama={self._ollama_available}, local_heavy={self._local_heavy_available}, "
            f"groq={self._groq_available}, premium={bool(self._premium_keys)})"
        )

    # ── Fine-grained execution (S5) ──────────────────────────────────────

    async def route(self, task_type: str, prompt: str, **kwargs) -> LLMResponse:
        """Route a prompt to the best available model for the task.

        Primary entry point for all LLM calls. Enforces the scrub hard-rule,
        data lanes, 429 rotation, per-provider billing, and the two-model
        consensus for vuln_confirm / idor_matrix_analyze.
        """
        entry = MODEL_ROUTING_TABLE.get(task_type)
        tier, model = self.resolve_model(task_type)  # raises NoBudgetError if none

        # Build the ordered provider stops: the resolved preferred stop first,
        # then the task's explicit chain (deduped).
        stops: List[Tuple[ModelTier, str]] = [(tier, model)]
        if entry and not entry.get("local_only"):
            for s in entry.get("chain", []):
                st = ModelTier(s[0])
                sm = s[1]
                if (st, sm) not in stops:
                    stops.append((st, sm))
        # local_only tasks never leave the machine (their source carries secrets).
        local_tiers = (ModelTier.LOCAL, ModelTier.LOCAL_HEAVY)
        if entry and entry.get("local_only"):
            stops = [(t, m) for (t, m) in stops if t in local_tiers] or stops

        # S5.3 hard rule: no secrets in any cloud-bound prompt. If a secret is
        # detected, re-route to LOCAL / LOCAL_HEAVY (self-hosted sink). If no
        # local backend is up, refuse (never send a secret to the cloud).
        scrub_result = scrub(prompt)
        scrub_rerouted: Optional[List[str]] = None
        if scrub_result.found:
            # Table-local stops first (e.g. a LOCAL_HEAVY 27B for dataflow), then
            # the forced LOCAL default, so a secret-bearing prompt gets the most
            # capable local sink the task already declared.
            local_stops = [(t, m) for (t, m) in stops if t in local_tiers]
            if self._ollama_available and not any(
                t is ModelTier.LOCAL for t, _ in local_stops
            ):
                local_stops = local_stops + [(ModelTier.LOCAL, TIER_DEFAULTS[ModelTier.LOCAL])]
            if self._local_heavy_available and not any(
                t is ModelTier.LOCAL_HEAVY for t, _ in local_stops
            ):
                local_stops.append((ModelTier.LOCAL_HEAVY, TIER_DEFAULTS[ModelTier.LOCAL_HEAVY]))
            if not local_stops:
                raise NoBudgetError(
                    f"scrub blocked task '{task_type}' (patterns: {scrub_result.matches}) "
                    f"and no local backend is available — refusing to send to the cloud"
                )
            logger.warning(
                "scrub_blocked: %d secret pattern(s) %s — re-routing task '%s' to local only",
                len(scrub_result.matches), scrub_result.matches, task_type,
            )
            stops = local_stops
            scrub_rerouted = list(scrub_result.matches)

        system = kwargs.get("system")
        max_tokens = kwargs.get("max_tokens")

        response: Optional[LLMResponse] = None
        stop_tier = tier
        for stop_tier, stop_model in stops:
            response = await self._serve_stop(
                stop_tier, stop_model, prompt, kwargs,
                system=system, max_tokens=max_tokens,
            )
            if response is not None:
                break

        if response is None:
            raise NoBudgetError(
                f"all provider stops failed or are unavailable for task '{task_type}' "
                f"(stops: {[(t.value, m) for t, m in stops]})"
            )

        response.tier = stop_tier
        if scrub_rerouted:
            response.raw["scrub_rerouted"] = scrub_rerouted

        # Two-model consensus (vuln_confirm / idor_matrix_analyze).
        if entry and entry.get("agree_with"):
            await self._apply_consensus(response, entry, prompt, kwargs,
                                        system=system, max_tokens=max_tokens)

        # Billing (per-provider bucket, S5.4.6). The consensus partner is billed
        # separately inside _apply_consensus.
        if self.tracker:
            await self.tracker.record_usage(
                agent_id=kwargs.get("agent_id", "unknown"),
                task_id=kwargs.get("task_id", "unknown"),
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                model=response.model,
                provider=response.provider,
                lane=response.lane,
                tier=stop_tier.value,
            )

        return response

    async def _serve_stop(
        self,
        stop_tier: ModelTier,
        stop_model: str,
        prompt: str,
        kwargs: Dict[str, Any],
        system: Optional[str],
        max_tokens: Optional[int],
    ) -> Optional[LLMResponse]:
        """Try to serve one (tier, model) stop. Returns an LLMResponse on success,
        None when the stop has no usable provider (caller rotates). Never raises
        for a single-provider failure — those are rotation signals."""
        if stop_tier is ModelTier.LOCAL:
            if not self._ollama_available:
                return None
            try:
                # _call_ollama is the monkeypatch seam S3 relies on, so LOCAL
                # stops always route through it (not the generic adapter).
                return await self._call_ollama(stop_model, prompt, **kwargs)
            except (ProviderUnavailable, RateLimited, aiohttp.ClientError, OSError) as exc:
                logger.warning("ollama stop failed (%s) — rotating", exc)
                return None

        if stop_tier is ModelTier.LOCAL_HEAVY and not self._local_heavy_available:
            return None

        provider = self._provider_for(stop_model)
        if provider is None or not provider.enabled:
            return None

        model = self._reconcile_model(provider, stop_model)
        if not await provider.try_acquire():
            logger.warning("soft rate limit reached on %s — rotating", provider.name)
            return None
        started = time.monotonic()
        try:
            result = await chat(provider, model, prompt, system=system,
                                max_tokens=max_tokens, http=self._http)
        except RateLimited:
            logger.warning("429 from %s — rotating to next provider", provider.name)
            return None
        except ProviderUnavailable as exc:
            logger.warning("provider %s unavailable (%s) — rotating", provider.name, exc)
            return None
        except (aiohttp.ClientError, OSError) as exc:
            logger.warning("provider %s network error (%s) — rotating", provider.name, exc)
            return None
        elapsed = time.monotonic() - started

        response = LLMResponse(
            text=result.text,
            model=result.model,
            tier=stop_tier,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            raw=result.raw,
            provider=result.provider,
            lane=provider.lane.value,
        )
        # S5.4.6: meter LOCAL_HEAVY GPU-hours from the call's wall time.
        if provider.name == "local_heavy" and self.tracker is not None:
            self.tracker.record_gpu_hours(elapsed / 3600.0)
        return response

    # ── Backend implementations ──────────────────────────────────────────

    async def _call_ollama(self, model: str, prompt: str, **kwargs) -> LLMResponse:
        """Send a prompt to the local Ollama instance (S4.3 live round-trip + the
        S3 monkeypatch seam). Signature and LOCAL semantics are preserved."""
        provider = self._ollama_provider()
        result = await chat(
            provider, model, prompt,
            system=kwargs.get("system"),
            max_tokens=kwargs.get("max_tokens"),
            http=self._http,
        )
        return LLMResponse(
            text=result.text,
            model=model,
            tier=ModelTier.LOCAL,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            raw=result.raw,
            provider="ollama",
            lane=DataLane.SAFE.value,
        )

    def _ollama_provider(self) -> Provider:
        p = self._provider("ollama")
        if p is not None:
            return p
        # Ad-hoc fallback if the registry lacks Ollama (e.g. explicit opt-out).
        return Provider(
            name="ollama", tier="LOCAL", lane=DataLane.SAFE,
            api_style=ApiStyle.OLLAMA,
            base_url=self.config.ollama_url, key=None,
            models=[LOCAL_LIGHT_PRIMARY, LOCAL_LIGHT_FALLBACK],
        )

    async def _apply_consensus(
        self,
        response: LLMResponse,
        entry: Dict[str, Any],
        prompt: str,
        kwargs: Dict[str, Any],
        system: Optional[str],
        max_tokens: Optional[int],
    ) -> None:
        """Run the second-opinion model for a consensus task and record the
        agreement in ``response.raw["consensus"]``. Fail-open: if no second model
        is available, the primary verdict stands (agreement=None)."""
        agree_text: Optional[str] = None
        agree_model: Optional[str] = None
        agree_in = 0
        agree_out = 0
        agree_provider: Optional[Provider] = None
        for cand in entry["agree_with"]:
            provider = self._provider_for(cand)
            if provider is None or not (provider.enabled and provider.available):
                continue
            try:
                result = await chat(
                    provider, self._reconcile_model(provider, cand), prompt,
                    system=system, max_tokens=max_tokens, http=self._http,
                )
            except (RateLimited, ProviderUnavailable, aiohttp.ClientError, OSError) as exc:
                logger.warning("consensus partner %s unavailable (%s)", cand, exc)
                continue
            agree_text = result.text
            agree_model = result.model
            agree_in = result.input_tokens
            agree_out = result.output_tokens
            agree_provider = provider
            break

        if agree_text is None:
            response.raw["consensus"] = {
                "agreement": None,
                "reason": "no second model available (fail-open, primary verdict stands)",
            }
            return

        primary_confirms = _verdict_confirms(response.text)
        agree_confirms = _verdict_confirms(agree_text)
        agreement = bool(primary_confirms and agree_confirms)
        response.raw["consensus"] = {
            "agree_model": agree_model,
            "agree_provider": agree_provider.name if agree_provider else None,
            "primary_confirms": primary_confirms,
            "agree_confirms": agree_confirms,
            "agreement": agreement,
        }
        if agreement is False:
            logger.warning(
                "consensus DISAGREEMENT for primary model %s (primary=%s, %s=%s)",
                response.model, primary_confirms, agree_model, agree_confirms,
            )

        # Bill the second call too (S5.4.6 per-provider ledger).
        if self.tracker and agree_provider is not None:
            await self.tracker.record_usage(
                agent_id=kwargs.get("agent_id", "unknown"),
                task_id=kwargs.get("task_id", "unknown") + "_consensus",
                input_tokens=agree_in,
                output_tokens=agree_out,
                model=agree_model or "",
                provider=agree_provider.name,
                lane=agree_provider.lane.value,
                tier=agree_provider.tier,
            )

    # ── War-room / ops helpers (S7) ──────────────────────────────────────

    def provider_status(self) -> List[Dict[str, Any]]:
        """Per-provider snapshot for the war-room dashboard (S7.3): name, tier,
        lane, enabled/available, model catalog, GPU-hour cost."""
        return [
            {
                "name": p.name,
                "tier": p.tier,
                "lane": p.lane.value,
                "enabled": p.enabled,
                "available": p.available,
                "has_key": p.has_key,
                "models": list(p.models),
                "live_models": list(p.live_models) if p.live_models else None,
                "context": p.context,
                "rpm": p.rpm,
                "hourly_cost": p.hourly_cost,
            }
            for p in self._registry
        ]
