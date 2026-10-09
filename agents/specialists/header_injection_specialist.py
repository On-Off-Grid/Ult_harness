# agents/specialists/header_injection_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class HeaderInjectionSpecialist(ISpecialist):
    """HTTP Header Injection / CRLF specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.HEADER_INJECTION

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

        # CRLF injection payload (adds a Custom-Header)
        payloads = [
            "%0d%0aCustom-Header:%20Hacked",
            "\r\nCustom-Header: Hacked",
        ]

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                test_url = f"{target}?param={p}"
                try:
                    async with session.get(test_url, timeout=10) as response:
                        if "Custom-Header" in response.headers:
                            finding = Finding(
                                finding_id=f"header_inj_{uuid.uuid4().hex[:8]}",
                                title="HTTP Header Injection (CRLF) Confirmed",
                                description="Successfully injected CRLF sequences to spawn a custom header.",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "url": test_url,
                                    "response_headers": dict(response.headers),
                                },
                                confidence=0.95,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error requesting {test_url}: {e}")

        return findings
