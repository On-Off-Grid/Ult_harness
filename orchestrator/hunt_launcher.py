# orchestrator/hunt_launcher.py
"""`main.py hunt` — the one-command hunt supervisor (S8.4).

Automates the worked example's Steps 0–5 in a single foreground process:

    preflight → scope (Intigriti auto-fetch) → init → dry-run ($0 gate)
              → boot control plane (child `main.py run`) → launch tools
              → supervise until Ctrl-C (or the control plane dying)

Pause / resume
--------------
A live hunt's *state* splits in two (verified against the code — there is no
other persistence):

* **Durable (survives any stop):** `workspace/<p>/reports/`, `evidence/`,
  `logs/egress_proxy.jsonl`, `scope.json`, `platform_profile.json`.
* **Volatile (in the `run` process memory only):** the admiral's
  task/finding maps, triage state, the token/budget ledger, the Interactsh
  session, and any launched tool processes.

So a pause is **not** a suspended animation — it is an honest, ordered
teardown plus a durable snapshot (`workspace/<p>/hunt_state.json`) recording
what survived and what was dropped. `main.py resume` rebuilds the volatile
half: re-preflight → (re-)scope → re-init (idempotent) → re-dry-run ($0
gate) → reboot the control plane → relaunch the same tools/targets.

The state file is written **early** (right after boot, `status="running"`,
with the control-plane pid) and rewritten on every exit — so even a hard
logout (SIGKILL, no cleanup) leaves a resumable marker, and `resume` refuses
to double-boot if the old control plane survived and still holds `:8001`/`:8080`.

Invariants preserved:
* The control plane still never scans — the launcher only *starts* external
  tools; the egress gate (`:8080`) remains the only path to the target.
* Fail-open: a tool crashing never kills the hunt (it is logged; the rest
  continue).
* Dry-run must end at $0 before anything goes live (S4.3 invariant).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import main
from core.types import ScopeMatchType, TargetScope
from tools import registry as reg

PROJECT_ROOT = main.PROJECT_ROOT
STATE_FILE_NAME = "hunt_state.json"
STATE_VERSION = 1
API_URL = "http://127.0.0.1:8001"
EGRESS_PROXY_URL = "http://127.0.0.1:8080"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pick_python() -> str:
    venv_py = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(venv_py) if venv_py.exists() else "python3"


def _resume_cmd(program: str, workspace: str) -> str:
    return f"{_pick_python()} main.py resume --program {program} --workspace {Path(workspace).resolve()}"


# ═══════════════════════════════════════════════════════════════════════════
# preflight
# ═══════════════════════════════════════════════════════════════════════════

def _ollama_up(timeout: float = 1.5) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",
                                     timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _control_plane_up(timeout: float = 1.5) -> bool:
    """Is something already serving the harness API on :8001? (i.e. a
    previous `run` survived a logout / was never torn down.)"""
    import urllib.request
    try:
        with urllib.request.urlopen(API_URL + "/api/v1/status",
                                     timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def preflight(*, platform: str, program: str, workspace: str,
              scope_file: Optional[str]) -> List[str]:
    """Fast, local checks. Returns a list of hard-error strings (empty = ok)."""
    errors: List[str] = []
    if not shutil.which("mitmdump"):
        errors.append(
            "mitmdump not found on PATH — egress would be UNGUARDED. "
            "Install mitmproxy in the venv and retry."
        )
    if _control_plane_up():
        errors.append(
            "a control plane is already serving :8001 (a previous run/hunt "
            "is still up). Tear it down first — see `main.py stop` — or "
            "resume it instead of booting a second instance."
        )
    ws = Path(workspace)
    try:
        probe = ws / ".hunt_write_probe"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        errors.append(f"workspace '{workspace}' is not writable ({exc.__class__.__name__})")
    if scope_file and not Path(scope_file).exists():
        errors.append(f"scope file '{scope_file}' does not exist")
    # At least one LLM backend must be configured. Ollama-only runs are legal
    # (S4.3 rehearsal), so this only fails when NOTHING is available.
    if not (os.getenv("GROQ_API_KEY") or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("LOCAL_HEAVY_URL") or _ollama_up()):
        errors.append(
            "no LLM backend configured (no GROQ_API_KEY / OPENROUTER_API_KEY in "
            ".env, no Ollama on :11434, LOCAL_HEAVY_URL empty) — the live run "
            "would have no route to a model."
        )
    return errors


# ═══════════════════════════════════════════════════════════════════════════
# scope (Intigriti auto-fetch)
# ═══════════════════════════════════════════════════════════════════════════

def _load_fetch_module():
    """Import scripts/fetch_intigriti_scope.py by path (it is not a package)."""
    import importlib.util
    path = PROJECT_ROOT / "scripts" / "fetch_intigriti_scope.py"
    spec = importlib.util.spec_from_file_location("fetch_intigriti_scope", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cached_scope_fresh(path: Path, marker: str) -> bool:
    """Is a cached Intigriti fetch current (payload schema of the running
    fetch script, so RoE metadata such as attribution headers is present)?

    Only files GENERATED by the fetch script are ever refreshed; a
    hand-written scope file (no generator marker) is operator-owned and is
    always treated as fresh — the launcher never clobbers an operator file.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        first = str((data.get("_comment") or [""])[0])
    except Exception:
        return False  # unreadable/corrupt cache → re-fetch
    if "Generated by scripts/fetch_intigriti_scope.py" not in first:
        return True  # not ours — operator-owned file
    return first.startswith(marker)


