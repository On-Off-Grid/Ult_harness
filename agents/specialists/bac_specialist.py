# agents/specialists/bac_specialist.py
import logging
import uuid
from typing import List

from agents.dual_session_tester import DualSessionTester
from agents.specialist_base import DualSessionMixin, ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class BACSpecialist(DualSessionMixin, ISpecialist):
    """Broken Access Control (BAC) specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.BAC

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

        # Setup tester
        tester = DualSessionTester()
        
        # Test targets matching admin endpoints / restricted functions
        results = await tester.run_matrix(
            url=target,
            method="GET",
            session_ctx=session_ctx,
        )

        is_idor, is_bac, desc = tester.analyze_results(results)
        if is_bac:
            finding = Finding(
                finding_id=f"bac_{uuid.uuid4().hex[:8]}",
                title="Broken Access Control (BAC) Detected",
                description=desc,
                vuln_category=self.category.value,
                endpoint=target,
                evidence={"matrix_results": results},
                confidence=0.9,
            )
            findings.append(finding)

        return findings
