# agents/specialists/prototype_pollution_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class PrototypePollutionSpecialist(ISpecialist):
    """Prototype Pollution specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.PROTOTYPE_POLLUTION

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

        # Payload to trigger Object.prototype modification
        payloads = [
            '{"__proto__": {"polluted": "yes"}}',
            '{"constructor": {"prototype": {"polluted": "yes"}}}',
        ]

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                try:
                    async with session.post(
                        target,
                        data=p,
                        headers={"Content-Type": "application/json"},
                        timeout=10,
                    ) as response:
                        body = await response.text()
                        # If server echoes prototype modification or indicates state change
                        if "polluted" in body:
                            finding = Finding(
                                finding_id=f"proto_poll_{uuid.uuid4().hex[:8]}",
                                title="Server-Side Prototype Pollution Detected",
                                description="Server reflected prototype pollution property injection.",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "response": body[:200],
                                },
                                confidence=0.8,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error posting json payload to {target}: {e}")

        return findings
