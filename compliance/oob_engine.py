# compliance/oob_engine.py
"""
OOBEngine: Out-of-band interaction engine using Interactsh.

Modes:
- "public": use public Interactsh (e.g. oast.me / oast.fun).[cite:1]
- "selfhosted": use self-hosted Interactsh at configured URL.

Responsibilities:
- Register a new OOB session.
- Generate unique payload URLs/domains for embedding in SSRF/RCE/XXE payloads.
- Poll for DNS/HTTP/SMTP interactions.
- Deregister/close the session.
"""

from __future__ import annotations

import asyncio
import random
import string
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from core.config import HarnessConfig


@dataclass
class OOBCallback:
    """Represents a single OOB interaction (DNS/HTTP/SMTP)."""

    type: str          # "dns", "http", "smtp", etc.
    timestamp: str
    raw: Dict[str, Any]


class OOBEngine:
    def __init__(self, mode: str = "public", base_domain: Optional[str] = None):
        cfg = HarnessConfig.load_from_env()
        self.mode = mode or cfg.interactsh_mode
        # For public mode, you typically use app.interactsh.com or oast.me.[cite:1][cite:16]
        self.base_domain = base_domain or "oast.me"
        self.session_id: Optional[str] = None
        self._closed = False

    async def init(self) -> None:
        """
        Initialize a new Interactsh session.

        In a full implementation, this would call the Interactsh API/client library
        to register a new session and obtain a unique domain.
        """
        # For now, we just generate a random session identifier.
        self.session_id = self._random_id()

    def generate_payload(self) -> str:
        """
        Returns a unique payload URL for embedding in requests.

        Example: http://<random>.<session>.<base_domain>/
        """
        if not self.session_id:
            # In case init() was not awaited
            self.session_id = self._random_id()
        token = self._random_id()
        return f"http://{token}.{self.session_id}.{self.base_domain}/"

    async def poll_callbacks(self) -> List[OOBCallback]:
        """
        Poll Interactsh for new interactions.

        In a full implementation, this would query the Interactsh endpoint for logs.
        Here we return an empty list as a skeleton.
        """
        if self._closed:
            return []
        # TODO: integrate with interactsh-py / HTTP API.
        await asyncio.sleep(0.0)
        return []

    async def close(self) -> None:
        """
        Deregister the Interactsh session and clean up resources.
        """
        # TODO: call Interactsh API to delete session.
        self._closed = True

    @staticmethod
    def _random_id(length: int = 10) -> str:
        return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))
