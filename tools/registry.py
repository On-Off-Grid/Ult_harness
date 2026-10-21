# tools/registry.py
"""Tool registry for `main.py hunt` (S8.4 launcher).

A *tool* is one of the acquired third-party recon/exploit components (the
sibling dirs fetched by `scripts/fetch_components.sh`, see CREDITS.md) that
the operator may launch against the program. The control plane itself never
scans (S0 decision) — this registry only describes HOW to launch each tool
and what it needs to be runnable; the harness stays a guardrail, not a hunter.

Design rules
------------
* **Honesty, no fake launches.** Every entry is `enabled: False` until its
  exact CLI has been verified against the pinned commit (CREDITS.md). A tool
  whose CLI cannot be safely confirmed stays disabled with a `note` saying
  why — the launcher then skips it with a warning instead of guessing.
* **Pure data + pure functions.** No I/O, no network, no subprocess here —
  the launcher (`orchestrator/hunt_launcher.py`) is the only thing that
  actually spawns. That keeps this module unit-testable offline.
* **Corpora are not tools.** `Awesome-Redteam/` and `CL4R1T4S/` are reference
  material (playbooks / prompt corpora), not processes — they are deliberately
  NOT in this registry. `mempalace/` and `T3MP3ST/` are support services
  already covered by `.env` / the legacy path, not hunt-time tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass(frozen=True)
class ToolSpec:
    """One launchable tool.

    Attributes
    ----------
    key       : registry key the operator passes to `--tools` (also the alias).
    label     : human name for logs/docs.
    kind      : "scanner" (points at targets), "agent" (long-running, may be
                interactive), "aux" (support, no target).
    enabled   : False until the CLI is verified against the pinned commit.
    per_target: True  -> launch ONE process per selected target (target is
                substituted into `cmd` as `{target}`).
                False -> launch ONE process; targets are provided via
                `stdin` (a list of URL strings) or not at all.
    needs     : list of (label, check_fn). Each check returns a human
                explanation of what is missing, or None when satisfied.
                All must pass before the tool is launched.
    build     : optional one-time setup (e.g. `go build`), run when `needs`
                pass but the artifact is missing.
    """

    key: str
    label: str
    kind: str
    cmd: List[str] = field(default_factory=list)
    enabled: bool = False
    per_target: bool = False
    needs: List = field(default_factory=list)
    build: Optional[List[str]] = None
    cwd: str = ""                       # relative to project root
    stdin_kind: str = "none"            # "none" | "targets" | "scope_urls"
    note: str = ""                      # shown when a tool is skipped/disabled


# ── runtime checks (shared) ───────────────────────────────────────────────

def _have_bin(binary: str) -> Optional[str]:
    import shutil
    return None if shutil.which(binary) else f"`{binary}` not on PATH"


def _dir_exists(rel: str) -> Optional[str]:
    import main  # PROJECT_ROOT
    return None if (main.PROJECT_ROOT / rel).is_dir() else f"dir missing: {rel}/"


# ── jsleak — Go JS-secrets/link scanner ───────────────────────────────────
# Reads URLs from STDIN (bufio.Scanner), not CLI args. Emits JSON lines with
# -json. `go` is on PATH in the operator env; the binary is built once into
# bin/jsleak (gitignored).
def _jsleak_binary() -> Optional[str]:
    import main
    b = main.PROJECT_ROOT / "jsleak" / "bin" / "jsleak"
    return None if b.exists() else "jsleak/bin/jsleak not built (auto-builds via `go build`)"


def _build_jsleak() -> None:
    import subprocess
    import main
    subprocess.run(
        # -o is relative to cwd (the jsleak/ module dir), so the binary lands
        # in <root>/jsleak/bin/jsleak — a one-time build, ~10 s.
        ["go", "build", "-o", "bin/jsleak", "."],
        cwd=str(main.PROJECT_ROOT / "jsleak"),
        check=True,
        capture_output=True,
    )


# ── cbb — claude-bug-bounty ReAct recon agent ─────────────────────────────
# `python agent.py --target <domain>`. Long-running, LLM-driven. Needs the
# Anthropic/Claude credentials it normally uses; launched per-target.
def _cbb_help_ok() -> Optional[str]:
    """Best-effort: agent.py must at least parse its own --help. If it cannot
    be run (missing deps / no interpreter) we refuse to launch it rather than
    guess. Verified against the pinned commit before flipping enabled=True."""
    import subprocess
    import main
    py = str(main.PROJECT_ROOT / ".venv" / "bin" / "python")
    import os
    if not os.path.exists(py):
        py = "python3"
    r = subprocess.run(
        [py, "agent.py", "--help"],
        cwd=str(main.PROJECT_ROOT / "claude-bug-bounty"),
        capture_output=True, timeout=30,
    )
    return None if r.returncode == 0 else \
        "agent.py --help did not exit 0 (missing deps or runtime)"


# ── adhd — divergent-ideation aux (no target) ─────────────────────────────
# `node dist/cli.js <prompt> --frames N --ideas N`. Advisory, not a scanner.
def _adhd_cli() -> Optional[str]:
    import main
    return None if (main.PROJECT_ROOT / "adhd" / "dist" / "cli.js").exists() \
        else "adhd/dist/cli.js missing (run the build in adhd/ first)"


# ── agent-reach — OSINT daemon (aux, no target) ───────────────────────────
# pip console-script `agent-reach`. Not installed by default; if the module
# is not importable we skip it (fail-open) instead of launching blind.
def _agent_reach_importable() -> Optional[str]:
    import importlib.util
    return None if importlib.util.find_spec("agent_reach") else \
        "`agent-reach` not installed (pip install -e Agent-Reach/)"


TOOLS = {
    "jsleak": ToolSpec(
        key="jsleak",
        label="jsleak — JS secrets & links scanner (Go)",
        kind="scanner",
        enabled=True,
        per_target=False,
        cmd=["jsleak/bin/jsleak", "-json", "-e", "-s", "-l", "-c", "10"],
        needs=[("jsleak/bin/jsleak built", _jsleak_binary)],
        build=_build_jsleak,
        stdin_kind="scope_urls",   # feed the in-scope URL list via stdin
        note="reads URLs from stdin; one process covers the whole scope list",
    ),
    "cbb": ToolSpec(
        key="cbb",
        label="claude-bug-bounty — ReAct recon agent (Python)",
        kind="agent",
        enabled=True,
        per_target=True,
        cmd=["{python}", "agent.py", "--target", "{target}"],
        cwd="claude-bug-bounty",
        needs=[("agent.py --help exits 0", _cbb_help_ok)],
        note="one long-running agent per selected target; LLM-driven",
    ),
    "adhd": ToolSpec(
        key="adhd",
        label="adhd — divergent ideation (Node, advisory)",
        kind="aux",
        enabled=False,
        per_target=False,
        cmd=["node", "adhd/dist/cli.js", "{prompt}", "--frames", "20"],
        needs=[("adhd/dist/cli.js present", _adhd_cli), ("node on PATH", lambda: _have_bin("node"))],
        note="advisory ideation engine — no target flag; disabled until the "
             "operator supplies a per-hunt prompt (not safe to auto-run)",
    ),
    "agent-reach": ToolSpec(
        key="agent-reach",
        label="Agent-Reach — OSINT health daemon (Python)",
        kind="aux",
        enabled=False,
        per_target=False,
        cmd=["agent-reach"],
        needs=[("agent-reach importable", _agent_reach_importable)],
        note="OSINT daemon, not a target scanner — disabled in v1; "
             "pip install -e Agent-Reach/ then enable",
    ),
}

ALL_KEYS = list(TOOLS.keys())

# The tools a bare `hunt <program>` launches by default (everything currently
# enabled — jsleak + cbb as of S8.4). `--tools` still wins, including
# `--tools none` for a control-plane-only run; the launcher skips any
# disabled key with a note either way.
ENABLED_KEYS = [k for k, s in TOOLS.items() if s.enabled]


def resolve_keys(comma_list: Optional[str]) -> List[str]:
    """`"jsleak,cbb"` -> ["jsleak", "cbb"]; unknown keys raise ValueError with
    the list of valid keys (so the operator gets a usable error, not a
    silent skip). ``"none"`` (any case) is the explicit control-plane-only
    selection — not a registry key."""
    if not comma_list:
        return []
    if comma_list.strip().lower() == "none":
        return []
    keys = [k.strip() for k in comma_list.split(",") if k.strip()]
    bad = [k for k in keys if k not in TOOLS]
    if bad:
        raise ValueError(
            f"unknown tool(s) {bad!r} — valid: {ALL_KEYS}"
        )
    # de-dup, preserve order
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def build_env(*, api_url: str, egress_proxy: str, extra: Optional[dict] = None) -> dict:
    """The env block a launched tool needs so it egresses through the scope
    gate and (where it's wired) calls back into the harness. Mirrors the
    manual export block in docs/examples/uzleuven_intigriti.md §Step 5.

    Everything is 127.0.0.1 + the egress proxy; NO_PROXY keeps localhost
    (the harness API, Ollama, mempalace) out of the proxy loop.
    """
    import os
    env = dict(os.environ)
    env.update({
        "HARNESS_API_URL": api_url,
        "HARNESS_EGRESS_PROXY": egress_proxy,
        "HTTP_PROXY": egress_proxy,
        "HTTPS_PROXY": egress_proxy,
        "NO_PROXY": "localhost,127.0.0.1",
    })
    if extra:
        env.update(extra)
    return env