def ensure_scope(*, platform: str, program: str,
                 scope_file: Optional[str]) -> tuple:
    """Return (scope_file_abs, error). For Intigriti, fetches when the cache
    is missing or stale (older fetch-script schema — e.g. predating the RoE
    testing-requirements metadata that feeds the platform headers).

    The control plane itself never calls platform APIs — this is the
    operator's sanctioned fetch (same code path as the standalone script,
    key from the same .env entry).
    """
    if scope_file:
        if not Path(scope_file).exists():
            return "", f"scope file '{scope_file}' does not exist"
        return str(Path(scope_file).resolve()), None
    if platform == "intigriti":
        mod = _load_fetch_module()
        out = PROJECT_ROOT / "scope_files" / f"{program}.json"
        if out.exists():
            if _cached_scope_fresh(out, mod.GEN_MARKER):
                return str(out), None
            print(f"[hunt] scope       : cached {out.name} predates the current "
                  f"fetch schema (no RoE metadata) — re-fetching")
        try:
            key = mod._load_key()
            data = mod.fetch_program(key, program)
            payload = mod.build_scope_payload(data, program)
        except SystemExit as exc:  # the script exits with a human message
            return "", str(exc)
        except Exception as exc:
            return "", (f"Intigriti scope fetch failed ({exc.__class__.__name__}: {exc}) "
                        "— or copy the scope by hand (docs §2a manual path) "
                        "and pass --scope-file")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        n_in = sum(1 for t in payload["targets"] if t["in_scope"])
        print(f"[hunt] scope       : fetched {program} from Intigriti → {out} "
              f"({n_in} in-scope rule(s))")
        return str(out), None
    return "", ("no scope file — pass --scope-file (Bugcrowd-shaped JSON) for "
                "non-Intigriti platforms")


def roe_advisory(scope_file: Optional[str], tool_keys: List[str]) -> List[str]:
    """The boot-time RoE advisory lines for a scope file (may be empty).

    The structured testing-requirements the scope file carries (Intigriti
    fetches emit ``_testing_requirements``; every other platform / hand-
    written file simply has no key → no advisory, generic by construction).
    The structured fields are APPLIED by ``init`` (attribution header / UA
    into the profile); the RoE free TEXT is not machine-readable, so when
    the two clearly disagree — ``automatedTooling`` at/below 1 while tools
    are about to launch — the operator gets one loud warning at boot rather
    than a silent conflict. The 0–5 scale's exact semantics are not
    documented by the platform, so the level is REPORTED, never acted on.
    """
    if not scope_file:
        return []
    try:
        meta = json.loads(Path(scope_file).read_text(encoding="utf-8"))
        meta = meta.get("_testing_requirements") if isinstance(meta, dict) else None
    except Exception:
        return []
    if not isinstance(meta, dict) or not meta:
        return []
    at = meta.get("automatedTooling")
    notes = [
        f"attribution header {meta['requestHeader']!r} "
        f"(→ workspace headers via init)" if meta.get("requestHeader") else "",
        f"UA override {meta['userAgent']!r}" if meta.get("userAgent") else "",
        f"automatedTooling: {at}" if at is not None else "",
        "safe-harbour: yes" if meta.get("safeHarbour") else "",
    ]
    notes = [n for n in notes if n]
    lines = [f"[hunt] RoE         : " + "; ".join(notes)] if notes else []
    if isinstance(at, (int, float)) and at <= 1 and tool_keys:
        lines.append(
            "[hunt] ⚠ RoE       : automatedTooling "
            f"{at} suggests automated tooling is heavily restricted or "
            "banned — this hunt still launched its tools. Read the RoE "
            "before submitting anything; pass --tools none (or jsleak "
            "only) if the program forbids scanners."
        )
    return lines


