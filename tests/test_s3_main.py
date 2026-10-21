# tests/test_s3_main.py
"""S3.3 — main.py CLI: --help (Gate S3 part 1) and the full init → dry-run
graph walk (Gate S3 part 2) against a sample scope file, in a subprocess
exactly as the operator would run it."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

SAMPLE_SCOPE = {
    "targets": [
        {"name": "*.acme-corp.com", "category": "URL", "in_scope": True},
        {"name": "api.acme-corp.com", "category": "URL", "in_scope": True},
        {"name": "legacy.acme-corp.com", "category": "URL", "in_scope": False},
    ]
}


def _run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), *args],
        capture_output=True, text=True, timeout=120,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture
def scope_file(tmp_path) -> Path:
    path = tmp_path / "scope.json"
    path.write_text(json.dumps(SAMPLE_SCOPE), encoding="utf-8")
    return path


@pytest.fixture
def workspace(tmp_path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


class TestHelp:
    def test_main_help(self):
        proc = _run_cli("--help")
        assert proc.returncode == 0
        assert "init" in proc.stdout
        assert "run" in proc.stdout
        assert "stop" in proc.stdout

    def test_run_help(self):
        proc = _run_cli("run", "--help")
        assert proc.returncode == 0
        assert "--dry-run" in proc.stdout
        assert "--program" in proc.stdout


class TestInit:
    def test_init_creates_workspace_and_profile(self, scope_file, workspace):
        proc = _run_cli(
            "init", "--platform", "hackerone", "--program", "acme-corp",
            "--scope-file", str(scope_file), "--researcher", "operator",
            "--workspace", str(workspace),
        )
        assert proc.returncode == 0, proc.stderr
        assert "in-scope     : 2 rule(s)" in proc.stdout
        assert "out-of-scope : 1 rule(s)" in proc.stdout

        prog_dir = workspace / "acme-corp"
        assert (prog_dir / "logs").is_dir()
        assert (prog_dir / "reports").is_dir()
        assert (prog_dir / "evidence").is_dir()

        profile = json.loads((prog_dir / "platform_profile.json").read_text())
        assert profile["platform"] == "hackerone"
        assert profile["program_handle"] == "acme-corp"
        assert profile["headers"]["X-BugBounty-HackerOne"] == "operator"

        headers = (prog_dir / "headers.txt").read_text()
        assert "X-BugBounty-HackerOne: operator" in headers

        scope = json.loads((prog_dir / "scope.json").read_text())
        assert scope["platform"] == "hackerone"  # operator's --platform wins
        assert len(scope["in_scope"]) == 2
        assert len(scope["out_of_scope"]) == 1
        out_patterns = [r["pattern"] for r in scope["out_of_scope"]]
        assert out_patterns == ["legacy.acme-corp.com"]

    def test_init_platform_override_beats_importer(self, scope_file, workspace):
        # The bugcrowd_json parser stamps platform=bugcrowd — the operator's
        # --platform must win (regression for the S3 init fix).
        proc = _run_cli(
            "init", "--platform", "intigriti", "--program", "acme-corp",
            "--scope-file", str(scope_file), "--workspace", str(workspace),
        )
        assert proc.returncode == 0, proc.stderr
        scope = json.loads(
            (workspace / "acme-corp" / "scope.json").read_text())
        assert scope["platform"] == "intigriti"

    def test_init_merges_roe_testing_requirements(self, workspace):
        # The UZ Leuven shape: the fetched scope file carries
        # _testing_requirements with requestHeader "X-Intigriti-Username:
        # {Username}". init must parse the "Name: value" form, substitute the
        # --researcher value for {Username}, keep the platform default
        # headers, and export the merged set to headers.txt — no manual edit.
        roe_scope = tmp_roe_scope(workspace.parent)
        proc = _run_cli(
            "init", "--platform", "intigriti", "--program", "acme-corp",
            "--scope-file", str(roe_scope), "--researcher", "onoffgrid",
            "--workspace", str(workspace),
        )
        assert proc.returncode == 0, proc.stderr
        assert "RoE header" in proc.stdout

        profile = json.loads(
            (workspace / "acme-corp" / "platform_profile.json").read_text())
        headers = profile["headers"]
        assert headers["X-Intigriti-Username"] == "onoffgrid"
        # Platform default attribution stays alongside the RoE header.
        assert headers["X-Intigriti-Researcher"] == "onoffgrid"

        flat = (workspace / "acme-corp" / "headers.txt").read_text()
        assert "X-Intigriti-Username: onoffgrid" in flat

    def test_init_merges_roe_user_agent_override(self, workspace):
        # A non-null RoE userAgent overrides the platform default UA.
        roe_scope = tmp_roe_scope(workspace.parent,
                                  user_agent="acme-bounty/1.0 (onoffgrid)")
        proc = _run_cli(
            "init", "--platform", "intigriti", "--program", "acme-corp",
            "--scope-file", str(roe_scope), "--researcher", "onoffgrid",
            "--workspace", str(workspace),
        )
        assert proc.returncode == 0, proc.stderr
        profile = json.loads(
            (workspace / "acme-corp" / "platform_profile.json").read_text())
        assert profile["headers"]["User-Agent"] == "acme-bounty/1.0 (onoffgrid)"


def tmp_roe_scope(base_dir, user_agent: str | None = None) -> Path:
    """A Bugcrowd-shaped scope file carrying _testing_requirements (the meta
    key scripts/fetch_intigriti_scope.py emits; absent for other platforms)."""
    path = Path(base_dir) / "roe_scope.json"
    path.write_text(json.dumps({
        "targets": [{"name": "a.acme-corp.com", "category": "URL",
                     "in_scope": True}],
        "_testing_requirements": {
            "requestHeader": "X-Intigriti-Username: {Username}",
            "userAgent": user_agent,
            "automatedTooling": 5,
            "intigritiMe": True,
            "safeHarbour": True,
        },
    }), encoding="utf-8")
    return path


class TestDryRunGate:
    """Gate S3: --dry-run on a sample scope walks config → gate → admiral →
    report → memory with mocked component calls."""

    def _init(self, scope_file, workspace):
        proc = _run_cli(
            "init", "--platform", "hackerone", "--program", "acme-corp",
            "--scope-file", str(scope_file), "--researcher", "operator",
            "--workspace", str(workspace),
        )
        assert proc.returncode == 0, proc.stderr

    def test_dry_run_walks_full_graph(self, scope_file, workspace):
        self._init(scope_file, workspace)
        proc = _run_cli("run", "--program", "acme-corp", "--dry-run",
                        "--workspace", str(workspace))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        out = proc.stdout
        for marker in (
            "scope gate  : sample endpoint ALLOWED",
            "scope gate  : unrelated host BLOCKED",
            "model route",
            "dispatch    : 1 finding(s) from mocked specialist",
            "triage      :",
            "noise filter: missing-header finding DROPPED",
            "report gate : pre-confirmation report correctly refused",
            "report      :",
            "mempalace   :",
            "full graph walked",
        ):
            assert marker in out, f"missing in dry-run output: {marker!r}\n{out}"

        status_line = [l for l in out.splitlines() if l.startswith("[dry-run] status")]
        status = json.loads(status_line[0].split("status      : ", 1)[1])
        assert status["hunt"] == "active"
        assert status["dry_run"] is True
        assert status["platform"] == "hackerone"
        assert status["findings"]["confirmed"] == 1
        assert status["reports_written"] == 1
        assert status["kill_switch"] is False

        # The confirmed report actually landed on disk, platform-tailored.
        reports = list((workspace / "acme-corp" / "reports").glob("*.md"))
        assert len(reports) == 1
        body = reports[0].read_text(encoding="utf-8")
        assert "**Platform:** hackerone" in body
        assert "CWE-89" in body

    def test_dry_run_requires_init(self, workspace):
        proc = _run_cli("run", "--program", "never-init-ed", "--dry-run",
                        "--workspace", str(workspace))
        assert proc.returncode != 0
        assert "init" in (proc.stderr + proc.stdout)

    def test_stop_prints_teardown_order(self):
        proc = _run_cli("stop")
        assert proc.returncode == 0
        assert "mitmdump" in proc.stdout
        assert "mempalace" in proc.stdout
