# tests/test_s2_ingest.py  — S2.9: scripts/ingest_*.py
"""Dry-run of the two MemPalace ingest scripts against a small sample corpus.

VERIFIED S2.9 FIX: both scripts used to import `mempalace` (and therefore
`chromadb`) at module top-level, so even `--dry-run` crashed on any machine
without the mempalace checkout / chromadb. The imports are now deferred into
the non-dry-run paths; these tests lock that behavior in.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SCRIPTS = {
    "awesome_redteam": REPO / "scripts" / "ingest_awesome_redteam.py",
    "cl4r1tas": REPO / "scripts" / "ingest_cl4r1tas.py",
}


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=120,
        cwd=str(REPO),
    )


def test_scripts_are_syntax_valid():
    for name, script in SCRIPTS.items():
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", str(script)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"{name} fails to compile: {proc.stderr}"


@pytest.mark.parametrize("name", list(SCRIPTS))
def test_dry_run_works_without_chromadb_or_mempalace_on_path(tmp_path, name):
    """`--dry-run` must succeed with NO mempalace importable and NO chromadb.

    This is the regression test for the S2.9 finding: the dry-run path must be
    dependency-free (pure file scan + reporting).
    """
    # Build a minimal corpus the script can find.
    corpus = tmp_path / "corpus"
    if name == "awesome_redteam":
        (corpus / "cheatsheets" / "sql").mkdir(parents=True)
        (corpus / "cheatsheets" / "sql" / "union.md").write_text("# UNION SQLi\n")
        (corpus / "tips" / "web").mkdir(parents=True)
        (corpus / "tips" / "web" / "xss.md").write_text("# DOM XSS\n")
    else:
        (corpus / "ANTHROPIC").mkdir(parents=True)
        (corpus / "ANTHROPIC" / "system_prompt.md").write_text("# system prompt\n")
        # A non-prompt file must NOT be picked up by find_prompt_files.
        (corpus / "README.md").write_text("# readme (not a prompt)\n")

    proc = _run(SCRIPTS[name], "--dry-run", "--root", str(corpus))
    assert proc.returncode == 0, f"exit={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    assert "[DRY-RUN]" in proc.stdout
    if name == "awesome_redteam":
        assert "Found 2 Markdown files" in proc.stdout
        assert "ar:awesome_redteam:sql:union" in proc.stdout
        assert "ar:awesome_redteam:web:xss" in proc.stdout
    else:
        assert "Found 1 CL4R1T4S prompt files" in proc.stdout
        assert "cl4r1tas:cl4r1tas:ANTHROPIC:system_prompt" in proc.stdout
        assert "README" not in proc.stdout


@pytest.mark.parametrize("name", list(SCRIPTS))
def test_dry_run_missing_root_reports_zero_files(tmp_path, name):
    """A nonexistent corpus must yield a clean 'Found 0' run, not a traceback."""
    proc = _run(SCRIPTS[name], "--dry-run", "--root", str(tmp_path / "does-not-exist"))
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    assert "Found 0" in proc.stdout


@pytest.mark.parametrize("name", list(SCRIPTS))
def test_top_level_imports_are_deferred(name):
    """Lock-in: the module top-level must not import mempalace/chromadb
    (that's what made --dry-run impossible without a full mempalace install)."""
    src = SCRIPTS[name].read_text(encoding="utf-8")
    top = src.split("def ")[0]  # everything before the first top-level function
    assert "from mempalace" not in top, f"{name}: mempalace imported at top level"
    assert "import chromadb" not in top, f"{name}: chromadb imported at top level"