# ═══════════════════════════════════════════════════════════════════════════
# init / dry-run
# ═══════════════════════════════════════════════════════════════════════════

def do_init(*, platform: str, program: str, scope_file: str,
            fmt: Optional[str], workspace: str, researcher: str) -> int:
    """Reuse main.cmd_init in-process (the same code the `init` command runs)."""
    ns = argparse.Namespace(
        platform=platform, program=program, scope_file=scope_file,
        format=fmt, researcher=researcher, workspace=workspace,
    )
    try:
        return main.cmd_init(ns)
    except SystemExit as exc:  # cmd_init raises SystemExit for human errors
        print(str(exc) if exc.code else f"[hunt] ✗ init failed: {exc}")
        return 1


def dry_run_check(*, program: str, workspace: str,
                  timeout: int = 180) -> tuple:
    """Spawn `main.py run --dry-run` in a child (offline, $0). Returns
    (ok, message). Non-zero budget or non-zero exit ⇒ hunt setup failed."""
    cmd = [sys.executable, str(PROJECT_ROOT / "main.py"), "run",
           "--program", program, "--dry-run", "--workspace", workspace]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(PROJECT_ROOT))
    except subprocess.TimeoutExpired:
        return False, "dry-run timed out"
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-5:]
        return False, "dry-run failed:\n" + "\n".join(tail)
    # The walk ends with: [dry-run] status : {… "budget": {"total_cost_usd": X …}}
    budget = None
    for line in reversed(r.stdout.splitlines()):
        if '"total_cost_usd"' in line:
            try:
                payload = json.loads(line.split(":", 1)[1].strip())
                budget = payload.get("budget", {}).get("total_cost_usd")
            except Exception:
                budget = None
            break
    if budget is None:
        return False, "dry-run finished but no budget line was found in its output"
    if budget != 0:
        return False, f"dry-run budget is ${budget} — must be $0 (cheatsheet §4)"
    return True, f"dry-run walked clean, budget ${budget}"


# ═══════════════════════════════════════════════════════════════════════════
# target derivation
# ═══════════════════════════════════════════════════════════════════════════

def derive_targets(scope: TargetScope, max_targets: int) -> tuple:
    """Split in-scope rules into:
    * per-target hosts (exact patterns, capped at max_targets) for
      per_target tools (e.g. one cbb agent each);
    * the full URL list fed to stdin-style tools (jsleak);
    * wildcards — NOT expanded (there is no subdomain enumeration in this
      repo; an honest note is printed instead).

    CIDR/IP rules are excluded: the egress gate enforces them, but they are
    not launchable hosts (talk to them manually with a Host header). A
    pattern carrying a path (`host/path/`) contributes its host only."""
    exact, urls, wildcards = [], [], []
    for r in scope.in_scope:
        p = r.pattern
        if r.match_type == ScopeMatchType.CIDR:
            continue  # gate-enforced, not a target host
        if r.match_type == ScopeMatchType.WILDCARD or p.startswith("*."):
            wildcards.append(p)
        elif "://" in p:
            urls.append(p)
        elif "/" in p:
            host = p.split("/", 1)[0].rstrip("/")
            if host and host not in exact:
                exact.append(host)
        else:
            if p not in exact:
                exact.append(p)
    return exact[:max_targets], urls + exact, wildcards


