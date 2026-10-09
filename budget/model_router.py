# budget/model_router.py
"""Routes LLM requests to the cheapest capable backend.

Tier priority:  LOCAL (Ollama, $0) → PAID_FREE (Groq, $0) → PAID_PREMIUM (OpenAI/Claude, $$)

On startup, performs an Ollama health check. If Ollama is unreachable,
all LOCAL tasks are promoted to PAID_FREE with a warning log.
"""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import aiohttp

from core.config import HarnessConfig

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    LOCAL = "LOCAL"
    PAID_FREE = "PAID_FREE"
    PAID_PREMIUM = "PAID_PREMIUM"


@dataclass
class LLMResponse:
    """Standardized response from any LLM backend."""
    text: str
    model: str
    tier: ModelTier
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)


# ── Task → Model routing table ──────────────────────────────────────────
# Keys match the task_type string passed to route(). Values specify the
# preferred tier and model name. See model_routing_guide.md §8 for details.
MODEL_ROUTING_TABLE: Dict[str, Dict[str, str]] = {
    # Phase ① Scope
    "scope_regex_gen":        {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "scope_interpret":        {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    # Phase ③ Planning
    "ideation_frame":         {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "ideation_deep":          {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "waf_evasion":            {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "fp_pattern_check":       {"tier": "LOCAL",        "model": "qwen2.5-coder:3b"},
    # Phase ④ Payloads
    "payload_craft":          {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "payload_polyglot":       {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "oob_embed":              {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    # Phase ⑤ Code Analysis
    "js_endpoint_extract":    {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "secret_detection":       {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "source_vuln_scan":       {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "dataflow_analysis":      {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "deobfuscation":          {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    # Phase ⑥ Fuzzing
    "adaptive_payload_select": {"tier": "LOCAL",       "model": "mistral:7b"},
    # Phase ⑦ Response Analysis
    "error_classify":         {"tier": "LOCAL",        "model": "qwen2.5-coder:3b"},
    "dom_xss_confirm":        {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "header_anomaly":         {"tier": "LOCAL",        "model": "mistral:7b"},
    # Phase ⑧ FP Filtering
    "noise_filter":           {"tier": "LOCAL",        "model": "qwen2.5-coder:3b"},
    "self_xss_detect":        {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "confidence_score":       {"tier": "LOCAL",        "model": "llama3.1:8b"},
    # Phase ⑨ Validation
    "vuln_confirm":           {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "idor_matrix_analyze":    {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "oob_correlate":          {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "biz_logic_validate":     {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "ai_jailbreak_confirm":   {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    # Phase ⑩ Chains
    "chain_analysis":         {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "impact_escalation":      {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "chain_narrative":        {"tier": "PAID_PREMIUM", "model": "claude-sonnet-4-20250514"},
    # Phase ⑪ Triage
    "vrt_classify":           {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "cwe_assign":             {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "cvss_calculate":         {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "dispute_prep":           {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "duplicate_detect":       {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    # Phase ⑫ Reports
    "report_draft":           {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "report_polish":          {"tier": "PAID_PREMIUM", "model": "gpt-4o"},
    "report_format":          {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "screenshot_alt_text":    {"tier": "LOCAL",        "model": "llama3.1:8b"},
}

# ── Fallback chain per tier ─────────────────────────────────────────────
FALLBACK_CHAIN = {
    ModelTier.LOCAL:        [ModelTier.PAID_FREE, ModelTier.PAID_PREMIUM],
    ModelTier.PAID_FREE:    [ModelTier.PAID_PREMIUM],
    ModelTier.PAID_PREMIUM: [],
}

# Default models per tier (used when fallback activates)
TIER_DEFAULTS = {
    ModelTier.LOCAL:        "qwen2.5-coder:7b",
    ModelTier.PAID_FREE:    "llama-3.1-70b-versatile",
    ModelTier.PAID_PREMIUM: "gpt-4o-mini",
}


class NoBudgetError(Exception):
    """Raised when no model backend is available for a task."""
    pass


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
        self._ollama_available: bool = True
        self._groq_available: bool = bool(config.groq_api_key)
        self._premium_keys: Dict[str, str] = {}

        # Detect premium API keys from environment
        for key_name, provider in [
            ("OPENAI_API_KEY", "openai"),
            ("ANTHROPIC_API_KEY", "anthropic"),
        ]:
            val = os.getenv(key_name)
            if val:
                self._premium_keys[provider] = val

    async def startup_health_check(self) -> None:
        """Check Ollama reachability on startup. If unreachable, promote LOCAL → PAID_FREE.

        Called once during harness bootstrap from main.py.
        """
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
                            return
                        else:
                            logger.warning("Ollama running but no models pulled.")
                    else:
                        logger.warning(f"Ollama returned HTTP {resp.status}")
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            logger.warning(f"Ollama unreachable at {self.config.ollama_url}: {exc}")

        self._ollama_available = False
        if self._groq_available:
            logger.warning(
                "Ollama unavailable — all LOCAL tasks routed to PAID_FREE tier (Groq)"
            )
        else:
            raise NoBudgetError(
                "No model backend available. Configure Ollama or set GROQ_API_KEY."
            )

    def resolve_model(self, task_type: str) -> tuple[ModelTier, str]:
        """Determine the tier and model for a given task type, applying fallbacks.

        Returns (tier, model_name).
        Raises NoBudgetError if no backend is available.
        """
        entry = MODEL_ROUTING_TABLE.get(task_type)
        if entry:
            preferred_tier = ModelTier(entry["tier"])
            preferred_model = entry["model"]
        else:
            # Unknown task type — default to LOCAL
            preferred_tier = ModelTier.LOCAL
            preferred_model = TIER_DEFAULTS[ModelTier.LOCAL]
            logger.warning(f"Unknown task_type '{task_type}' — defaulting to LOCAL")

        # Check if preferred tier is available
        if preferred_tier == ModelTier.LOCAL and self._ollama_available:
            return preferred_tier, preferred_model
        elif preferred_tier == ModelTier.PAID_FREE and self._groq_available:
            return preferred_tier, preferred_model
        elif preferred_tier == ModelTier.PAID_PREMIUM and self._premium_keys:
            return preferred_tier, preferred_model

        # Fallback chain
        for fallback_tier in FALLBACK_CHAIN.get(preferred_tier, []):
            if fallback_tier == ModelTier.LOCAL and self._ollama_available:
                return fallback_tier, TIER_DEFAULTS[fallback_tier]
            elif fallback_tier == ModelTier.PAID_FREE and self._groq_available:
                return fallback_tier, TIER_DEFAULTS[fallback_tier]
            elif fallback_tier == ModelTier.PAID_PREMIUM and self._premium_keys:
                return fallback_tier, TIER_DEFAULTS[fallback_tier]

        raise NoBudgetError(
            f"No backend available for task '{task_type}' "
            f"(preferred: {preferred_tier.value}, "
            f"ollama={self._ollama_available}, groq={self._groq_available}, "
            f"premium={bool(self._premium_keys)})"
        )

    async def route(self, task_type: str, prompt: str, **kwargs) -> LLMResponse:
        """Route a prompt to the best available model for the given task type.

        This is the primary entry point for all LLM calls in the harness.
        """
        tier, model = self.resolve_model(task_type)

        if tier == ModelTier.LOCAL:
            response = await self._call_ollama(model, prompt, **kwargs)
        elif tier == ModelTier.PAID_FREE:
            response = await self._call_groq(model, prompt, **kwargs)
        elif tier == ModelTier.PAID_PREMIUM:
            response = await self._call_premium(model, prompt, **kwargs)
        else:
            raise NoBudgetError(f"Unhandled tier: {tier}")

        response.tier = tier

        # Record token usage if tracker is attached
        if self.tracker:
            await self.tracker.record_usage(
                agent_id=kwargs.get("agent_id", "unknown"),
                task_id=kwargs.get("task_id", "unknown"),
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                model=model,
            )

        return response

    # ── Backend implementations ─────────────────────────────────────────

    async def _call_ollama(self, model: str, prompt: str, **kwargs) -> LLMResponse:
        """Send prompt to local Ollama instance."""
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if "system" in kwargs:
            payload["system"] = kwargs["system"]

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.config.ollama_url}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                data = await resp.json()
                return LLMResponse(
                    text=data.get("response", ""),
                    model=model,
                    tier=ModelTier.LOCAL,
                    input_tokens=data.get("prompt_eval_count", 0),
                    output_tokens=data.get("eval_count", 0),
                    raw=data,
                )

    async def _call_groq(self, model: str, prompt: str, **kwargs) -> LLMResponse:
        """Send prompt to Groq API (free tier)."""
        headers = {
            "Authorization": f"Bearer {self.config.groq_api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if "system" in kwargs:
            messages.append({"role": "system", "content": kwargs["system"]})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": model, "messages": messages}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                data = await resp.json()
                choice = data.get("choices", [{}])[0]
                usage = data.get("usage", {})
                return LLMResponse(
                    text=choice.get("message", {}).get("content", ""),
                    model=model,
                    tier=ModelTier.PAID_FREE,
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    raw=data,
                )

    async def _call_premium(self, model: str, prompt: str, **kwargs) -> LLMResponse:
        """Send prompt to OpenAI or Anthropic (paid tier)."""
        if model.startswith("gpt"):
            return await self._call_openai(model, prompt, **kwargs)
        elif model.startswith("claude"):
            return await self._call_anthropic(model, prompt, **kwargs)
        else:
            raise NoBudgetError(f"Unknown premium model: {model}")

    async def _call_openai(self, model: str, prompt: str, **kwargs) -> LLMResponse:
        """OpenAI chat completions API."""
        api_key = self._premium_keys.get("openai", "")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        messages = []
        if "system" in kwargs:
            messages.append({"role": "system", "content": kwargs["system"]})
        messages.append({"role": "user", "content": prompt})

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": model, "messages": messages},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                data = await resp.json()
                choice = data.get("choices", [{}])[0]
                usage = data.get("usage", {})
                return LLMResponse(
                    text=choice.get("message", {}).get("content", ""),
                    model=model,
                    tier=ModelTier.PAID_PREMIUM,
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    raw=data,
                )

    async def _call_anthropic(self, model: str, prompt: str, **kwargs) -> LLMResponse:
        """Anthropic messages API."""
        api_key = self._premium_keys.get("anthropic", "")
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        messages = [{"role": "user", "content": prompt}]
        payload: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 4096}
        if "system" in kwargs:
            payload["system"] = kwargs["system"]

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                data = await resp.json()
                text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
                usage = data.get("usage", {})
                return LLMResponse(
                    text="\n".join(text_blocks),
                    model=model,
                    tier=ModelTier.PAID_PREMIUM,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    raw=data,
                )
