# tests/test_s3_reporting.py
"""S3.2 — TaxonomyMapper + ReportWriter: VRT/CWE/CVSS mapping, the
CONFIRMED/CHAINED-only report gate, and on-disk platform output."""
from __future__ import annotations

import pytest

from core.types import (
    Platform,
    Task,
    VulnCategory,
    VulnStatus,
)
from reporting.taxonomy import TaxonomyMapper, VRT_MAPPINGS
from reporting.writers import REPORTABLE_STATUSES, ReportGateError, ReportWriter


def _task(category: VulnCategory, status: VulnStatus,
          wing: str = "acme-corp") -> Task:
    return Task(
        task_id="task_test123456",
        wing_id=wing,
        specialist_id=f"{category.value}_specialist",
        correlation_id="corr123",
        target_endpoint=f"https://app.example.com/{category.value}",
        vuln_category=category,
        status=status,
        metadata={"finding_id": "f1"},
    )


# ── TaxonomyMapper ────────────────────────────────────────────────────────

class TestTaxonomy:
    def test_all_16_categories_have_mapping(self):
        assert set(VRT_MAPPINGS.keys()) == set(VulnCategory), (
            "every VulnCategory needs a VRT/CWE mapping"
        )

    def test_vrt_string_shape(self):
        mapper = TaxonomyMapper()
        vrt = mapper.get_vrt(VulnCategory.SQLI)
        assert vrt.startswith("SQL Injection")
        assert "->" in vrt

    def test_known_cwe_ids(self):
        mapper = TaxonomyMapper()
        assert mapper.get_cwe(VulnCategory.SQLI) == 89
        assert mapper.get_cwe(VulnCategory.XSS) == 79
        assert mapper.get_cwe(VulnCategory.IDOR) == 639
        assert mapper.get_cwe(VulnCategory.RCE) == 78
        assert mapper.get_cwe(VulnCategory.SSRF) == 918
        assert mapper.get_cwe(VulnCategory.JWT) == 347

    def test_cvss_vectors(self):
        mapper = TaxonomyMapper()
        crit = mapper.get_cvss_vector(VulnCategory.RCE)
        assert crit.startswith("CVSS:3.1/AV:N/AC:L/PR:N")
        assert "C:H/I:H/A:H" in crit
        ssrf = mapper.get_cvss_vector(VulnCategory.SSRF)
        assert "/S:C/" in ssrf

    def test_severity_from_vector(self):
        mapper = TaxonomyMapper()
        assert mapper.severity_from_vector(
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == "High"
        assert mapper.severity_from_vector(
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H") == "Critical"

    def test_classify_bundle(self):
        mapper = TaxonomyMapper()
        bundle = mapper.classify(_task(VulnCategory.SQLI, VulnStatus.CONFIRMED))
        assert bundle["cwe"] == 89
        assert bundle["severity"] == "High"
        assert bundle["vrt"].startswith("SQL Injection")
        assert bundle["cvss_vector"].startswith("CVSS:3.1/")


# ── ReportWriter ──────────────────────────────────────────────────────────

FINDING = {
    "title": "SQLi on login",
    "description": "Boolean-based blind SQLi via user parameter.",
    "impact": "Full database exfiltration possible.",
    "remediation": "Use parameterized queries.",
}
EVIDENCE = {
    "request": "POST /login HTTP/1.1\nuser=1' AND '1'='1",
    "response": "500 — SQL syntax error",
    "poc": "curl -X POST https://app.example.com/login -d \"user=1' AND '1'='1\"",
}


class TestReportGate:
    def test_only_confirmed_and_chained_reportable(self):
        for status in (VulnStatus.IDENTIFIED, VulnStatus.VALIDATING,
                       VulnStatus.FALSE_POSITIVE, VulnStatus.OUT_OF_SCOPE):
            with pytest.raises(ReportGateError):
                ReportWriter.assert_reportable(
                    _task(VulnCategory.SQLI, status))
        for status in REPORTABLE_STATUSES:
            ReportWriter.assert_reportable(_task(VulnCategory.SQLI, status))  # no raise

    def test_write_report_raises_pre_confirmation(self, tmp_path):
        writer = ReportWriter(str(tmp_path))
        with pytest.raises(ReportGateError):
            writer.write_report(
                _task(VulnCategory.SQLI, VulnStatus.VALIDATING),
                FINDING, EVIDENCE, Platform.HACKERONE)
        assert list(tmp_path.glob("*/reports/*")) == []

    def test_confirm_gate_via_admiral_status(self, tmp_path):
        """A finding the admiral still holds in VALIDATING cannot be reported
        even if the caller builds the Task themselves with a spoofed status —
        the writer re-checks task.status at render time."""
        writer = ReportWriter(str(tmp_path))
        spoofed = _task(VulnCategory.SQLI, VulnStatus.CONFIRMED)
        spoofed.status = VulnStatus.VALIDATING  # caller lies
        with pytest.raises(ReportGateError):
            writer.render_markdown(spoofed, FINDING, EVIDENCE, Platform.HACKERONE)


class TestRenderAndWrite:
    def test_platform_tailoring(self, tmp_path):
        writer = ReportWriter(str(tmp_path))
        task = _task(VulnCategory.SQLI, VulnStatus.CONFIRMED)

        h1 = writer.render_markdown(task, FINDING, EVIDENCE, Platform.HACKERONE)
        assert "HackerOne" in h1

        ywh = writer.render_markdown(task, FINDING, EVIDENCE, Platform.YESWEHACK)
        assert "YesWeHack" in ywh

        intig = writer.render_markdown(task, FINDING, EVIDENCE, Platform.INTIGRITI)
        assert "Intigriti" in intig

        # generic fallback for the remaining platforms
        bc = writer.render_markdown(task, FINDING, EVIDENCE, Platform.BUGCROWD)
        assert "bugcrowd" in bc

    def test_report_contains_all_sections(self, tmp_path):
        writer = ReportWriter(str(tmp_path))
        task = _task(VulnCategory.SQLI, VulnStatus.CONFIRMED)
        md = writer.render_markdown(task, FINDING, EVIDENCE, Platform.HACKERONE)
        for section in ("## Classification", "CWE-89", "CVSS:3.1/", "## Summary",
                        "## Steps to Reproduce", "## Impact", "## Evidence",
                        "## Remediation", "user=1' AND '1'='1"):
            assert section in md, f"missing section: {section}"

    def test_chained_task_gets_chain_note(self, tmp_path):
        writer = ReportWriter(str(tmp_path))
        task = _task(VulnCategory.SQLI, VulnStatus.CHAINED)
        task.metadata["chained_to"] = "task_parent_1"
        md = writer.render_markdown(task, FINDING, EVIDENCE, Platform.HACKERONE)
        assert "Chained finding" in md
        assert "task_parent_1" in md
        assert "CHAINED" in md

    def test_write_report_lands_in_wing_reports_dir(self, tmp_path):
        writer = ReportWriter(str(tmp_path))
        task = _task(VulnCategory.SQLI, VulnStatus.CONFIRMED)
        result = writer.write_report(task, FINDING, EVIDENCE, Platform.HACKERONE)
        assert result.path == tmp_path / "acme-corp" / "reports" / "task_test123456_sqli.md"
        assert result.path.exists()
        assert result.bytes_written > 0
        assert result.severity == "High"

    def test_task_id_sanitized_in_filename(self, tmp_path):
        writer = ReportWriter(str(tmp_path))
        task = _task(VulnCategory.SQLI, VulnStatus.CONFIRMED)
        task.task_id = "task/odd:chars here"
        result = writer.write_report(task, FINDING, EVIDENCE, Platform.HACKERONE)
        assert "/" not in result.path.name and ":" not in result.path.name
        assert result.path.exists()

    def test_evidence_keys_without_artifacts(self, tmp_path):
        writer = ReportWriter(str(tmp_path))
        task = _task(VulnCategory.LFI, VulnStatus.CONFIRMED)
        md = writer.render_markdown(task, None, {}, Platform.INTIGRITI)
        assert "No evidence artifacts captured" in md
        assert "(no description recorded)" in md
        assert "CWE-22" in md
