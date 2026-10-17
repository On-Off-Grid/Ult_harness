# reporting/writers.py
"""Platform-specific report writers (S3.2).

Gate: reports are generated ONLY for findings in CONFIRMED or CHAINED state —
anything else raises ReportGateError. This enforces workflow stage 7
("No report is generated without explicit operator approval": confirmation
in the state machine IS the approval gate).

Output: workspace/<wing>/reports/<task_id>_<category>.md (platform-ready
Markdown), per workflow_overview.md stage 8 (archived: docs/archive/legacy-v2/).
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.types import Platform, Task, VulnStatus
from reporting.taxonomy import TaxonomyMapper

logger = logging.getLogger(__name__)

REPORTABLE_STATUSES = (VulnStatus.CONFIRMED, VulnStatus.CHAINED)


class ReportGateError(RuntimeError):
    """Raised when a report is requested for a finding that is not
    CONFIRMED or CHAINED. The state machine is the approval gate."""


# ── Per-platform flavoring ────────────────────────────────────────────────
# The three platforms named in plan v3 S3.2 get tailored intros; the other
# two in the Platform enum share the generic template.
_PLATFORM_NOTES: Dict[Platform, str] = {
    Platform.HACKERONE: (
        "Submitted via HackerOne. Sections follow the H1 expected template "
        "(Summary / Impact / Steps / Evidence). Severity is an initial "
        "assessment — final triage by the program."
    ),
    Platform.INTIGRITI: (
        "Submitted via Intigriti. Severity and remediation follow the "
        "intigriti report structure; CWE reference included for triage."
    ),
    Platform.YESWEHACK: (
        "Submitted via YesWeHack. Vulnerability type mapped to the YWH "
        "classification (VRT phrasing); proof-of-concept included."
    ),
}
_GENERIC_NOTE = (
    "Platform: {name}. Severity and remediation are initial assessments — "
    "final classification belongs to the program triage."
)


@dataclass
class ReportResult:
    """Outcome of a report generation: the on-disk file + metadata."""
    task_id: str
    path: Path
    platform: Platform
    cwe: int
    cvss_vector: str
    severity: str
    bytes_written: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class ReportWriter:
    """Renders confirmed findings into platform-ready Markdown reports.

    Usage:
        writer = ReportWriter(workspace_dir="./workspace")
        result = writer.write_report(task, finding, evidence, platform)
        # result.path -> workspace/<wing>/reports/<task_id>_<category>.md
    """

    def __init__(self, workspace_dir: str = "./workspace", taxonomy: Optional[TaxonomyMapper] = None):
        self.workspace_dir = Path(workspace_dir)
        self.taxonomy = taxonomy or TaxonomyMapper()

    # ── Gate ────────────────────────────────────────────────────────────

    @staticmethod
    def assert_reportable(task: Task) -> None:
        """Raise unless the finding cleared the triage approval gate."""
        if task.status not in REPORTABLE_STATUSES:
            raise ReportGateError(
                f"Refusing to write report for {task.task_id}: status is "
                f"{task.status.value}, reports require CONFIRMED or CHAINED. "
                f"(Operator approval via triage is mandatory.)"
            )

    # ── Rendering ───────────────────────────────────────────────────────

    def render_markdown(
        self,
        task: Task,
        finding: Optional[Dict[str, Any]],
        evidence: Optional[Dict[str, Any]],
        platform: Platform,
    ) -> str:
        """Render the report body. Pure function — safe to preview."""
        self.assert_reportable(task)

        finding = finding or {}
        evidence = evidence or {}
        cls = self.taxonomy.classify(task)
        title = finding.get("title") or f"{cls['vrt']} on {task.target_endpoint}"
        description = finding.get("description") or "(no description recorded)"
        note = _PLATFORM_NOTES.get(
            platform, _GENERIC_NOTE.format(name=platform.value)
        )
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        evidence_lines = []
        if evidence.get("request"):
            evidence_lines.append(f"```\nRequest:\n{evidence['request']}\n```")
        if evidence.get("response"):
            evidence_lines.append(f"```\nResponse:\n{evidence['response']}\n```")
        if evidence.get("poc"):
            evidence_lines.append(f"**PoC:**\n```\n{evidence['poc']}\n```")
        if evidence.get("oob_callback"):
            evidence_lines.append(f"OOB callback evidence: {evidence['oob_callback']}")
        evidence_md = "\n\n".join(evidence_lines) if evidence_lines else "No evidence artifacts captured."

        chain_note = ""
        if task.status == VulnStatus.CHAINED:
            parent = task.metadata.get("chained_to")
            chain_note = (
                f"\n**Chained finding** — part of a chain"
                + (f" (parent: `{parent}`)" if parent else "")
                + ", raising overall impact.\n"
            )

        return f"""# {title}

**Program:** {task.wing_id}
**Platform:** {platform.value}
**Endpoint:** `{task.target_endpoint}`
**Status:** {task.status.value.upper()}
**Report generated:** {now}

{chain_note}
## Classification

| Field | Value |
|---|---|
| VRT | {cls['vrt']} |
| CWE | CWE-{cls['cwe']} |
| CVSS 3.1 | {cls['cvss_vector']} |
| Severity (initial) | {cls['severity']} |

## Summary

{description}

## Steps to Reproduce

1. See PoC / request evidence below.
2. Observe the anomalous response.

## Impact

{finding.get('impact', 'See classification — initial severity ' + cls['severity'] + '.')}

## Evidence

{evidence_md}

## Remediation

{finding.get('remediation', 'Apply parameterized queries / strict input validation / proper authorization checks per CWE-' + str(cls['cwe']) + ' guidance.')}

---
_{note}_
_Auto-drafted by Ult_harness (OpAdmiral) — operator review mandatory before submission._
"""

    # ── Disk output ─────────────────────────────────────────────────────

    def reports_dir(self, wing_id: str) -> Path:
        return self.workspace_dir / wing_id / "reports"

    def write_report(
        self,
        task: Task,
        finding: Optional[Dict[str, Any]],
        evidence: Optional[Dict[str, Any]],
        platform: Platform,
    ) -> ReportResult:
        """Render + persist the report to workspace/<wing>/reports/."""
        markdown = self.render_markdown(task, finding, evidence, platform)
        out_dir = self.reports_dir(task.wing_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", task.task_id)
        path = out_dir / f"{safe_id}_{task.vuln_category.value}.md"
        path.write_text(markdown, encoding="utf-8")

        cls = self.taxonomy.classify(task)
        logger.info(
            "report_written",
            extra={
                "task_id": task.task_id,
                "platform": platform.value,
                "path": str(path),
                "status": task.status.value,
            },
        )
        return ReportResult(
            task_id=task.task_id,
            path=path,
            platform=platform,
            cwe=cls["cwe"],
            cvss_vector=cls["cvss_vector"],
            severity=cls["severity"],
            bytes_written=path.stat().st_size,
        )
