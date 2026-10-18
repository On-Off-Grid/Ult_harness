# tests/test_s8_hunt_launcher.py
"""S8.4 — `main.py hunt` / `resume` launcher: offline, no network, no real
components.

Covers:
* tool registry (keys, resolve, env builder, honest disabled/skip)
* target derivation (exact / url / wildcard split + cap)
* preflight hard-fail paths (no mitmdump, control plane already up)
* tool spawning (env injection, per-target fan-out, stdin feed, fail-open on
  a tool that crashes immediately)
* pause/resume state (write/read round-trip, durable snapshot, resume cmd)
* ordered tool teardown (kill_tools reaps the process group)
* dry-run $0 gate parsing (subprocess mocked — no real main.py spawn)

Everything is driven with stub executables / monkeypatched seams so the suite
stays offline and fast.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import tools.registry as reg
from core.types import (
    Platform,
    ScopeMatchType,
    ScopeRule,
    TargetScope,
)
import orchestrator.hunt_launcher as hl


# ── helpers ───────────────────────────────────────────────────────────────

def _scope(*rules) -> TargetScope:
    return TargetScope(
        program_handle="acme",
        platform=Platform.BUGCROWD,
        in_scope=list(rules),
        out_of_scope=[],
        rate_limit_rps=10.0,
        max_concurrent=5,
    )


def _stub_tool(tmp_path: Path, behavior: str = "sleep") -> str:
    """Write a tiny shell 'component' (UNIQUE name per behavior — six stubs
    sharing one filename would overwrite each other) and return its path.
    `behavior`:
      sleep   — sleep for a couple seconds (alive)
      crash   — exit 1 immediately
      envdump — write the HARNESS_* / proxy env it was launched with, then exit 0
      stdin   — echo what it read on stdin to a file, then exit 0
    """
    script = tmp_path / f"stub_{behavior}.sh"
    if behavior == "envdump":
        script.write_text(
            "#!/bin/sh\n"
            "echo \"HARNESS_API_URL=$HARNESS_API_URL\" > \"${STUB_ENV_OUT}\"\n"
            "echo \"HTTPS_PROXY=$HTTPS_PROXY\" >> \"${STUB_ENV_OUT}\"\n"
            "echo \"NO_PROXY=$NO_PROXY\" >> \"${STUB_ENV_OUT}\"\n"
            "exit 0\n",
            encoding="utf-8",
        )
    elif behavior == "stdin":
        script.write_text(
            "#!/bin/sh\n"
            "cat > \"${STUB_STDIN_OUT}\"\n"
            "exit 0\n",
            encoding="utf-8",
        )
    elif behavior == "crash":
        script.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    else:  # sleep
        script.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def _make_spec(key: str, script: str, *, per_target: bool = False,
               enabled: bool = True, stdin_kind: str = "none") -> reg.ToolSpec:
    return reg.ToolSpec(
        key=key, label=f"stub {key}", kind="aux",
        cmd=[script] if not per_target else [script, "--target", "{target}"],
        enabled=enabled, per_target=per_target,
        needs=[], build=None, cwd="", stdin_kind=stdin_kind,
    )


@pytest.fixture
def registry(tmp_path: Path, monkeypatch):
    """Point reg.TOOLS at stub tools so spawn_tools never touches a real
    component. Restore the real registry afterwards."""
    real = reg.TOOLS
    stubs = {
        "sleep": _make_spec("sleep", _stub_tool(tmp_path, "sleep")),
        "crash": _make_spec("crash", _stub_tool(tmp_path, "crash")),
        "envdump": _make_spec("envdump", _stub_tool(tmp_path, "envdump")),
        "stdin": _make_spec("stdin", _stub_tool(tmp_path, "stdin"),
                            stdin_kind="scope_urls"),
        "per": _make_spec("per", _stub_tool(tmp_path, "sleep"), per_target=True),
        "off": _make_spec("off", _stub_tool(tmp_path, "sleep"), enabled=False),
    }
    monkeypatch.setattr(reg, "TOOLS", stubs)
    return stubs


# ── registry ──────────────────────────────────────────────────────────────

def test_registry_keys_resolve_and_dedup():
    assert set(reg.resolve_keys("jsleak,cbb,jsleak")) == {"jsleak", "cbb"}
    assert reg.resolve_keys(None) == []
    assert reg.resolve_keys("") == []


def test_registry_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown tool"):
        reg.resolve_keys("jsleak,nope")


def test_build_env_injects_harness_and_proxy():
    env = reg.build_env(api_url="http://127.0.0.1:8001",
                        egress_proxy="http://127.0.0.1:8080")
    assert env["HARNESS_API_URL"] == "http://127.0.0.1:8001"
    assert env["HARNESS_EGRESS_PROXY"] == "http://127.0.0.1:8080"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:8080"
    assert "127.0.0.1" in env["NO_PROXY"]


# ── target derivation ─────────────────────────────────────────────────────

def test_derive_targets_splits_exact_url_wildcard_and_caps():
    scope = _scope(
        ScopeRule("a.acme.com", ScopeMatchType.EXACT, ""),
        ScopeRule("https://b.acme.com/x", ScopeMatchType.EXACT, ""),
        ScopeRule("*.acme.com", ScopeMatchType.WILDCARD, ""),
    )
    per, urls, wild = hl.derive_targets(scope, max_targets=1)
    assert per == ["a.acme.com"]                      # exact, capped at 1
    assert "https://b.acme.com/x" in urls             # url kept
    assert "*.acme.com" in wild                       # wildcard not expanded
    assert "a.acme.com" in urls                       # exact also fed to stdin tools


# ── preflight ─────────────────────────────────────────────────────────────

def test_preflight_fails_without_mitmdump(monkeypatch, tmp_path):
    monkeypatch.setattr(hl.shutil, "which", lambda b: None if b == "mitmdump" else "/usr/bin/true")
    monkeypatch.setattr(hl, "_control_plane_up", lambda: False)
    monkeypatch.setattr(hl, "_ollama_up", lambda: True)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    errs = hl.preflight(platform="bugcrowd", program="acme",
                        workspace=str(tmp_path), scope_file=None)
    assert any("mitmdump" in e for e in errs)


def test_preflight_fails_when_control_plane_already_up(monkeypatch, tmp_path):
    monkeypatch.setattr(hl.shutil, "which", lambda b: "/usr/bin/true")
    monkeypatch.setattr(hl, "_control_plane_up", lambda: True)
    monkeypatch.setattr(hl, "_ollama_up", lambda: True)
    errs = hl.preflight(platform="bugcrowd", program="acme",
                        workspace=str(tmp_path), scope_file=None)
    assert any(":8001" in e for e in errs)


def test_preflight_fails_on_missing_scope_file(monkeypatch, tmp_path):
    monkeypatch.setattr(hl.shutil, "which", lambda b: "/usr/bin/true")
    monkeypatch.setattr(hl, "_control_plane_up", lambda: False)
    monkeypatch.setattr(hl, "_ollama_up", lambda: True)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    errs = hl.preflight(platform="bugcrowd", program="acme",
                        workspace=str(tmp_path), scope_file=str(tmp_path / "nope.json"))
    assert any("does not exist" in e for e in errs)


def test_preflight_ok_when_all_present(monkeypatch, tmp_path):
    monkeypatch.setattr(hl.shutil, "which", lambda b: "/usr/bin/true")
    monkeypatch.setattr(hl, "_control_plane_up", lambda: False)
    monkeypatch.setattr(hl, "_ollama_up", lambda: True)
    errs = hl.preflight(platform="bugcrowd", program="acme",
                        workspace=str(tmp_path), scope_file=None)
    assert errs == []


# ── tool spawning ─────────────────────────────────────────────────────────

def test_spawn_injects_env_and_feeds_stdin(tmp_path, monkeypatch, registry):
    env_out = tmp_path / "env.txt"
    monkeypatch.setenv("STUB_ENV_OUT", str(env_out))
    procs, notes = hl.spawn_tools(
        keys=["envdump"], per_target=["a.acme.com"],
        scope_urls=["https://a.acme.com/", "https://b.acme.com/"],
        api_url="http://127.0.0.1:8001", egress_proxy="http://127.0.0.1:8080",
        scope=_scope(ScopeRule("a.acme.com", ScopeMatchType.EXACT, "")))
    # envdump is not per_target and stdin_kind=none -> single process, no stdin
    assert len(procs) == 1
    procs[0].proc.wait(timeout=10)
    lines = env_out.read_text(encoding="utf-8").splitlines()
    assert "HARNESS_API_URL=http://127.0.0.1:8001" in lines
    assert "HTTPS_PROXY=http://127.0.0.1:8080" in lines
    hl.kill_tools(procs)


def test_spawn_feeds_scope_urls_on_stdin(tmp_path, monkeypatch, registry):
    out = tmp_path / "stdin.txt"
    monkeypatch.setenv("STUB_STDIN_OUT", str(out))
    procs, notes = hl.spawn_tools(
        keys=["stdin"], per_target=[],
        scope_urls=["https://a.acme.com/", "https://b.acme.com/"],
        api_url="http://127.0.0.1:8001", egress_proxy="http://127.0.0.1:8080",
        scope=_scope())
    assert len(procs) == 1
    procs[0].proc.wait(timeout=10)
    got = out.read_text(encoding="utf-8").split()
    assert got == ["https://a.acme.com/", "https://b.acme.com/"]
    hl.kill_tools(procs)


def test_spawn_fans_out_per_target(tmp_path, registry):
    procs, notes = hl.spawn_tools(
        keys=["per"], per_target=["a.acme.com", "b.acme.com"],
        scope_urls=[], api_url="http://127.0.0.1:8001",
        egress_proxy="http://127.0.0.1:8080", scope=_scope())
    assert len(procs) == 2, "per_target tool must get one process per host"
    hl.kill_tools(procs)


def test_spawn_skips_disabled_tool(tmp_path, registry):
    procs, notes = hl.spawn_tools(
        keys=["off"], per_target=["a.acme.com"], scope_urls=[],
        api_url="a", egress_proxy="b", scope=_scope())
    assert procs == []
    assert any("disabled" in n for n in notes)


def test_spawn_never_raises_when_tool_crashes(tmp_path, registry):
    # A crashing tool is a skip/noise note at the supervisor level, but
    # spawn itself must not raise just because the binary exits non-zero.
    procs, notes = hl.spawn_tools(
        keys=["crash"], per_target=["a.acme.com"], scope_urls=[],
        api_url="a", egress_proxy="b", scope=_scope())
    assert len(procs) == 1
    code = procs[0].proc.wait(timeout=10)
    assert code != 0
    hl.kill_tools(procs)


def test_kill_tools_reaps_process_group(tmp_path, registry):
    procs, _ = hl.spawn_tools(
        keys=["sleep"], per_target=["a.acme.com"], scope_urls=[],
        api_url="a", egress_proxy="b", scope=_scope())
    assert len(procs) == 1
    assert procs[0].proc.poll() is None      # alive
    hl.kill_tools(procs)
    assert procs[0].proc.poll() is not None  # reaped
    # the sleep's process group is gone too
    try:
        os.killpg(os.getpgid(procs[0].proc.pid), 0)
        alive = True
    except (ProcessLookupError, PermissionError):
        alive = False
    assert not alive


# ── pause / resume state ──────────────────────────────────────────────────

def test_state_roundtrip_and_resume_cmd(tmp_path):
    ws = str(tmp_path / "workspace")
    sp = hl.write_state(program="acme", platform="bugcrowd", workspace=ws,
                        scope_file=str(tmp_path / "s.json"),
                        tools=["jsleak", "cbb"], per_target=["a.acme.com"],
                        phases=["preflight", "scope", "init", "dry_run", "booted"],
                        durable={"reports": ["r.md"], "evidence": [],
                                 "egress_log_lines": 3,
                                 "scope_rules_in": 2, "scope_rules_out": 0},
                        status="paused", run_pid=12345)
    assert sp.exists()
    st = hl.read_state(ws, "acme")
    assert st["program"] == "acme"
    assert st["status"] == "paused"
    assert st["tools"] == ["jsleak", "cbb"]
    assert st["targets"] == ["a.acme.com"]
    assert "main.py resume --program acme" in st["resume_cmd"]
    assert st["durable"]["egress_log_lines"] == 3


def test_read_state_missing_returns_none(tmp_path):
    assert hl.read_state(str(tmp_path / "nope"), "acme") is None


def test_snapshot_durable_counts_disk_files(tmp_path):
    ws = tmp_path / "workspace" / "acme"
    (ws / "reports").mkdir(parents=True)
    (ws / "evidence").mkdir(parents=True)
    (ws / "logs").mkdir(parents=True)
    (ws / "reports" / "a.md").write_text("r", encoding="utf-8")
    (ws / "reports" / "b.md").write_text("r", encoding="utf-8")
    (ws / "evidence" / "e.txt").write_text("e", encoding="utf-8")
    (ws / "logs" / "egress_proxy.jsonl").write_text(
        '{"a":1}\n{"b":2}\n{"c":3}\n', encoding="utf-8")
    (ws / "scope.json").write_text(
        json.dumps({"in_scope": [1, 2, 3], "out_of_scope": [1]}),
        encoding="utf-8")
    d = hl.snapshot_durable(str(tmp_path / "workspace"), "acme")
    assert d["reports"] == ["a.md", "b.md"]
    assert d["evidence"] == ["e.txt"]
    assert d["egress_log_lines"] == 3
    assert d["scope_rules_in"] == 3
    assert d["scope_rules_out"] == 1


# ── dry-run $0 gate (subprocess mocked — no real main.py spawn) ───────────

class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str, stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_dry_run_gate_accepts_zero_budget(monkeypatch):
    status_line = ('[dry-run] status      : {"program": "acme", '
                   '"budget": {"total_cost_usd": 0}}')
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        return _FakeCompleted(0, "[dry-run] ✅ full graph walked\n" + status_line)

    monkeypatch.setattr(hl.subprocess, "run", fake_run)
    ok, msg = hl.dry_run_check(program="acme", workspace="./workspace")
    assert ok, msg
    assert "dry-run" in " ".join(calls["cmd"])
    assert "--dry-run" in calls["cmd"]


def test_dry_run_gate_rejects_nonzero_budget(monkeypatch):
    status_line = ('[dry-run] status      : {"program": "acme", '
                   '"budget": {"total_cost_usd": 1.5}}')
    monkeypatch.setattr(hl.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(0, status_line))
    ok, msg = hl.dry_run_check(program="acme", workspace="./workspace")
    assert not ok
    assert "$1.5" in msg


def test_dry_run_gate_rejects_nonzero_exit(monkeypatch):
    monkeypatch.setattr(hl.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(2, "boom", "traceback"))
    ok, msg = hl.dry_run_check(program="acme", workspace="./workspace")
    assert not ok
    assert "dry-run failed" in msg


# ── pid / control-plane liveness helpers ──────────────────────────────────

def test_pid_alive_false_for_none_and_invalid():
    assert hl._pid_alive(None) is False
    assert hl._pid_alive(0) is False
    # a large pid that is certainly not running
    assert hl._pid_alive(2**31 - 1) is False
    # current process is alive
    assert hl._pid_alive(os.getpid()) is True
