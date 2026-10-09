# agents/specialists/business_logic_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class BusinessLogicSpecialist(ISpecialist):
    """Business Logic specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.BUSINESS_LOGIC

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

        # Payload trying to exploit numeric overflows or negative quantities in carts
        payloads = [
            '{"quantity": -1}',
            '{"quantity": 0}',
            '{"amount": -100}',
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
                        # If response indicates negative amount success (e.g. price balance goes up or succeeds)
                        if response.status == 200 and ("success" in body or "balance" in body):
                            finding = Finding(
                                finding_id=f"biz_logic_{uuid.uuid4().hex[:8]}",
                                title="Business Logic Flaw (Negative Quantity/Price) Confirmed",
                                description="Successfully modified cart state with negative values.",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "response": body[:200],
                                },
                                confidence=0.9,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error posting json payload to {target}: {e}")

        return findings
