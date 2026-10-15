#!/usr/bin/env python3
# main.py
"""Ult_harness CLI entry point (S3.3).

Commands
  init  — parse a program scope file, create the workspace, export the
          platform profile (headers) for the egress proxy / specialists.
  run   — boot the full control-plane graph in-process:
            config → compliance (scope gate) → budget (router/tracker)
            → OpAdmiral → triage → reporting → mempalace write-back
          with --dry-run walking the entire graph on a sample hunt using
          mocked component calls (no packets, no LLM calls, no palace writes).
  stop  — shut down an in-process run (single-process model; also prints the
          external-service teardown order for live multi-service setups).

Live run additionally spawns the mitmdump egress proxy (:8080) and serves the
admiral REST/WS API (:8001) via uvicorn.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# Ensure the project root is importable no matter where main.py is launched from.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import HarnessConfig  # noqa: E402
from core.types import (  # noqa: E402
    MultiSessionContext,
    Platform,
    PlatformHeaders,
    ScopeMatchType,
    ScopeRule,
    TargetScope,
    TokenBudget,
    VulnCategory,
    VulnStatus,
)
from compliance.header_injector import HeaderInjector, PlatformProfile  # noqa: E402
from compliance.scope_importer import ScopeImporter  # noqa: E402
from orchestrator.admiral import OpAdmiral, build_graph  # noqa: E402
from reporting.writers import ReportGateError  # noqa: E402

logger = logging.getLogger("harness.main")

SCOPED_PLATFORMS = (
    Platform.HACKERONE,
    Platform.BUGCROWD,
    Platform.YESWEHACK,
    Platform.INTIGRITI,
)


# ═══════════════════════════════════════════════════════════════════════════
# init
# ═══════════════════════════════════════════════════════════════════════════

def _parse_scope(args) -> TargetScope:
    """Parse the scope file per its --format (or infer it).

    The operator's `--platform` is authoritative: importer parsers stamp
    their own platform on the TargetScope, which would silently override it.
    """
    fmt = (args.format or "").lower() or _infer_format(args.scope_file)
    scope_file = args.scope_file

    if fmt == "hackerone_csv":
        scope = ScopeImporter.parse_hackerone_csv(scope_file, args.program)
    elif fmt == "bugcrowd_json":
        scope = ScopeImporter.parse_bugcrowd_json(scope_file, args.program)
    elif fmt in ("yeswehack_json", "intigriti_json"):
        method = getattr(ScopeImporter, f"parse_{fmt}")
        scope = method(scope_file, args.program)
    else:
        # Fallback: minimal inline scope (for dev / Gate S3 sample scopes).
        logger.warning(f"--format '{fmt}' unsupported — using permissive wildcard scope")
        scope = TargetScope(
            program_handle=args.program,
            platform=Platform(args.platform),
            in_scope=[ScopeRule(pattern="*", match_type=ScopeMatchType.WILDCARD)],
        )
        return scope

    scope.platform = Platform(args.platform)
    return scope


def _infer_format(scope_file: str) -> str:
    if scope_file.endswith(".csv"):
        return "hackerone_csv"
    if scope_file.endswith(".json"):
        return "bugcrowd_json"
    return "bugcrowd_json"


def cmd_init(args) -> int:
    platform = Platform(args.platform)
    scope = _parse_scope(args)

    workspace = Path(args.workspace) / scope.program_handle
    (workspace / "logs").mkdir(parents=True, exist_ok=True)
    (workspace / "reports").mkdir(parents=True, exist_ok=True)
    (workspace / "evidence").mkdir(parents=True, exist_ok=True)

    # Platform profile → header export (single source of truth, design v2.1 §1.4)
    headers = PlatformHeaders.for_platform(platform, args.researcher)
    profile = PlatformProfile(
        platform=platform.value,
        program_handle=scope.program_handle,
        researcher_username=args.researcher,
        headers={**headers.headers, **({"User-Agent": headers.user_agent} if headers.user_agent else {})},
        rate_limit_rps=scope.rate_limit_rps,
        max_concurrent_requests=scope.max_concurrent,
        auth={},
    )
    injector = HeaderInjector(profile)
    profile_path = workspace / "platform_profile.json"
    profile_path.write_text(json.dumps(vars(profile), indent=2, default=str), encoding="utf-8")
    headers_path = workspace / "headers.txt"
    injector.export_headers_file(str(headers_path))

    # Persist the parsed scope so run/egress can reload it.
    scope_path = workspace / "scope.json"
    scope_path.write_text(
        json.dumps({
            "program_handle": scope.program_handle,
            "platform": scope.platform.value,
            "in_scope": [
                {"pattern": r.pattern, "match_type": r.match_type.value, "description": r.description}
                for r in scope.in_scope
            ],
            "out_of_scope": [
                {"pattern": r.pattern, "match_type": r.match_type.value, "description": r.description}
                for r in scope.out_of_scope
            ],
            "rate_limit_rps": scope.rate_limit_rps,
            "max_concurrent": scope.max_concurrent,
        }, indent=2),
        encoding="utf-8",
    )

    print(f"[init] program      : {scope.program_handle} ({platform.value})")
    print(f"[init] in-scope     : {len(scope.in_scope)} rule(s)")
    print(f"[init] out-of-scope : {len(scope.out_of_scope)} rule(s)")
    print(f"[init] workspace    : {workspace}")
    print(f"[init] profile      : {profile_path}")
    print(f"[init] headers      : {headers_path}")
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# run — dry-run graph walk
# ═══════════════════════════════════════════════════════════════════════════

def _load_workspace_scope(workspace_root: str, program: str) -> TargetScope:
    """Reload the scope.json produced by `init`."""
    scope_path = Path(workspace_root) / program / "scope.json"
    if not scope_path.exists():
        raise FileNotFoundError(
            f"{scope_path} not found — run `main.py init` for program "
            f"'{program}' first."
        )
    data = json.loads(scope_path.read_text(encoding="utf-8"))
    return TargetScope(
        program_handle=data["program_handle"],
        platform=Platform(data["platform"]),
        in_scope=[
            ScopeRule(
                pattern=r["pattern"],
                match_type=ScopeMatchType(r["match_type"]),
                description=r.get("description", ""),
            )
            for r in data.get("in_scope", [])
        ],
        out_of_scope=[
            ScopeRule(
                pattern=r["pattern"],
                match_type=ScopeMatchType(r["match_type"]),
                description=r.get("description", ""),
            )
            for r in data.get("out_of_scope", [])
        ],
        rate_limit_rps=data.get("rate_limit_rps", 10.0),
        max_concurrent=data.get("max_concurrent", 5),
    )


def _sample_endpoint(scope: TargetScope) -> str:
    """Pick a plausible in-scope endpoint for the dry-run hunt."""
    for rule in scope.in_scope:
        if rule.match_type == ScopeMatchType.WILDCARD and rule.pattern.startswith("*."):
            return f"https://app.{rule.pattern[2:]}:8443"
        if rule.match_type == ScopeMatchType.EXACT:
            return f"https://{rule.pattern}"
    return "https://target.example.invalid"


class _MockSpecialist:
    """Gate-S3 'mocked component call': deterministic findings, zero network."""

    def __init__(self, category: VulnCategory):
        self._category = category
        self.calls: List[str] = []

    @property
    def category(self) -> VulnCategory:
        return self._category

    async def scan(self, target, scope, session_ctx, correlation_id):
        self.calls.append(target)
        from triage.noise_filter import Finding
        return [
            Finding(
                finding_id=f"dryrun_{self._category.value}_{len(self.calls)}",
                title=f"Dry-run {self._category.value} on {target}",
                description=f"Synthetic {self._category.value} finding produced by the "
                            f"mocked specialist for graph validation (no network).",
                vuln_category=self._category.value,
                endpoint=target,
                evidence={"poc": "curl -s 'http://dry-run.invalid/poc'"},
                confidence=0.5,
                metadata={"specialist": f"{self._category.value}_specialist"},
            )
        ]


async def _dry_run_walk(graph: dict, scope: TargetScope) -> int:
    """Walk config → gate → admiral → triage → report → memory with a mocked
    specialist. Exercises every stage of the pipeline in-process."""
    admiral: OpAdmiral = graph["admiral"]
    print(f"[dry-run] program   : {scope.program_handle}")
    print(f"[dry-run] platform  : {scope.platform.value}")
    print(f"[dry-run] in-scope  : {len(scope.in_scope)} rule(s), "
          f"out-of-scope: {len(scope.out_of_scope)} rule(s)")

    endpoint = _sample_endpoint(scope)
    print(f"[dry-run] endpoint  : {endpoint}")

    # Stage: gate
    assert admiral.scope_gate.is_in_scope(endpoint), "sample endpoint must be in scope"
    print("[dry-run] ① scope gate  : sample endpoint ALLOWED")
    assert not admiral.scope_gate.is_in_scope("https://evil.example.com/x"), \
        "unrelated host must be blocked"
    print("[dry-run] ① scope gate  : unrelated host BLOCKED")

    # Stage: budget-aware model selection (no call made)
    tier, model = graph["model_router"].resolve_model("payload_craft")
    print(f"[dry-run] ② model route : payload_craft → {tier.value}/{model}")

    # Stage: dispatch (mocked specialist = component call mocked)
    mock = _MockSpecialist(VulnCategory.SQLI)
    task = admiral.make_task(
        specialist_id="sqli_specialist",
        target_endpoint=endpoint,
        vuln_category=VulnCategory.SQLI,
    )
    result = await admiral.dispatch(task, specialist=mock,
                                    session_ctx=MultiSessionContext())
    assert result.status == "ok" and len(result.findings) == 1, \
        f"mock dispatch failed: {result}"
    print(f"[dry-run] ③ dispatch    : {len(result.findings)} finding(s) from mocked specialist")

    # Stage: triage (noise filter → state machine)
    ingest = await admiral.ingest_finding(result.findings[0])
    assert ingest.action == "ingested" and ingest.status == VulnStatus.VALIDATING, \
        f"ingest failed: {ingest}"
    print(f"[dry-run] ④ triage      : {ingest.task_id} → {ingest.status.value}")

    # Stage: noise filter — a non-bountiable pattern must be dropped
    from triage.noise_filter import Finding
    noise = Finding(
        finding_id="dryrun_noise_1",
        title="Missing security header on login",
        description="CSP and HSTS headers are absent.",
        vuln_category="xss",
        endpoint=endpoint,
    )
    noise_result = await admiral.ingest_finding(noise)
    assert noise_result.action == "dropped_noise", f"noise filter failed: {noise_result}"
    print(f"[dry-run] ④ noise filter: missing-header finding DROPPED ({noise_result.reason})")

    # Stage: operator approval → report (CONFIRMED gate)
    try:
        admiral.generate_report(ingest.task_id, scope.platform)
        raise AssertionError("report generated for a non-CONFIRMED finding — gate failed")
    except ReportGateError:
        print(f"[dry-run] ⑤ report gate : pre-confirmation report correctly refused")

    await admiral.confirm_finding(ingest.task_id, evidence={"poc": "curl -s '...'"})
    report = admiral.generate_report(ingest.task_id, scope.platform)
    print(f"[dry-run] ⑥ report      : {report.path} ({report.severity}, CWE-{report.cwe})")

    # Stage: memory write-back (dry-run → 'would file' only)
    drawers = await admiral.write_back_memory()
    print(f"[dry-run] ⑦ mempalace   : {len(drawers)} drawer(s) would be filed "
          f"(dry-run, no chromadb write)")

    print(f"[dry-run] status      : {json.dumps(admiral.status())}")
    print("[dry-run] ✅ full graph walked: config → gate → admiral → report → memory")
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# run — live
# ═══════════════════════════════════════════════════════════════════════════

def _spawn_egress_proxy(config: HarnessConfig, scope: TargetScope,
                        workspace_root: str) -> Optional[subprocess.Popen]:
    """Spawn mitmdump with the EgressProxy addon (live mode only)."""
    if not shutil.which("mitmdump"):
        logger.warning("mitmdump not found on PATH — egress proxy not started")
        return None
    env = dict(os.environ)
    env.update({
        "HARNESS_PROGRAM_HANDLE": scope.program_handle,
        "HARNESS_WING_ID": scope.program_handle,
        "HARNESS_WORKSPACE": str(Path(workspace_root).resolve()),
        "EGRESS_PROXY_PORT": str(config.egress_proxy_port),
    })
    addon = str(PROJECT_ROOT / "compliance" / "egress_proxy.py")
    cmd = [
        "mitmdump", "--listen-port", str(config.egress_proxy_port),
        "--set", "block_global=false",
        "-s", addon,
    ]
    logger.info(f"spawning egress proxy: {' '.join(cmd)}")
    return subprocess.Popen(cmd, env=env)


async def _run_live(args) -> int:
    import uvicorn
    from orchestrator.admiral import create_app

    config = HarnessConfig.load_from_env()
    scope = _load_workspace_scope(args.workspace, args.program)
    graph = build_graph(config, scope)

    proxy_proc = _spawn_egress_proxy(config, scope, args.workspace)
    try:
        # Router health check (raises NoBudgetError if no backend at all).
        await graph["model_router"].startup_health_check()

        # Auth bootstrap (only if the profile carries personas).
        profile_path = Path(args.workspace) / args.program / "platform_profile.json"
        if profile_path.exists():
            auth = json.loads(profile_path.read_text(encoding="utf-8")).get("auth") or {}
            if auth:
                from sessions.session_manager import SessionManager
                sm = SessionManager(auth, proxy_url=f"http://127.0.0.1:{config.egress_proxy_port}")
                graph["admiral"].session_manager = sm
                await sm.bootstrap_sessions()
                logger.info("session manager bootstrapped")

        app = create_app(graph["admiral"])
        server_config = uvicorn.Config(app, host="127.0.0.1", port=config.api_port, log_level="warning")
        server = uvicorn.Server(server_config)
        await server.serve()
    finally:
        if proxy_proc is not None:
            proxy_proc.terminate()
            try:
                proxy_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proxy_proc.kill()
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# stop
# ═══════════════════════════════════════════════════════════════════════════

def cmd_stop(args) -> int:
    print("[stop] teardown order (external services):")
    print("       1. OpAdmiral REST/WS   (:8001) — in-process, exits with `run`")
    print("       2. mitmdump egress     (:8080) — child process, terminated with `run`")
    print("       3. mempalace           (:8000) — external service, stop separately")
    print("       4. Ollama              (:11434) — external service, leave running")
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Ult_harness — autonomous bug-bounty control plane (S3).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="parse scope file, create workspace, export platform profile")
    p_init.add_argument("--platform", required=True, choices=[p.value for p in Platform])
    p_init.add_argument("--program", required=True, help="program handle (e.g. acme-corp)")
    p_init.add_argument("--scope-file", required=True, help="H1 CSV / Bugcrowd JSON / YWH-Intigriti JSON")
    p_init.add_argument("--format", default=None,
                        help="hackerone_csv | bugcrowd_json | yeswehack_json | intigriti_json "
                             "(inferred from extension when omitted)")
    p_init.add_argument("--researcher", default="researcher",
                        help="researcher username for platform attribution headers")
    p_init.add_argument("--workspace", default="./workspace")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="boot the harness (full control-plane graph)")
    p_run.add_argument("--program", required=True, help="program handle (must be init'ed)")
    p_run.add_argument("--dry-run", action="store_true",
                       help="walk the full graph with mocked component calls — no packets, "
                            "no LLM calls, no palace writes")
    p_run.add_argument("--workspace", default="./workspace")
    p_run.set_defaults(func=cmd_run)

    p_stop = sub.add_parser("stop", help="print the live-service teardown order")
    p_stop.set_defaults(func=cmd_stop)

    return parser


def cmd_run(args) -> int:
    config = HarnessConfig.load_from_env()
    if args.dry_run:
        config.dry_run = True
    config.workspace_dir = args.workspace  # bind CLI workspace into the graph

    scope = _load_workspace_scope(args.workspace, args.program)
    graph = build_graph(config, scope)

    if args.dry_run:
        return asyncio.run(_dry_run_walk(graph, scope))
    return asyncio.run(_run_live(args))


def _load_dotenv() -> None:
    """Load .env from the project root if present (never fatal).

    Keys live in the gitignored `.env` — the only sanctioned location
    (docs/provisioning.md). Real environment variables always win over
    .env values (override=False).
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    try:
        import dotenv
        dotenv.load_dotenv(env_file, override=False)
    except ImportError:
        logger.warning("python-dotenv not installed — .env not loaded "
                       "(export variables manually)")


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
