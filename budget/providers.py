# budget/providers.py
"""S5 — provider registry, adapters, rate limiting, and model discovery.

Replaces the old single-Groq ``_call_groq``/``_call_openai``/``_call_anthropic``
triplication with:
  * a dataclass ``Provider`` registry (built from ``HarnessConfig``),
  * ONE generic OpenAI-compatible adapter (Groq / OpenRouter / Mistral /
    GitHub Models / Cloudflare / LOCAL_HEAVY llama-server),
  * ONE Gemini-native adapter,
  * the existing Ollama adapter,
  * per-provider soft rate limiters + a ``RateLimited`` signal for 429 rotation,
  * runtime ``GET /models`` discovery (free tiers drift — Groq rotated 2026-09).

Everything here is import-safe with no network and no keys. HTTP goes through an
injectable ``http`` callable so the router (and tests) can drive it offline:

    await chat(provider, model, prompt, system, http=real_http)
    await chat(provider, model, prompt, system, http=fake_http)   # tests

``http`` is ``async def http(method, url, headers, payload, timeout) -> (status, json_dict)``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DataLane(str, Enum):
    """Data-handling lane (S5.3). RESTRICTED lanes only ever receive scrubbed,
    non-sensitive content; the router refuses a findings-carrying prompt to one
    when a secret is detected."""
    SAFE = "SAFE"
    RESTRICTED = "RESTRICTED"


class ApiStyle(str, Enum):
    OPENAI_COMPAT = "openai_compat"    # Groq/OpenRouter/Mistral/GitHub/Cloudflare/llama-server
    GEMINI_NATIVE = "gemini_native"    # Google AI Studio
    OLLAMA = "ollama"                  # local Ollama /api/generate


@dataclass
class LLMResult:
    """Raw outcome of a single provider call (before the router stamps tier/lane)."""
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)


class RateLimited(Exception):
    """A provider returned 429 (or its limiter rejected) — rotate to the next."""


class ProviderUnavailable(Exception):
    """A provider errored (non-429) — skip it and try the next in the chain."""


HttpFn = Callable[..., Awaitable[Tuple[int, Dict[str, Any]]]]


def default_http(method: str, url: str, headers: Dict[str, str],
                 payload: Dict[str, Any], timeout: int = 60) -> "Awaitable[Tuple[int, Dict[str, Any]]]":
    """Real HTTP via aiohttp. Imported lazily so the module is import-safe."""
    import aiohttp

    async def _call() -> Tuple[int, Dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except (json.JSONDecodeError, ValueError):
                    body = {}
                return resp.status, body

    return _call()


@dataclass
class Provider:
    name: str
    tier: str                    # "LOCAL_LIGHT" | "LOCAL_HEAVY" | "PAID_FREE" | "PAID_PREMIUM"
    lane: DataLane
    api_style: ApiStyle
    base_url: str
    key: Optional[str]           # bearer key / url for LOCAL_HEAVY; None for keyless local
    models: List[str]            # preference list (reconciled at runtime)
    context: int = 8192
    rpm: int = 30
    rpd: int = 1000
    hourly_cost: float = 0.0     # LOCAL_HEAVY GPU-hour cost only
    enabled: bool = True         # key present + not disabled
    # runtime state (mutated by discovery / limiter)
    available: bool = True
    live_models: Optional[List[str]] = None
    _limiter: "RateLimiter" = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._limiter = RateLimiter(rpm=self.rpm, rpd=self.rpd)

    @property
    def has_key(self) -> bool:
        return bool(self.key)

    def resolved_models(self) -> List[str]:
        """Preferred models that are still in the live catalog (if discovery ran).
        If no discovery happened, return the configured preference list as-is."""
        if self.live_models is None:
            return list(self.models)
        live = set(self.live_models)
        present = [m for m in self.models if m in live]
        # Fall back to the first live model if none of the preferences survived
        # a catalog rotation (free tiers drift) — never crash.
        return present if present else list(self.live_models)[:1]

    async def try_acquire(self) -> bool:
        return await self._limiter.acquire()


class RateLimiter:
    """Soft per-provider limiter: sliding-window RPM + RPD.

    ``acquire()`` is non-blocking: it returns True when the provider is under its
    limits, else False (the caller backs off / rotates). Deliberately simple —
    the 429 path is the authoritative backstop and is what the gates exercise.
    """

    def __init__(self, rpm: int = 30, rpd: int = 1000, now: Optional[Callable[[], float]] = None):
        self.rpm = max(1, rpm)
        self.rpd = max(1, rpd)
        self._now = now or time.monotonic
        self._minute: Deque[float] = deque()
        self._day: Deque[float] = deque()

    def _prune(self) -> None:
        now = self._now()
        while self._minute and now - self._minute[0] > 60:
            self._minute.popleft()
        while self._day and now - self._day[0] > 86400:
            self._day.popleft()

    async def acquire(self) -> bool:
        self._prune()
        if len(self._minute) >= self.rpm or len(self._day) >= self.rpd:
            return False
        self._minute.append(self._now())
        self._day.append(self._now())
        return True


# ── Adapters ────────────────────────────────────────────────────────────────

def _openai_chat_url(provider: Provider) -> str:
    base = provider.base_url.rstrip("/")
    # Accept either a full .../chat/completions URL or a bare base.
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


async def chat(provider: Provider, model: str, prompt: str,
               system: Optional[str] = None, *,
               http: Optional[HttpFn] = None) -> LLMResult:
    """Route a single prompt to ``provider`` via the right adapter.

    Raises ``RateLimited`` on 429 and ``ProviderUnavailable`` on other HTTP errors.
    """
    http = http or (lambda m, u, h, p, t=60: default_http(m, u, h, p, t))
    if provider.api_style is ApiStyle.OLLAMA:
        return await _chat_ollama(provider, model, prompt, system, http=http)
    if provider.api_style is ApiStyle.GEMINI_NATIVE:
        return await _chat_gemini(provider, model, prompt, system, http=http)
    return await _chat_openai_compat(provider, model, prompt, system, http=http)


async def _chat_openai_compat(provider: Provider, model: str, prompt: str,
                              system: Optional[str], *, http: HttpFn) -> LLMResult:
    headers = {"Content-Type": "application/json"}
    if provider.key:
        headers["Authorization"] = f"Bearer {provider.key}"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages}

    status, data = await http("POST", _openai_chat_url(provider), headers, payload)
    if status == 429:
        raise RateLimited(f"{provider.name}: 429 rate limited")
    if status >= 400:
        raise ProviderUnavailable(f"{provider.name}: HTTP {status}: {str(data)[:200]}")

    choice = (data.get("choices") or [{}])[0]
    usage = data.get("usage", {})
    return LLMResult(
        text=(choice.get("message") or {}).get("content", "") or "",
        model=data.get("model", model),
        provider=provider.name,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        raw=data,
    )


async def _chat_gemini(provider: Provider, model: str, prompt: str,
                       system: Optional[str], *, http: HttpFn) -> LLMResult:
    # Google AI Studio: .../v1beta/models/{model}:generateContent?key=KEY
    base = provider.base_url.rstrip("/")
    url = f"{base}/models/{model}:generateContent"
    if provider.key:
        url = f"{url}?key={provider.key}"
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    payload: Dict[str, Any] = {"contents": contents}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    status, data = await http("POST", url, {"Content-Type": "application/json"}, payload)
    if status == 429:
        raise RateLimited(f"{provider.name}: 429 rate limited")
    if status >= 400:
        raise ProviderUnavailable(f"{provider.name}: HTTP {status}: {str(data)[:200]}")

    candidates = data.get("candidates") or [{}]
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if p.get("text"))
    usage = data.get("usageMetadata", {})
    return LLMResult(
        text=text,
        model=model,
        provider=provider.name,
        input_tokens=usage.get("promptTokenCount", 0),
        output_tokens=usage.get("candidatesTokenCount", 0),
        raw=data,
    )


async def _chat_ollama(provider: Provider, model: str, prompt: str,
                       system: Optional[str], *, http: HttpFn) -> LLMResult:
    base = provider.base_url.rstrip("/")
    payload: Dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system
    status, data = await http("POST", f"{base}/api/generate",
                              {"Content-Type": "application/json"}, payload)
    if status >= 400:
        raise ProviderUnavailable(f"{provider.name}: HTTP {status}: {str(data)[:200]}")
    return LLMResult(
        text=data.get("response", "") or "",
        model=model,
        provider=provider.name,
        input_tokens=data.get("prompt_eval_count", 0),
        output_tokens=data.get("eval_count", 0),
        raw=data,
    )


async def discover_models(provider: Provider, *, http: Optional[HttpFn] = None,
                          timeout: int = 10) -> List[str]:
    """Runtime ``GET /models`` reconciliation. Never fatal — on any failure the
    provider's configured preference list is kept (``live_models`` stays None)."""
    http = http or (lambda m, u, h, p, t=10: default_http(m, u, h, p, t))
    base = provider.base_url.rstrip("/")
    if provider.api_style is ApiStyle.OLLAMA:
        url = f"{base}/api/tags"
    else:
        url = f"{base}/models"
    headers = {}
    if provider.key and provider.api_style is not ApiStyle.OLLAMA:
        headers["Authorization"] = f"Bearer {provider.key}"
    try:
        status, data = await http("GET", url, headers, {}, timeout)
    except Exception as exc:  # pragma: no cover - network edge
        logger.warning("model discovery failed for %s: %s", provider.name, exc)
        return list(provider.models)
    if status != 200:
        logger.warning("model discovery %s: HTTP %s", provider.name, status)
        return list(provider.models)
    if provider.api_style is ApiStyle.OLLAMA:
        names = [m.get("name", "") for m in data.get("models", [])]
    else:
        items = data.get("data")
        if isinstance(items, list):
            names = [m.get("id", "") for m in items]
        else:
            names = [str(m) for m in (data.get("models") or [])]
    names = [n for n in names if n]
    provider.live_models = names or None
    if names:
        logger.info("model discovery %s: %d live model(s)", provider.name, len(names))
    return names


