# agents/specialists/xss_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class XSSSpecialist(ISpecialist):
    """Cross-Site Scripting (XSS) specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.XSS

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

        prompt = (
            f"Generate 3 XSS test payloads for endpoint: {target}. "
            f"Format as raw payloads only, one per line."
        )

        payloads = [
            "<script>alert(1)</script>",
            '"><img src=x onerror=alert(1)>',
            "javascript:alert(1)",
        ]

        if self.model_router:
            try:
                resp = await self.model_router.route(
                    task_type="payload_craft",
                    prompt=prompt,
                    agent_id="xss_specialist",
                    task_id=correlation_id,
                )
                generated = [line.strip() for line in resp.text.split("\n") if line.strip()]
                if generated:
                    payloads = generated[:5]
            except Exception as e:
                logger.warning(f"Failed to use ModelRouter for XSS payloads: {e}")

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                test_url = f"{target}?input={p}"
                try:
                    async with session.get(test_url, timeout=10) as response:
                        body = await response.text()
                        if p in body:
                            finding = Finding(
                                finding_id=f"xss_{uuid.uuid4().hex[:8]}",
                                title="Reflected XSS Detected",
                                description=f"Payload was reflected unsanitized in the response body.",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "url": test_url,
                                    "status": response.status,
                                },
                                confidence=0.75,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error requesting {test_url}: {e}")

        return findings
