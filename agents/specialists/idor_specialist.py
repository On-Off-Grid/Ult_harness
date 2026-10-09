# agents/specialists/idor_specialist.py
import logging
import uuid
from typing import List

from agents.dual_session_tester import DualSessionTester
from agents.specialist_base import DualSessionMixin, ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class IDORSpecialist(DualSessionMixin, ISpecialist):
    """Insecure Direct Object Reference (IDOR) specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.IDOR

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

        # Setup tester (can configure HTTP_PROXY if needed)
        tester = DualSessionTester()
        
        # Assume endpoint has an id parameter that can be manipulated (e.g. /api/user/123)
        # In a real scanner, target would represent a specific resource parameter to fuzz.
        results = await tester.run_matrix(
            url=target,
            method="GET",
            session_ctx=session_ctx,
        )

        is_idor, is_bac, desc = tester.analyze_results(results)
        if is_idor:
            finding = Finding(
                finding_id=f"idor_{uuid.uuid4().hex[:8]}",
                title="Insecure Direct Object Reference (IDOR) Detected",
                description=desc,
                vuln_category=self.category.value,
                endpoint=target,
                evidence={"matrix_results": results},
                confidence=0.9,
            )
            findings.append(finding)

        return findings