# ═══════════════════════════════════════════════════════════════════════════
# tool spawning
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ToolProc:
    key: str
    label: str
    target: str
    proc: subprocess.Popen
    stdin_data: Optional[str] = None


def spawn_tools(*, keys: List[str], per_target: List[str], scope_urls: List[str],
                api_url: str, egress_proxy: str,
                scope: TargetScope) -> tuple:
    """Launch the selected tools. Returns (procs, skip_notes). Never raises
    for a per-tool problem — a bad tool is a skip note, not a hunt abort."""
    procs: list = []
    notes: list = []
    for key in keys:
        spec = reg.TOOLS[key]
        if not spec.enabled:
            notes.append(f"{key}: disabled ({spec.note})")
            continue
        missing = [label for label, check in spec.needs if check()]
        if missing and spec.build is not None:
            # e.g. jsleak's one-time `go build`
            try:
                spec.build()
                missing = [label for label, check in spec.needs if check()]
            except Exception as exc:
                notes.append(f"{key}: build failed ({exc.__class__.__name__}: {exc})")
                continue
        if missing:
            notes.append(f"{key}: skipped — {'; '.join(missing)}")
            continue
        env = reg.build_env(api_url=api_url, egress_proxy=egress_proxy)
        cwd = spec.cwd or str(PROJECT_ROOT)
        targets = per_target if spec.per_target else ["<all>"]
        for t in targets:
            cmd = [part.format(target=t, python=_pick_python()) for part in spec.cmd]
            stdin_data = None
            if spec.stdin_kind == "scope_urls" and not spec.per_target:
                stdin_data = "\n".join(scope_urls) + "\n"
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=env, start_new_session=True,
                stdin=subprocess.PIPE if stdin_data else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if stdin_data:
                proc.stdin.write(stdin_data.encode("utf-8"))
                proc.stdin.close()
            procs.append(ToolProc(key=key, label=spec.label, target=t,
                                  proc=proc, stdin_data=stdin_data))
            print(f"[hunt] tool        : {key} started (pid {proc.pid}) target={t}")
    return procs, notes