# ── Registry builder ────────────────────────────────────────────────────────

# Per-provider live endpoints (2026 catalog; model *names* are reconciled at
# runtime via discover_models, so these bases are what matter).
GROQ_BASE = "https://api.groq.com/openai/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MISTRAL_BASE = "https://api.mistral.ai/v1"
GITHUB_MODELS_BASE = "https://models.inference.ai.azure.com"   # GitHub Models (OpenAI-compat)
CLOUDFLARE_BASE = "https://inference.cloudflare.com/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def build_registry(config) -> List[Provider]:
    """Build the ordered provider registry from a ``HarnessConfig``.

    Ordering = failover preference. LOCAL providers first (free + private),
    then the FREE pool (Groq primary → OpenRouter → Mistral), then the PREMIUM
    frontier (GitHub Models free → Gemini RESTRICTED → Cloudflare → OpenRouter
    paid). Availability is derived from key presence + explicit opt-outs.
    """
    regs: List[Provider] = []

    def dis(name: str) -> bool:
        return name in getattr(config, "disabled_providers", set())

    # ── LOCAL_LIGHT (Ollama) ──────────────────────────────────────────────
    ollama_on = bool(getattr(config, "ollama_url", None)) and not dis("ollama")
    regs.append(Provider(
        name="ollama", tier="LOCAL_LIGHT", lane=DataLane.SAFE, api_style=ApiStyle.OLLAMA,
        base_url=getattr(config, "ollama_url", "http://127.0.0.1:11434"), key=None,
        models=["hf.co/dr-ry/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M", "qwen2.5:7b"],
        context=32768, rpm=60, rpd=100000, enabled=ollama_on,
    ))

    # ── LOCAL_HEAVY (Qwen3.8-27B on cloud GPU, $0, OFF unless URL set) ────
    lh_url = getattr(config, "local_heavy_url", None)
    lh_on = bool(lh_url) and not dis("local_heavy")
    regs.append(Provider(
        name="local_heavy", tier="LOCAL_HEAVY", lane=DataLane.SAFE, api_style=ApiStyle.OPENAI_COMPAT,
        base_url=lh_url or "", key=getattr(config, "local_heavy_api_key", None),
        models=["qwen3.8-27b"], context=32768, rpm=60, rpd=100000,
        hourly_cost=getattr(config, "local_heavy_hourly_cost", 0.0), enabled=lh_on,
    ))

    # ── FREE pool ─────────────────────────────────────────────────────────
    groq_key = getattr(config, "groq_api_key", None)
    if groq_key and not dis("groq"):
        regs.append(Provider(
            name="groq", tier="PAID_FREE", lane=DataLane.SAFE, api_style=ApiStyle.OPENAI_COMPAT,
            base_url=GROQ_BASE, key=groq_key,
            models=["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"],
            context=131072, rpm=30, rpd=1000,
        ))
    openrouter_key = getattr(config, "openrouter_api_key", None)
    if openrouter_key and not dis("openrouter"):
        regs.append(Provider(
            name="openrouter", tier="PAID_FREE", lane=DataLane.SAFE, api_style=ApiStyle.OPENAI_COMPAT,
            base_url=OPENROUTER_BASE, key=openrouter_key,
            models=["qwen/qwen3.8-27b:free", "nvidia/nemotron-3-ultra:free", "poolside/laguna-s-2.1:free"],
            context=262144, rpm=20, rpd=1000,
        ))
    mistral_key = getattr(config, "mistral_api_key", None)
    if mistral_key and not dis("mistral"):
        regs.append(Provider(
            name="mistral", tier="PAID_FREE", lane=DataLane.SAFE, api_style=ApiStyle.OPENAI_COMPAT,
            base_url=MISTRAL_BASE, key=mistral_key,
            models=["codestral", "mistral-small-latest", "ministral-3-14b-latest"],
            context=256000, rpm=500, rpd=1000,
        ))

    # ── PREMIUM frontier (free first; paid OpenRouter as overflow) ────────
    github_token = getattr(config, "github_token", None)
    if github_token and not dis("github"):
        regs.append(Provider(
            name="github_models", tier="PAID_PREMIUM", lane=DataLane.RESTRICTED,
            api_style=ApiStyle.OPENAI_COMPAT, base_url=GITHUB_MODELS_BASE, key=github_token,
            models=["gpt-4o", "claude-3-5-sonnet", "gpt-4o-mini"],
            context=128000, rpm=15, rpd=150,
        ))
    gemini_key = getattr(config, "gemini_api_key", None)
    if gemini_key and not dis("gemini"):
        regs.append(Provider(
            name="gemini", tier="PAID_PREMIUM", lane=DataLane.RESTRICTED,
            api_style=ApiStyle.GEMINI_NATIVE, base_url=GEMINI_BASE, key=gemini_key,
            models=["gemini-2.5-flash", "gemini-2.5-flash-lite"],
            context=1000000, rpm=15, rpd=1500,
        ))
    if (getattr(config, "cloudflare_api_token", None)
            and getattr(config, "cloudflare_account_id", None)
            and not dis("cloudflare")):
        regs.append(Provider(
            name="cloudflare", tier="PAID_FREE", lane=DataLane.SAFE, api_style=ApiStyle.OPENAI_COMPAT,
            base_url=f"{CLOUDFLARE_BASE}/{config.cloudflare_account_id}",
            key=config.cloudflare_api_token,
            models=["@cf/openai/gpt-oss-120b"], context=131072, rpm=30, rpd=1000,
        ))

    return regs


def providers_for_tier(registry: List[Provider], tier: str) -> List[Provider]:
    """Enabled + available providers for a tier, in failover order."""
    return [p for p in registry if p.tier == tier and p.enabled and p.available]
