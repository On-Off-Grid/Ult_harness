# core/config.py
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class HarnessConfig:
    dry_run: bool = False
    interactsh_mode: str = "public"       # "public" | "selfhosted"
    interactsh_url: str = "https://interactsh.com"
    egress_proxy_port: int = 8080
    war_room_port: int = 3333
    api_port: int = 8001                  # FIX A-1: admiral on 8001, not 8000
    mempalace_url: str = "http://127.0.0.1:8000"
    ollama_url: str = "http://127.0.0.1:11434"
    groq_api_key: Optional[str] = None
    max_session_cost_usd: float = 10.00
    workspace_dir: str = "./workspace"

    @classmethod
    def load_from_env(cls) -> "HarnessConfig":
        return cls(
            dry_run=os.getenv("HARNESS_DRY_RUN", "false").lower() == "true",
            interactsh_mode=os.getenv("INTERACTSH_MODE", "public"),
            interactsh_url=os.getenv("INTERACTSH_URL", "https://interactsh.com"),
            egress_proxy_port=int(os.getenv("EGRESS_PROXY_PORT", "8080")),
            war_room_port=int(os.getenv("WAR_ROOM_PORT", "3333")),
            api_port=int(os.getenv("HARNESS_API_PORT", "8001")),
            groq_api_key=os.getenv("GROQ_API_KEY"),
            workspace_dir=os.getenv("HARNESS_WORKSPACE", "./workspace"),
        )