def kill_tools(procs: list) -> None:
    """Ordered tool teardown: SIGTERM the process group, wait, SIGKILL."""
    for tp in procs:
        if tp.proc.poll() is not None:
            continue
        try:
            os.killpg(os.getpgid(tp.proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.time() + 3
    for tp in procs:
        try:
            tp.proc.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(tp.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


# ═══════════════════════════════════════════════════════════════════════════
# pause / resume state
# ═══════════════════════════════════════════════════════════════════════════

def snapshot_durable(workspace: str, program: str) -> dict:
    """What actually survives on disk (the honest part of the snapshot)."""
    ws = Path(workspace) / program

    def _names(d: Path) -> list:
        return sorted(p.name for p in d.iterdir() if p.is_file()) if d.is_dir() else []

    egress = ws / "logs" / "egress_proxy.jsonl"
    egress_lines = 0
    if egress.exists():
        with egress.open(encoding="utf-8", errors="replace") as fh:
            egress_lines = sum(1 for _ in fh)
    return {
        "reports": _names(ws / "reports"),
        "evidence": _names(ws / "evidence"),
        "egress_log_lines": egress_lines,
        "scope_rules_in": _count_scope(ws, "in_scope"),
        "scope_rules_out": _count_scope(ws, "out_of_scope"),
    }


def _count_scope(ws: Path, key: str) -> int:
    sj = ws / "scope.json"
    if not sj.exists():
        return 0
    try:
        return len(json.loads(sj.read_text(encoding="utf-8")).get(key, []))
    except Exception:
        return 0


def write_state(*, program: str, platform: str, workspace: str,
                scope_file: Optional[str], tools: List[str],
                per_target: List[str], phases: list, durable: dict,
                status: str, run_pid: Optional[int] = None) -> Path:
    """Write workspace/<p>/hunt_state.json — the pause/resume marker.

    Written early (status="running", right after boot) AND on every exit, so
    even a hard logout (SIGKILL) leaves a resumable state behind.
    """
    ws = Path(workspace) / program
    ws.mkdir(parents=True, exist_ok=True)
    state_path = ws / STATE_FILE_NAME
    state = {
        "version": STATE_VERSION,
        "program": program,
        "platform": platform,
        "workspace": str(Path(workspace).resolve()),
        "scope_file": str(Path(scope_file).resolve()) if scope_file else None,
        "tools": tools,
        "targets": per_target,
        "status": status,                       # running | paused | ended | failed
        "phases_completed": phases,
        "run_pid": run_pid,
        "updated_at": _now(),
        "durable": durable,
        "volatilized_on_stop": [
            "admiral tasks & triage state (in memory only)",
            "token/budget ledger (in memory only)",
            "Interactsh OOB session (deregistered — in-flight blind "
            "callbacks no longer correlate)",
            "launched tool processes",
        ],
        "resume_cmd": _resume_cmd(program, workspace),
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state_path


def read_state(workspace: str, program: str) -> Optional[dict]:
    p = Path(workspace) / program / STATE_FILE_NAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, TypeError, ValueError):
        return False
    except PermissionError:
        return True  # exists, but not ours


# ═══════════════════════════════════════════════════════════════════════════
# the supervisor
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class _Shutdown:
    requested: bool = False


def _boot(args, *, state: Optional[dict] = None) -> int:
    """Shared boot path for `hunt` and `resume`:
    preflight → scope → init → dry-run → run child → tools → supervise."""
    program: str = args.program
    workspace: str = getattr(args, "workspace", "./workspace")
    platform: str = (state.get("platform") if state else args.platform)
    scope_file: Optional[str] = (state.get("scope_file") if state
                                 else getattr(args, "scope_file", None))

    # tool selection: CLI wins, else saved state, else none
    cli_tools = getattr(args, "tools", None)
    tools_key: str = cli_tools if cli_tools else (
        ",".join(state.get("tools", [])) if state else "")

    # per-target hosts: CLI wins, else saved state, else derive from scope
    cli_targets = getattr(args, "targets", None)
    if cli_targets:
        per_target: Optional[List[str]] = [t for t in cli_targets.split(",") if t]
    elif state:
        saved = state.get("targets") or []
        per_target = [t for t in saved if t] or None
    else:
        per_target = None

    phases: list = []

    # 1. preflight ────────────────────────────────────────────────────────
    print(f"[hunt] preflight   : program={program} platform={platform} "
          f"workspace={workspace}")
    errors = preflight(platform=platform, program=program,
                       workspace=workspace, scope_file=scope_file)
    if errors:
        for e in errors:
            print(f"[hunt] ✗ {e}")
        return 1
    phases.append("preflight")

    # 2. scope ────────────────────────────────────────────────────────────
    scope_file, err = ensure_scope(platform=platform, program=program,
                                   scope_file=scope_file)
    if err:
        print(f"[hunt] ✗ {err}")
        return 1
    phases.append("scope")

    # 3. init (idempotent — resume re-runs it to refresh profile/headers) ─
    rc = do_init(platform=platform, program=program, scope_file=scope_file,
                 fmt=getattr(args, "format", None), workspace=workspace,
                 researcher=getattr(args, "researcher", "onoffgrid"))
    if rc != 0:
        return rc
    phases.append("init")

    scope = main._load_workspace_scope(workspace, program)

    # 4. dry-run rehearsal ($0 gate) ──────────────────────────────────────
    skip_dry = getattr(args, "skip_dry_run", False)
    if skip_dry:
        print("[hunt] dry-run     : skipped (--skip-dry-run) — the $0 gate is OFF")
        phases.append("dry_run_skipped")
    else:
        ok, msg = dry_run_check(program=program, workspace=workspace)
        if not ok:
            print(f"[hunt] ✗ dry-run: {msg}")
            return 1
        print(f"[hunt] dry-run     : {msg}")
        phases.append("dry_run")

    # 5. tools plan ───────────────────────────────────────────────────────
    try:
        tool_keys = reg.resolve_keys(tools_key)
    except ValueError as exc:
        print(f"[hunt] ✗ {exc}")
        return 1
    if per_target is None:
        per_target, scope_urls, wildcards = derive_targets(
            scope, getattr(args, "max_targets", 3))
        if wildcards:
            print(f"[hunt] note        : wildcards {wildcards} are NOT expanded "
                  "(no subdomain enumeration in-repo) — pass --targets to scan "
                  "specific subdomains")
        per_target = per_target or []
    else:
        # explicit --targets: also feed them as the stdin list (simplest,
        # honest behaviour)
        scope_urls = per_target
    tools_label = ", ".join(tool_keys) if tool_keys else "none (control plane only)"
    print(f"[hunt] tools       : {tools_label} | per-target hosts: {per_target or '—'}")
    phases.append("tools_planned")

    # RoE advisory (see roe_advisory) — printed at boot, after the tool plan.
    for line in roe_advisory(scope_file, tool_keys):
        print(line)

    # 6. boot the control plane as a child, in its OWN session: the parent
    #    (hunt) is the single controller of the whole tree — a terminal
    #    Ctrl-C reaches only the parent, which then tears down in order.
    run_cmd = [sys.executable, str(PROJECT_ROOT / "main.py"), "run",
               "--program", program, "--workspace", workspace]
    run_proc = subprocess.Popen(run_cmd, cwd=str(PROJECT_ROOT),
                                start_new_session=True)
    phases.append("booted")
    print(f"[hunt] control plane: pid {run_proc.pid} → war room "
          f"{API_URL}/  (state saved for pause/resume)")

    # Fail fast if the control plane cannot boot (bad config / no backend).
    time.sleep(5)
    if run_proc.poll() is not None:
        print(f"[hunt] ✗ control plane died at boot (exit {run_proc.returncode})")
        return run_proc.returncode or 1

    # Early state write: even a hard logout now leaves a resumable marker.
    write_state(program=program, platform=platform, workspace=workspace,
                scope_file=scope_file, tools=tool_keys, per_target=per_target,
                phases=phases, durable=snapshot_durable(workspace, program),
                status="running", run_pid=run_proc.pid)

    procs, notes = spawn_tools(
        keys=tool_keys, per_target=per_target, scope_urls=scope_urls,
        api_url=API_URL, egress_proxy=EGRESS_PROXY_URL, scope=scope)
    for n in notes:
        print(f"[hunt] note        : {n}")

    # 7. supervise ────────────────────────────────────────────────────────
    sd = _Shutdown()

    def _on_signal(signum, _frame):
        sd.requested = True

    prev_int = signal.signal(signal.SIGINT, _on_signal)
    prev_term = signal.signal(signal.SIGTERM, _on_signal)
    exit_code = 0
    status = "ended"
    try:
        while True:
            rc = run_proc.poll()
            if rc is not None:
                print(f"[hunt] control plane exited (code {rc}) — stopping tools")
                kill_tools(procs)
                exit_code = rc if rc >= 0 else 1
                status = "ended" if rc == 0 else "failed"
                break
            if sd.requested:
                print("[hunt] Ctrl-C — tearing down: tools first, then "
                      "control plane (ordered)")
                kill_tools(procs)
                exit_code = 0
                status = "paused"
                break
            # reap finished tools (fail-open: a dead tool is a log line)
            for tp in list(procs):
                if tp.proc.poll() is not None:
                    procs.remove(tp)
                    print(f"[hunt] tool {tp.key} (target={tp.target}) exited "
                          f"(code {tp.proc.returncode}) — hunt continues (fail-open)")
            time.sleep(1)
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)
        # Let the control plane child finish its own ordered teardown
        # (OOB loop → Interactsh deregister → mitmdump).
        if run_proc.poll() is None:
            try:
                run_proc.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                run_proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                run_proc.kill()
        # Final state write (the pause/resume marker).
        durable = snapshot_durable(workspace, program)
        state_path = write_state(
            program=program, platform=platform, workspace=workspace,
            scope_file=scope_file, tools=tool_keys, per_target=per_target,
            phases=phases, durable=durable, status=status,
            run_pid=run_proc.pid if _pid_alive(run_proc.pid) else None)
        print(f"[hunt] state       : {state_path} (status={status})")
        if status in ("paused", "failed"):
            print(f"[hunt] resume      : {_resume_cmd(program, workspace)}")
        print(f"[hunt] durable     : {len(durable['reports'])} report(s), "
              f"{len(durable['evidence'])} evidence file(s), "
              f"{durable['egress_log_lines']} egress log line(s) on disk")
        print("[hunt] volatile    : in-memory tasks / triage / budget / OOB "
              "session are gone (they lived only in the run process)")
    return exit_code


def cmd_hunt(args) -> int:
    # Program handle: positional (`hunt uzleuven`) or --program — main.py
    # folds the flag onto args.program before this runs; reject an empty
    # handle up front with the bare-form hint.
    program = getattr(args, "program", None)
    if not program or not str(program).strip():
        print("[hunt] ✗ missing program handle — bare form: "
              "`main.py hunt <program>` (e.g. `main.py hunt uzleuven`)")
        return 1
    args.program = str(program).strip()

    # Platform: explicit --platform always wins. Without it, a bare
    # `hunt <program>` defaults to intigriti — the only platform the harness
    # can auto-fetch scope from. Any other platform needs --platform (a
    # hand-copied scope file does not say where it came from).
    if not getattr(args, "platform", None):
        if getattr(args, "scope_file", None):
            print("[hunt] ✗ --platform is required when --scope-file is passed "
                  "(the file does not state which platform it came from)")
            return 1
        args.platform = "intigriti"
        print("[hunt] platform    : intigriti (default — the only "
              "auto-fetchable platform; pass --platform <p> for any other)")

    # Tools: default to the enabled registry tools so a bare `hunt <program>`
    # produces traffic from the first boot. Explicit --tools wins — including
    # `--tools none` for a control-plane-only run (resolve_keys maps "none"
    # to an empty plan).
    if not getattr(args, "tools", None):
        args.tools = ",".join(reg.ENABLED_KEYS)
    return _boot(args)


def cmd_resume(args) -> int:
    program: str = args.program
    workspace: str = getattr(args, "workspace", "./workspace")
    state = read_state(workspace, program)
    if state is None:
        # operator may have resumed from a different cwd
        state = read_state("./workspace", program)
        if state is not None:
            workspace = state.get("workspace") or workspace
        else:
            print(f"[resume] ✗ no saved state at "
                  f"{Path(workspace) / program / STATE_FILE_NAME} — "
                  f"run `main.py hunt` first (state is saved on every stop)")
            return 1
    if state.get("program") != program:
        print(f"[resume] ✗ state is for program {state.get('program')!r}, "
              f"not {program!r}")
        return 1

    print(f"[resume] state       : {state.get('status')} @ "
          f"{state.get('updated_at')} — {len(state.get('durable', {}).get('reports', []))} "
          f"report(s), {state.get('durable', {}).get('egress_log_lines', 0)} egress "
          f"line(s) survived the stop")

    # A previous control plane may have SURVIVED the logout (hard kill leaves
    # children running). It still holds :8001/:8080 — double-boot would fail
    # on the port. Detect and tell the operator exactly what to do.
    old_pid = state.get("run_pid")
    if _control_plane_up():
        if old_pid and _pid_alive(old_pid):
            teardown = f"      kill {old_pid}        # then re-run this resume command"
        else:
            teardown = (f"      (find it: pgrep -f 'main.py run --program "
                        f"{program}') — then re-run this resume command")
        pid_note = f" (saved pid {old_pid})" if old_pid else ""
        print(f"[resume] ✗ a control plane is already up on :8001{pid_note}"
              " — it survived the stop. Tear it down first:\n" + teardown)
        return 1

    print("[resume] rebuilding  : preflight → (re-)scope → init → dry-run → "
          "control plane → tools")

    # Re-fetch scope for Intigriti if the saved file vanished (the fetch is
    # idempotent and re-reads the live scope).
    scope_file = state.get("scope_file")
    if scope_file and not Path(scope_file).exists() and state.get("platform") == "intigriti":
        print("[resume] note        : saved scope file missing — re-fetching "
              "from Intigriti")
        scope_file = None

    ns = argparse.Namespace(
        program=program,
        platform=state.get("platform"),
        scope_file=scope_file,
        format=None,
        workspace=workspace,
        researcher="onoffgrid",
        tools=args.tools,               # CLI override (None = use saved)
        targets=args.targets,           # CLI override (None = use saved)
        max_targets=3,
        skip_dry_run=args.skip_dry_run,
    )
    return _boot(ns, state=state)
