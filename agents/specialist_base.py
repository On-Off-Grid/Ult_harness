# agents/specialist_base.py
"""Abstract base class and mixins for all specialist agents.

Provides integrated token tracking, mempalace false positive caching checks,
out-of-band mixin for SSRF/RCE/XXE, and multi-session authorization mixin.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import aiohttp

from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class ISpecialist(ABC):
    """Base interface for all specialist vulnerability agents.

    Each agent has a category and a scan entry point.
    """

    def __init__(self, model_router=None, mempalace_url: str = "http://127.0.0.1:8000"):
        self.model_router = model_router
        self.mempalace_url = mempalace_url

    @property
    @abstractmethod
    def category(self) -> VulnCategory:
        """The vulnerability category this specialist focuses on."""
        pass

    @abstractmethod
    async def scan(
        self,
        target: str,
        scope: TargetScope,
        session_ctx: MultiSessionContext,
        correlation_id: str,
    ) -> List[Finding]:
        """Perform scan on the target endpoint.

        Returns list of raw Findings.
        """
        pass

    async def check_false_positive(self, endpoint: str) -> bool:
        """Query mempalace to see if this endpoint has a matching known false positive pattern."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.mempalace_url}/search"
                payload = {
                    "query": f"category:{self.category.value} endpoint:{endpoint}",
                    "mode": "fp",
                }
                async with session.post(url, json=payload, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("matches"):
                            logger.info(
                                f"FP match found in mempalace for {endpoint} under {self.category.value}"
                            )
                            return True
        except Exception as e:
            logger.warning(f"Failed to query mempalace for FP patterns: {e}")
        return False


class OOBMixin:
    """Mixin for specialists requiring Out-Of-Band validation (SSRF, RCE, XXE)."""

    def __init__(self, oob_engine=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.oob_engine = oob_engine

    def embed_oob_payload(self, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate a unique OOB callback URL for triggering external callback
        validation. ``context`` (endpoint / category / correlation_id) is
        registered with the shared hunt OOB session so the receive side
        (``OpAdmiral.poll_oob``) can attribute a callback back to the finding
        that fired it (S8.1)."""
        if self.oob_engine:
            return self.oob_engine.generate_payload(context)
        return "http://interact.oast.me/placeholder_oob"


class DualSessionMixin:
    """Placeholder mixin for specialists requiring session comparison (IDOR, BAC)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
