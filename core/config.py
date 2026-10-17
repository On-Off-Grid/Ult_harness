# core/config.py
"""Harness configuration.

Keys come from the environment / the gitignored ``.env`` (loaded by ``main.py``).
Real environment variables always win over ``.env`` (``override=False``). Nothing
secret is ever stored here — only env-var *values* that were present at load time.

Provider enable/disable: a provider is available when (a) its key is present and
(b) it has not been explicitly disabled via ``HARNESS_DISABLE_<NAME>=1``. The
``disabled_providers`` set is the explicit opt-out list.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, Optional


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


_PLACEHOLDER_MARKERS = (
    "replace", "changeme", "change_me", "change-me", "your_key", "your-key",
    "yourkey", "example", "dummy", "placeholder", "insert", "todo", "xxxx",
)


def _clean_key(raw: Optional[str]) -> Optional[str]:
    """Normalize a key env var: empty or obviously-placeholder values
    (``ghp_REPLACE_ME``, ``sk-EXAMPLE_KEY`` ...) count as *unset*. A
    half-filled ``.env`` must never advertise a fake-enabled provider."""
    if raw is None:
        return None
    v = raw.strip()
    if not v:
        return None
    low = v.lower()
    if any(marker in low for marker in _PLACEHOLDER_MARKERS):
        return None
    return v


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass
class HarnessConfig:
    dry_run: bool = False
    interactsh_mode: str = "public"       # "public" | "selfhosted"
    interactsh_url: str = "https://interactsh.com"
    egress_proxy_port: int = 8080
    war_room_port: int = 3333             # (S7) separate-war-room option; S7 serves same-origin on api_port
    api_port: int = 8001                  # FIX A-1: admiral on 8001, not 8000
    mempalace_url: str = "http://127.0.0.1:8000"
    ollama_url: str = "http://127.0.0.1:11434"
    groq_api_key: Optional[str] = None
    max_session_cost_usd: float = 10.00
    workspace_dir: str = "./workspace"

    # ── S5: multi-provider routing (FREE / PREMIUM lanes) ────────────────
    openrouter_api_key: Optional[str] = None
    github_token: Optional[str] = None        # GitHub Models free frontier
    mistral_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    cloudflare_account_id: Optional[str] = None
    cloudflare_api_token: Optional[str] = None

    # ── S5: LOCAL_HEAVY (Qwen3.8-27B on a cloud GPU, on-demand) ─────────
    # Off unless local_heavy_url is set; then it is a $0 OpenAI-compatible
    # llama-server endpoint reached over a private network.
    local_heavy_url: Optional[str] = None
    local_heavy_api_key: Optional[str] = None
    local_heavy_hourly_cost: float = 0.00     # GPU-hour cost (RunPod ~0.34–0.45)

    # Explicit per-provider opt-out (set via HARNESS_DISABLE_<NAME>=1).
    disabled_providers: set = field(default_factory=set)

    @classmethod
    def load_from_env(cls) -> "HarnessConfig":
        disabled = {
            name.lower()
            for name in ("groq", "openrouter", "github", "mistral",
                         "gemini", "cloudflare", "local_heavy", "ollama")
            if _env_flag(f"HARNESS_DISABLE_{name.upper()}")
        }
        return cls(
            dry_run=_env_flag("HARNESS_DRY_RUN"),
            interactsh_mode=os.getenv("INTERACTSH_MODE", "public"),
            interactsh_url=os.getenv("INTERACTSH_URL", "https://interactsh.com"),
            egress_proxy_port=_env_int("EGRESS_PROXY_PORT", 8080),
            war_room_port=_env_int("WAR_ROOM_PORT", 3333),
            api_port=_env_int("HARNESS_API_PORT", 8001),
            mempalace_url=os.getenv("HARNESS_MEMPALACE_URL", "http://127.0.0.1:8000"),
            ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
            groq_api_key=_clean_key(os.getenv("GROQ_API_KEY")),
            openrouter_api_key=_clean_key(os.getenv("OPENROUTER_API_KEY")),
            github_token=_clean_key(os.getenv("GITHUB_TOKEN")),
            mistral_api_key=_clean_key(os.getenv("MISTRAL_API_KEY")),
            gemini_api_key=_clean_key(os.getenv("GEMINI_API_KEY")),
            cloudflare_account_id=_clean_key(os.getenv("CLOUDFLARE_ACCOUNT_ID")),
            cloudflare_api_token=_clean_key(os.getenv("CLOUDFLARE_API_TOKEN")),
            local_heavy_url=os.getenv("LOCAL_HEAVY_URL") or None,
            local_heavy_api_key=_clean_key(os.getenv("LOCAL_HEAVY_API_KEY")),
            local_heavy_hourly_cost=_env_float("LOCAL_HEAVY_HOURLY_COST", 0.0),
            max_session_cost_usd=_env_float("HARNESS_MAX_SESSION_COST", 10.0),
            workspace_dir=os.getenv("HARNESS_WORKSPACE", "./workspace"),
            disabled_providers=disabled,
        )

    # Convenience: is a provider usable right now? (key present + not disabled.)
    def provider_enabled(self, name: str) -> bool:
        key = name.lower()
        if key in self.disabled_providers:
            return False
        return bool(self._provider_key(name))

    def _provider_key(self, name: str) -> Optional[str]:
        return {
            "groq": self.groq_api_key,
            "openrouter": self.openrouter_api_key,
            "github": self.github_token,
            "mistral": self.mistral_api_key,
            "gemini": self.gemini_api_key,
            "cloudflare": self.cloudflare_api_token,
            "local_heavy": self.local_heavy_url,
            "ollama": self.ollama_url,
        }.get(name.lower())
