# reporting/taxonomy.py
"""Vulnerability taxonomy — VRT / CWE / CVSS 3.1 classification.

Implements the TaxonomyMapper from
harness_gap_bridging_specification_v2_1_2.md §3.1 (archived:
docs/archive/legacy-v2/), adapted to the verified `core.types.VulnCategory`
enum (16 categories).

These mappings are a triage *aid* for report drafting — the final severity
call always belongs to the operator (workflow stage 7).
"""

import logging
from typing import Any, Dict

from core.types import Task, VulnCategory

logger = logging.getLogger(__name__)

# ── VRT / CWE mapping per category ────────────────────────────────────────
# VRT category/variant names follow the HackerOne VRT phrasing so reports
# read naturally to program triage; CWE ids are the canonical mappings.
VRT_MAPPINGS: Dict[VulnCategory, Dict[str, Any]] = {
    VulnCategory.SQLI:                 {"category": "SQL Injection", "variant": "Blind / Error-Based", "cwe": 89},
    VulnCategory.XSS:                 {"category": "Cross-Site Scripting", "variant": "Reflected / Stored", "cwe": 79},
    VulnCategory.SSRF:                {"category": "Server-Side Request Forgery", "variant": "Open SSRF", "cwe": 918},
    VulnCategory.IDOR:                {"category": "Broken Object Level Authorization", "variant": "Insecure Direct Object Reference", "cwe": 639},
    VulnCategory.LFI:                 {"category": "Path Traversal", "variant": "Local File Inclusion", "cwe": 22},
    VulnCategory.RCE:                 {"category": "Command Injection", "variant": "Remote Code Execution", "cwe": 78},
    VulnCategory.XXE:                 {"category": "XML External Entity Processing", "variant": "External Entity Disclosure", "cwe": 611},
    VulnCategory.JWT:                 {"category": "Improper Cryptographic Signature", "variant": "Algorithm Confusion / Weak Signing", "cwe": 347},
    VulnCategory.OPEN_REDIRECT:       {"category": "URL Redirection to Untrusted Site", "variant": "Open Redirect", "cwe": 601},
    VulnCategory.PROTOTYPE_POLLUTION: {"category": "Client-Side Prototype Pollution", "variant": "Prototype Pollution", "cwe": 1321},
    VulnCategory.CSTI:                {"category": "Code Injection", "variant": "Server-Side Template Injection", "cwe": 94},
    VulnCategory.MASS_ASSIGNMENT:     {"category": "Improper Control of Input to System", "variant": "Mass Assignment", "cwe": 915},
    VulnCategory.HEADER_INJECTION:    {"category": "Improper Neutralization", "variant": "HTTP Request Smuggling / CRLF Injection", "cwe": 440},
    VulnCategory.BAC:                 {"category": "Broken Access Control", "variant": "Authorization Bypass", "cwe": 285},
    VulnCategory.AI_JAILBREAK:        {"category": "Improper Control of Generation Effect", "variant": "Prompt Injection / Jailbreak", "cwe": 400},
    VulnCategory.BUSINESS_LOGIC:      {"category": "Business Logic", "variant": "Broken Function-Level Logic", "cwe": 670},
}

_DEFAULT_MAPPING = {"category": "Other", "variant": "Generic", "cwe": 200}

# ── CVSS 3.1 vectors (gap-bridging spec §3.1) ─────────────────────────────
_VECTOR_CRITICAL = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
_VECTOR_SSRF     = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N"
_VECTOR_DEFAULT  = "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:L/A:N"


class TaxonomyMapper:
    """Maps a VulnCategory to VRT / CWE / CVSS for report drafting.

    Usage:
        mapper = TaxonomyMapper()
        mapper.get_vrt(VulnCategory.SQLI)      # "SQL Injection -> Blind / Error-Based"
        mapper.get_cwe(VulnCategory.SQLI)      # 89
        mapper.classify(task)                  # full dict for a Task
    """

    def get_vrt(self, category: VulnCategory) -> str:
        data = VRT_MAPPINGS.get(category, _DEFAULT_MAPPING)
        return f"{data['category']} -> {data['variant']}"

    def get_cwe(self, category: VulnCategory) -> int:
        return VRT_MAPPINGS.get(category, _DEFAULT_MAPPING)["cwe"]

    def get_cvss_vector(self, category: VulnCategory, impact_level: str = "HIGH") -> str:
        """Return a CVSS 3.1 vector string for the category.

        impact_level is accepted for API symmetry with the gap-bridging
        spec; vectors are category-driven (refine per-finding in S5).
        """
        if category in (VulnCategory.SQLI, VulnCategory.RCE):
            return _VECTOR_CRITICAL
        if category == VulnCategory.SSRF:
            return _VECTOR_SSRF
        return _VECTOR_DEFAULT

    @staticmethod
    def severity_from_vector(vector: str) -> str:
        """Coarse severity band from a CVSS 3.1 vector (no lib dependency)."""
        scope_changed = "/S:C/" in vector
        highs = sum(marker in vector for marker in ("C:H", "I:H", "A:H"))
        if scope_changed and highs >= 2:
            return "Critical"
        if highs >= 2 or scope_changed:
            return "High"
        if highs == 1:
            return "Medium"
        return "Low"

    def classify(self, task: Task) -> Dict[str, Any]:
        """Full classification bundle for a task's finding."""
        vector = self.get_cvss_vector(task.vuln_category)
        return {
            "vrt": self.get_vrt(task.vuln_category),
            "cwe": self.get_cwe(task.vuln_category),
            "cvss_vector": vector,
            "severity": self.severity_from_vector(vector),
        }
