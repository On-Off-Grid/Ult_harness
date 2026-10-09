# agents/specialists/open_redirect_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class OpenRedirectSpecialist(ISpecialist):
    """Open Redirect specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.OPEN_REDIRECT

    async def scan(
        self,
        target: str,
        scope: TargetScope,
        session_ctx: MultiSessionContext,
        correlation_id: str,
    ) -> List[Finding]:
        findings = []

        if await self.check_false_positive(target):
            return findings

        payloads = [
            "https://evil.com",
            "//evil.com",
            "/\\evil.com",
        ]

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                test_url = f"{target}?next={p}"
                try:
                    # Don't follow redirects to catch 302 Location header
                    async with session.get(test_url, allow_redirects=False, timeout=10) as response:
                        location = response.headers.get("Location", "")
                        if location == p or "evil.com" in location:
                            finding = Finding(
                                finding_id=f"open_redirect_{uuid.uuid4().hex[:8]}",
                                title="Open Redirect Detected",
                                description=f"Location header redirects to untrusted host using payload: {p}",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "url": test_url,
                                    "location_header": location,
                                    "status": response.status,
                                },
                                confidence=0.85,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error requesting {test_url}: {e}")

        return findings
