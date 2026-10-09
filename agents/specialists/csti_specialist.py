# agents/specialists/csti_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class CSTISpecialist(ISpecialist):
    """Client-Side Template Injection (CSTI) specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.CSTI

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

        # Angular/Vue expression injection payloads
        payloads = [
            "{{7*7}}",
            "{{constructor.constructor('alert(1)')()}}",
        ]

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                test_url = f"{target}?input={p}"
                try:
                    async with session.get(test_url, timeout=10) as response:
                        body = await response.text()
                        if "49" in body:
                            finding = Finding(
                                finding_id=f"csti_{uuid.uuid4().hex[:8]}",
                                title="Client-Side Template Injection Detected",
                                description="Successfully evaluated math expression {{7*7}} in client-side HTML output.",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "url": test_url,
                                },
                                confidence=0.85,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error requesting {test_url}: {e}")

        return findings
