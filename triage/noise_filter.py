# triage/noise_filter.py
"""Pre-triage noise filter — drops non-bountiable findings BEFORE they enter
the triage pipeline.

Bug bounty platforms consistently reject certain finding categories. Filtering
them early saves LLM tokens, operator time, and avoids reputation damage from
submitting junk reports.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DropReason(str, Enum):
    """Why a finding was auto-dropped."""
    MISSING_SECURITY_HEADERS = "missing_security_headers"
    SPF_DMARC = "spf_dmarc_misconfiguration"
    SELF_XSS = "self_xss"
    RATE_LIMIT_ABSENCE = "rate_limit_absence"
    COOKIE_FLAGS = "cookie_flags"
    CLICKJACKING_NOLOGIN = "clickjacking_on_non_authenticated_page"
    MIXED_CONTENT = "mixed_content"
    SOFTWARE_VERSION_DISCLOSURE = "software_version_disclosure"
    AUTOCOMPLETE = "autocomplete_not_disabled"
    HOST_HEADER_INJECTION_NO_IMPACT = "host_header_injection_no_impact"
    BEST_PRACTICE = "best_practice_violation"


# ── Known non-bountiable patterns ────────────────────────────────────────
# Each entry: (keywords_in_title, keywords_in_description) → DropReason
NOISE_PATTERNS: List[Dict[str, Any]] = [
    {
        "title_contains": ["missing", "security header"],
        "desc_contains": ["csp", "hsts", "x-frame-options", "x-content-type-options",
                          "referrer-policy", "permissions-policy"],
        "reason": DropReason.MISSING_SECURITY_HEADERS,
    },
    {
        "title_contains": ["spf", "dmarc", "dkim"],
        "desc_contains": ["email", "spoofing", "dns txt"],
        "reason": DropReason.SPF_DMARC,
    },
    {
        "title_contains": ["self-xss", "self xss"],
        "desc_contains": ["paste", "console", "own browser", "own session"],
        "reason": DropReason.SELF_XSS,
    },
    {
        "title_contains": ["rate limit", "brute force"],
        "desc_contains": ["no rate limit", "missing rate limit", "unlimited attempts"],
        "reason": DropReason.RATE_LIMIT_ABSENCE,
    },
    {
        "title_contains": ["cookie", "httponly", "secure flag"],
        "desc_contains": ["httponly", "secure flag", "samesite"],
        "reason": DropReason.COOKIE_FLAGS,
    },
    {
        "title_contains": ["clickjacking"],
        "desc_contains": ["non-authenticated", "public page", "login page", "no sensitive action"],
        "reason": DropReason.CLICKJACKING_NOLOGIN,
    },
    {
        "title_contains": ["mixed content"],
        "desc_contains": ["http://", "mixed content", "insecure resource"],
        "reason": DropReason.MIXED_CONTENT,
    },
    {
        "title_contains": ["version disclosure", "server header", "x-powered-by"],
        "desc_contains": ["version", "server:", "x-powered-by", "technology disclosure"],
        "reason": DropReason.SOFTWARE_VERSION_DISCLOSURE,
    },
    {
        "title_contains": ["autocomplete"],
        "desc_contains": ["autocomplete", "password field", "autofill"],
        "reason": DropReason.AUTOCOMPLETE,
    },
    {
        "title_contains": ["host header"],
        "desc_contains": ["host header injection", "no impact", "informational"],
        "reason": DropReason.HOST_HEADER_INJECTION_NO_IMPACT,
    },
]


@dataclass
class Finding:
    """Raw finding from a specialist agent, before triage."""
    finding_id: str
    title: str
    description: str
    vuln_category: str
    endpoint: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FilterResult:
    """Output of the noise filter — tells the caller whether the finding passed."""
    passed: bool
    reason: Optional[DropReason] = None
    reason_detail: str = ""
    original_finding: Optional[Finding] = None


class NoiseFilter:
    """Filters out non-bountiable findings using pattern matching.

    Usage:
        nf = NoiseFilter()
        result = nf.filter(finding)
        if result.passed:
            # proceed to triage state machine
        else:
            logger.info(f"Dropped: {result.reason}")
    """

    def __init__(self, extra_patterns: Optional[List[Dict[str, Any]]] = None):
        self.patterns = NOISE_PATTERNS.copy()
        if extra_patterns:
            self.patterns.extend(extra_patterns)
        self._dropped: List[FilterResult] = []

    def filter(self, finding: Finding) -> FilterResult:
        """Check a finding against all noise patterns.

        Returns FilterResult with passed=True if the finding should proceed,
        or passed=False with the reason if it was filtered.
        """
        title_lower = finding.title.lower()
        desc_lower = finding.description.lower()

        for pattern in self.patterns:
            title_match = any(kw in title_lower for kw in pattern["title_contains"])
            desc_match = any(kw in desc_lower for kw in pattern["desc_contains"])

            if title_match and desc_match:
                result = FilterResult(
                    passed=False,
                    reason=pattern["reason"],
                    reason_detail=(
                        f"Title matched: {pattern['title_contains']}, "
                        f"Desc matched: {pattern['desc_contains']}"
                    ),
                    original_finding=finding,
                )
                self._dropped.append(result)

                logger.info(
                    "noise_filter_drop",
                    extra={
                        "finding_id": finding.finding_id,
                        "title": finding.title,
                        "drop_reason": pattern["reason"].value,
                    },
                )
                return result

        return FilterResult(passed=True, original_finding=finding)

    def get_drop_summary(self) -> Dict[str, int]:
        """Count of dropped findings per reason — useful for War Room display."""
        summary: Dict[str, int] = {}
        for r in self._dropped:
            key = r.reason.value if r.reason else "unknown"
            summary[key] = summary.get(key, 0) + 1
        return summary

    @property
    def total_dropped(self) -> int:
        return len(self._dropped)
