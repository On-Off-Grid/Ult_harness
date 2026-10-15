# orchestrator/admiral.py
"""OpAdmiral — THE BRAIN of the harness (S3.1).

Central coordinator per workflow_overview.md §2: receives tasks, dispatches
specialists, enforces scope, tracks triage state, gates budget, writes
reports, and keeps the memory palace fed.

Architecture (plan v3 S3.1 + gap-bridging spec §3.2, adapted to the S2-verified
control-plane APIs):

  * The core is a **pure-Python async class** (`OpAdmiral`) with no web
    dependency — the Gate-S3 dry-run graph walk and the whole test-suite drive
    it directly (mocked specialist LLM calls).
  * The FastAPI transport layer (REST + /ws, port 8001) is provided by
    `create_app()` and imported **lazily**, so the brain works even in
    environments without fastapi installed.

Wired (all S2-verified, all GREEN):
  compliance.scope_gate.ScopeGate        — kill switch on scope violations
  compliance.scope_importer.ScopeImporter
  compliance.header_injector.HeaderInjector
  budget.token_tracker.TokenTracker      — per-agent budgets, warning/exhausted events
  budget.model_router.ModelRouter        — budget-aware model selection
  sessions.session_manager.SessionManager
  triage.noise_filter.NoiseFilter        — FP drop before triage
  triage.state_machine.TriageStateMachine — IDENTIFIED→VALIDATING→CONFIRMED/…
  agents.dual_session_tester.DualSessionTester — IDOR/BAC validation hook
  reporting.writers.ReportWriter         — CONFIRMED/CHAINED-only reports
  reporting.taxonomy.TaxonomyMapper

Component wiring hooks that never shipped in Phase 4B (4.6/4.7 of
patches/local-tweaks.md §6) are exposed here as the harness side of the
contract:
  record_tokens()        — 4.6: adhd engine POST /api/tokens/record target
  route_llm_request()    — 4.7: cbb agent router POST /api/v1/llm/route target
Both delegate to the verified TokenTracker / ModelRouter (spec blueprint
constructor mismatches — TokenTracker(hard_cap=…), ScopeGate(),
SessionManager(state.config) — corrected against the real signatures).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import HarnessConfig
from core.event_bus import IEventBus, InMemoryEventBus
from core.types import (
    MultiSessionContext,
    OrchestrationEvent,
    Platform,
    Task,
    TargetScope,
    TokenBudget,
    VulnCategory,
    VulnStatus,
)
from budget.model_router import ModelRouter, NoBudgetError
from budget.token_tracker import TokenTracker
from compliance.scope_gate import ScopeGate
from agents.dual_session_tester import DualSessionTester
from reporting.writers import ReportResult, ReportWriter
from triage.noise_filter import DropReason, Finding as NoiseFinding, NoiseFilter
from triage.state_machine import InvalidTransitionError, TriageStateMachine

logger = logging.getLogger(__name__)

# Kill switch: N scope violations halt dispatch entirely (defense in depth —
# the egress proxy still blocks at the network layer).
DEFAULT_KILL_SWITCH_THRESHOLD = 3


@dataclass
class DispatchResult:
    """Outcome of dispatching one task to its specialist."""
    task_id: str
    specialist: str
    status: str                 # "ok" | "skipped_halted" | "skipped_out_of_scope"
                                # | "error"
    findings: List[Any] = field(default_factory=list)
    detail: str = ""


@dataclass
class IngestResult:
    """Outcome of pushing a finding through the triage pipeline."""
    finding_id: str
    action: str                 # "ingested" | "dropped_noise" | "dropped_out_of_scope"
    task_id: Optional[str] = None
    status: Optional[VulnStatus] = None
    reason: str = ""
    validation: str = ""


class HuntHaltedError(RuntimeError):
    """Raised by dispatch when the kill switch is engaged."""


class OpAdmiral:
    """The central coordinator (brain) of the harness.

    Construct via `build_graph()` or directly:

        admiral = OpAdmiral(config, scope, event_bus=bus)
        await admiral.dispatch(task)
        result = admiral.ingest_finding({...})
    """

    def __init__(
        self,
        config: HarnessConfig,
        scope: TargetScope,
        event_bus: Optional[IEventBus] = None,
        token_tracker: Optional[TokenTracker] = None,
        model_router: Optional[ModelRouter] = None,
        noise_filter: Optional[NoiseFilter] = None,
        state_machine: Optional[TriageStateMachine] = None,
        report_writer: Optional[ReportWriter] = None,
        session_manager: Any = None,
        kill_switch_threshold: int = DEFAULT_KILL_SWITCH_THRESHOLD,
    ):
        self.config = config
        self.scope = scope
        self.event_bus = event_bus or InMemoryEventBus()
        self.token_tracker = token_tracker or TokenTracker(self.event_bus)
        self.model_router = model_router or ModelRouter(config, self.token_tracker)
        self.scope_gate = ScopeGate(scope)
        self.noise_filter = noise_filter or NoiseFilter()
        self.state_machine = state_machine or TriageStateMachine(self.event_bus)
        self.report_writer = report_writer or ReportWriter(config.workspace_dir)
        self.session_manager = session_manager
        self.dual_session_tester = DualSessionTester(proxy_url=f"http://127.0.0.1:{config.egress_proxy_port}")

        # ── Hunt state ──
        self.tasks: Dict[str, Task] = {}
        self.findings: Dict[str, Any] = {}          # finding_id -> raw finding dict
        self.task_by_finding: Dict[str, str] = {}   # finding_id -> task_id
        self.scope_violations: List[str] = []
        self.halted: bool = False
        self.kill_switch_threshold = kill_switch_threshold
        self.reports: List[ReportResult] = []
        self.dry_run = config.dry_run

    # ══════════════════════════════════════════════════════════════════════
    # Task dispatch (S3.1)
    # ══════════════════════════════════════════════════════════════════════

    def register_task(self, task: Task) -> Task:
        """Track a task in the admiral's registry (idempotent)."""
        self.tasks[task.task_id] = task
        return task

    def make_task(
        self,
        specialist_id: str,
        target_endpoint: str,
        vuln_category: VulnCategory,
        correlation_id: Optional[str] = None,
        wing_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        task = Task(
            task_id=f"task_{uuid.uuid4().hex[:10]}",
            wing_id=wing_id or self.scope.program_handle,
            specialist_id=specialist_id,
            correlation_id=correlation_id or uuid.uuid4().hex[:12],
            target_endpoint=target_endpoint,
            vuln_category=vuln_category,
            metadata=metadata or {},
        )
        return self.register_task(task)

    async def _enforce_scope(self, task: Task) -> Optional[str]:
        """Scope kill switch: out-of-scope targets are rejected at dispatch
        time (the egress proxy is the network-layer backstop). Repeated
        violations engage the halt switch for the whole hunt."""
        if self.scope_gate.is_in_scope(task.target_endpoint):
            return None
        self.scope_violations.append(task.target_endpoint)
        logger.warning(
            "scope_violation",
            extra={
                "task_id": task.task_id,
                "endpoint": task.target_endpoint,
                "count": len(self.scope_violations),
            },
        )
        if len(self.scope_violations) >= self.kill_switch_threshold and not self.halted:
            self.halted = True
            logger.error(
                f"KILL SWITCH engaged — {len(self.scope_violations)} scope violations"
            )
        try:
            await self.state_machine.transition(
                task,
                VulnStatus.OUT_OF_SCOPE,
                evidence={"violated_scope": task.target_endpoint},
            )
        except InvalidTransitionError:
            pass  # already in a terminal state
        return (
            f"OUT_OF_SCOPE: {task.target_endpoint} "
            f"(violation #{len(self.scope_violations)})"
        )

    async def dispatch(
        self,
        task: Task,
        specialist: Any = None,
        session_ctx: Optional[MultiSessionContext] = None,
    ) -> DispatchResult:
        """Dispatch a task to its specialist.

        specialist: an ISpecialist instance (with async scan(...)). If None,
        the task is dry-run: validated for scope + budget but no scan is
        executed (used by Gate S3 with mocked component calls).
        """
        if self.halted:
            return DispatchResult(
                task.task_id, task.specialist_id, "skipped_halted",
                detail="hunt halted by scope kill switch",
            )

        violation = await self._enforce_scope(task)
        if violation:
            return DispatchResult(task.task_id, task.specialist_id, "skipped_out_of_scope", detail=violation)

        if specialist is None:
            tier, model = self.model_router.resolve_model("payload_craft")
            return DispatchResult(
                task.task_id, task.specialist_id, "ok",
                detail=f"dry-run: no scan executed (would use {tier.value}/{model})",
            )

        ctx = session_ctx or getattr(self.session_manager, "context", None) \
            or MultiSessionContext()
        try:
            findings = await specialist.scan(
                task.target_endpoint,
                self.scope,
                ctx,
                task.correlation_id,
            )
        except NoBudgetError as exc:
            # Budget-aware model selection failed — record and skip.
            logger.error(f"dispatch {task.task_id}: {exc}")
            return DispatchResult(task.task_id, task.specialist_id, "error", detail=str(exc))
        except Exception as exc:  # specialist crash must not kill the hunt
            logger.exception(f"dispatch {task.task_id} failed: {exc}")
            return DispatchResult(task.task_id, task.specialist_id, "error", detail=str(exc))

        return DispatchResult(task.task_id, task.specialist_id, "ok", findings=list(findings))

    # ══════════════════════════════════════════════════════════════════════
    # Finding ingestion: noise filter → (dual-session validation) → state machine
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _finding_to_noise(f: Any) -> NoiseFinding:
        """Accept either a triage.noise_filter.Finding or a raw dict."""
        if isinstance(f, NoiseFinding):
            return f
        d = f if isinstance(f, dict) else vars(f)
        return NoiseFinding(
            finding_id=str(d.get("finding_id", uuid.uuid4().hex[:10])),
            title=str(d.get("title", "")),
            description=str(d.get("description", "")),
            vuln_category=str(d.get("vuln_category", "sqli")),
            endpoint=str(d.get("endpoint", "")),
            evidence=d.get("evidence", {}) or {},
            confidence=float(d.get("confidence", 0.0)),
            metadata=d.get("metadata", {}) or {},
        )

    async def _dual_session_validate(self, nf: NoiseFinding) -> Optional[str]:
        """S3.1 dual-session validation hook.

        Runs for IDOR/BAC findings that carry matrix evidence. Returns the
        validation verdict string, or None when the finding does not need
        (or does not have) matrix results.
        """
        category = self._parse_category(nf.vuln_category)
        if category not in (VulnCategory.IDOR, VulnCategory.BAC):
            return None
        matrix = (nf.evidence or {}).get("matrix")
        if not matrix:
            return None
        is_idor, is_bac, description = DualSessionTester.analyze_results(matrix)
        verdict = "IDOR" if is_idor else ("BAC" if is_bac else "NO_BUG")
        logger.info(
            "dual_session_validation",
            extra={"finding_id": nf.finding_id, "verdict": verdict, "detail": description},
        )
        return f"{verdict}: {description}"

    @staticmethod
    def _parse_category(raw: str) -> VulnCategory:
        try:
            return VulnCategory(raw)
        except ValueError:
            return VulnCategory.SQLI  # defensive default for unknown labels

    async def ingest_finding(self, f: Any) -> IngestResult:
        """Push one raw finding through: noise filter → dual-session
        validation → scope check → triage state machine (→ VALIDATING)."""
        nf = self._finding_to_noise(f)
        self.findings[nf.finding_id] = (
            nf if isinstance(nf, NoiseFinding) else dict(nf)
        )

        # 1) Scope — findings on out-of-scope endpoints are recorded, never triaged.
        if not self.scope_gate.is_in_scope(nf.endpoint):
            self.scope_violations.append(nf.endpoint)
            return IngestResult(
                nf.finding_id, "dropped_out_of_scope",
                reason=f"endpoint {nf.endpoint} out of scope",
            )

        # 2) Noise filter — non-bountiable patterns dropped before triage.
        result = self.noise_filter.filter(nf)
        if not result.passed:
            return IngestResult(
                nf.finding_id, "dropped_noise",
                reason=result.reason.value if result.reason else "noise",
            )

        # 3) Dual-session validation hook (IDOR/BAC with matrix evidence).
        validation = await self._dual_session_validate(nf)

        # 4) State machine: create task, IDENTIFIED → VALIDATING.
        task = self.make_task(
            specialist_id=str(nf.metadata.get("specialist", "unknown")),
            target_endpoint=nf.endpoint,
            vuln_category=self._parse_category(nf.vuln_category),
            metadata={
                "finding_id": nf.finding_id,
                "title": nf.title,
                "description": nf.description,
                "confidence": nf.confidence,
                "dual_session": validation or "",
            },
        )
        self.task_by_finding[nf.finding_id] = task.task_id
        await self.state_machine.transition(
            task,
            VulnStatus.VALIDATING,
            evidence={"evidence_keys": list(nf.evidence.keys())},
        )
        return IngestResult(
            nf.finding_id, "ingested", task_id=task.task_id,
            status=task.status, validation=validation or "",
        )

    # ══════════════════════════════════════════════════════════════════════
    # Operator approval (workflow stage 7)
    # ══════════════════════════════════════════════════════════════════════

    async def confirm_finding(
        self, task_id: str, evidence: Optional[Dict[str, Any]] = None
    ) -> Task:
        """Operator confirms a VALIDATING finding (stage 7 ✅)."""
        task = self._task_or_raise(task_id)
        await self.state_machine.transition(task, VulnStatus.CONFIRMED, evidence=evidence or {})
        return task

    async def reject_finding(self, task_id: str, fp_reason: str) -> Task:
        """Operator rejects with a mandatory FP reason (stage 7 ❌)."""
        task = self._task_or_raise(task_id)
        await self.state_machine.transition(
            task, VulnStatus.FALSE_POSITIVE, fp_reason=fp_reason
        )
        return task

    def _task_or_raise(self, task_id: str) -> Task:
        try:
            return self.tasks[task_id]
        except KeyError:
            raise KeyError(f"unknown task_id: {task_id}") from None

    # ══════════════════════════════════════════════════════════════════════
    # Reporting (stage 8) — CONFIRMED/CHAINED only
    # ══════════════════════════════════════════════════════════════════════

    def generate_report(self, task_id: str, platform: Platform) -> ReportResult:
        task = self._task_or_raise(task_id)
        self.report_writer.assert_reportable(task)  # gate

        finding = self.findings.get(task.metadata.get("finding_id", ""), {})
        finding = finding if isinstance(finding, dict) else vars(finding)
        evidence = finding.get("evidence", {}) or {}

        result = self.report_writer.write_report(task, finding, evidence, platform)
        self.reports.append(result)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._publish_report_event(task, result))
        except RuntimeError:
            pass  # no running loop — caller drives events itself
        return result

    async def _publish_report_event(self, task: Task, result: ReportResult) -> None:
        await self.event_bus.publish(
            "reporting",
            OrchestrationEvent(
                event_type="report_generated",
                correlation_id=task.correlation_id,
                source_component="op_admiral",
                payload={
                    "task_id": task.task_id,
                    "platform": result.platform.value,
                    "path": str(result.path),
                },
            ),
        )

    # ══════════════════════════════════════════════════════════════════════
    # Component-wiring hooks (4.6 / 4.7 — harness side of the contract)
    # ══════════════════════════════════════════════════════════════════════

    async def record_tokens(
        self,
        agent_id: str,
        task_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> TokenBudget:
        """POST /api/tokens/record handler (adhd engine, tweak 4.6).

        External components POST their own LLM usage here so the harness
        ledger stays the single source of token/cost truth.
        """
        return await self.token_tracker.record_usage(
            agent_id=agent_id,
            task_id=task_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )

    async def route_llm_request(
        self, task_type: str, prompt: str, agent_id: str = "external"
    ) -> Dict[str, Any]:
        """POST /api/v1/llm/route handler (cbb agent router, tweak 4.7).

        External Python components POST a task_type + prompt; the response is
        the routed LLM text with billing metadata already recorded in the
        TokenTracker by ModelRouter.
        """
        response = await self.model_router.route(
            task_type, prompt, agent_id=agent_id, task_id=f"external_{uuid.uuid4().hex[:8]}"
        )
        return {
            "text": response.text,
            "model": response.model,
            "tier": response.tier.value,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        }

    # ══════════════════════════════════════════════════════════════════════
    # Status / memory write-back
    # ══════════════════════════════════════════════════════════════════════

    def status(self) -> Dict[str, Any]:
        """GET /api/v1/status — the War Room summary payload."""
        wing = self.token_tracker.get_wing_summary(self.scope.program_handle)
        return {
            "hunt": "halted" if self.halted else "active",
            "dry_run": self.dry_run,
            "program": self.scope.program_handle,
            "platform": self.scope.platform.value,
            "active_specialists": len({t.specialist_id for t in self.tasks.values()}),
            "tasks_total": len(self.tasks),
            "scope_violations": len(self.scope_violations),
            "kill_switch": self.halted,
            "findings": self.state_machine.get_status_counts(),
            "noise_dropped": self.noise_filter.get_drop_summary(),
            "budget": {
                "total_tokens": wing["total_tokens"],
                "total_cost_usd": wing["total_cost_usd"],
                "agents": wing["agent_count"],
            },
            "reports_written": len(self.reports),
        }

    async def write_back_memory(self, tasks: Optional[List[Task]] = None) -> List[Dict[str, Any]]:
        """Mempalace write-back: persist terminal findings + FP reasons so
        specialists' check_false_positive() learns across runs.

        Uses the same deferred ChromaBackend path as scripts/ingest_*.py —
        chromadb is only imported for a real (non dry-run) write. Returns a
        list of drawer dicts (what was / would be filed).
        """
        if tasks is None:
            tasks = [t for t in self.tasks.values()
                     if t.status in (VulnStatus.CONFIRMED, VulnStatus.CHAINED,
                                     VulnStatus.FALSE_POSITIVE)]
        drawers: List[Dict[str, Any]] = []
        palace_path = str(Path.home() / ".mempalace")
        backend = None
        col = None
        if not self.dry_run and tasks:
            try:
                from mempalace.backends.chroma import ChromaBackend  # deferred (heavy dep)
                backend = ChromaBackend()
                col = backend.get_collection(palace_path, collection_name="mempalace_findings", create=True)
            except Exception as exc:  # pragma: no cover - palace unavailable
                logger.warning(f"mempalace write-back unavailable: {exc}")

        for task in tasks:
            finding = self.findings.get(task.metadata.get("finding_id", ""), {})
            finding = finding if isinstance(finding, dict) else vars(finding)
            fp_reason = ""
            for record in self.state_machine.get_history(task.task_id):
                if record.to_status == VulnStatus.FALSE_POSITIVE:
                    fp_reason = record.fp_reason
            drawer = {
                "drawer_id": f"findings:{task.wing_id}:{task.task_id}",
                "wing": task.wing_id,
                "room": task.vuln_category.value,
                "content": json.dumps({
                    "task_id": task.task_id,
                    "title": task.metadata.get("title", ""),
                    "endpoint": task.target_endpoint,
                    "status": task.status.value,
                    "fp_reason": fp_reason,
                }, indent=2),
            }
            drawers.append(drawer)
            if self.dry_run:
                logger.info(f"[DRY-RUN] Would file to mempalace: {drawer['drawer_id']}")
                continue
            if col is not None:
                try:
                    col.upsert(ids=[drawer["drawer_id"]],
                               documents=[drawer["content"]],
                               metadatas=[{"wing": drawer["wing"], "room": drawer["room"]}])
                except Exception as exc:  # pragma: no cover
                    logger.warning(f"mempalace upsert failed for {drawer['drawer_id']}: {exc}")

        return drawers


def build_graph(
    config: HarnessConfig,
    scope: TargetScope,
    event_bus: Optional[IEventBus] = None,
) -> Dict[str, Any]:
    """Wire config → compliance → budget → triage → reporting → memory.

    Returns the full graph as a dict — the single construction point used by
    main.py and the Gate-S3 dry-run walk.
    """
    bus = event_bus or InMemoryEventBus()
    tracker = TokenTracker(bus)
    router = ModelRouter(config, tracker)
    admiral = OpAdmiral(
        config=config,
        scope=scope,
        event_bus=bus,
        token_tracker=tracker,
        model_router=router,
        report_writer=ReportWriter(config.workspace_dir),
    )
    return {
        "config": config,
        "event_bus": bus,
        "token_tracker": tracker,
        "model_router": router,
        "scope_gate": admiral.scope_gate,
        "admiral": admiral,
        "report_writer": admiral.report_writer,
    }


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI transport (imported lazily — the core brain works without fastapi)
# ═══════════════════════════════════════════════════════════════════════════

def create_app(admiral: OpAdmiral):
    """Build the REST + WebSocket surface for the admiral (port 8001).

    Endpoints (workflow_overview.md §2 + gap-bridging spec §3.2, request
    bodies matched to the verified control-plane signatures):

      GET  /api/v1/status              — hunt summary
      GET  /api/v1/findings            — task registry
      POST /api/triage/callback        — external finding ingestion
      POST /api/triage/{task_id}/confirm   — operator approval
      POST /api/triage/{task_id}/reject    — operator rejection (FP reason)
      POST /api/tokens/record          — 4.6: external token accounting
      POST /api/v1/llm/route           — 4.7: external LLM routing
      GET  /ws                         — live OrchestrationEvent stream
    """
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "fastapi is required for the admiral API server — activate the "
            "project venv (.venv) or `pip install fastapi`."
        ) from exc

    from pydantic import BaseModel

    app = FastAPI(title="OpAdmiral", version="2.1.2")
    connections: List[WebSocket] = []

    class TriageCallback(BaseModel):
        finding_id: str = ""
        title: str
        description: str
        vuln_category: str
        endpoint: str
        evidence: Dict[str, Any] = {}
        confidence: float = 0.0
        metadata: Dict[str, Any] = {}

    class ConfirmRequest(BaseModel):
        evidence: Dict[str, Any] = {}

    class RejectRequest(BaseModel):
        fp_reason: str

    class TokenRecordRequest(BaseModel):
        agent_id: str
        task_id: str
        input_tokens: int
        output_tokens: int
        model: str

    class LLMRouteRequest(BaseModel):
        task_type: str
        prompt: str
        agent_id: str = "external"

    @app.get("/api/v1/status")
    async def status():
        return admiral.status()

    @app.get("/api/v1/findings")
    async def findings():
        return [
            {
                "task_id": t.task_id,
                "status": t.status.value,
                "specialist": t.specialist_id,
                "category": t.vuln_category.value,
                "endpoint": t.target_endpoint,
                "title": t.metadata.get("title", ""),
            }
            for t in admiral.tasks.values()
        ]

    @app.post("/api/triage/callback")
    async def triage_callback(req: TriageCallback):
        result = await admiral.ingest_finding(req.model_dump())
        return {
            "action": result.action,
            "task_id": result.task_id,
            "status": result.status.value if result.status else None,
            "reason": result.reason,
            "validation": result.validation,
        }

    @app.post("/api/triage/{task_id}/confirm")
    async def confirm(task_id: str, req: ConfirmRequest):
        task = await admiral.confirm_finding(task_id, req.evidence)
        return {"task_id": task_id, "status": task.status.value}

    @app.post("/api/triage/{task_id}/reject")
    async def reject(task_id: str, req: RejectRequest):
        task = await admiral.reject_finding(task_id, req.fp_reason)
        return {"task_id": task_id, "status": task.status.value}

    @app.post("/api/tokens/record")
    async def record_tokens(req: TokenRecordRequest):
        budget = await admiral.record_tokens(
            agent_id=req.agent_id,
            task_id=req.task_id,
            input_tokens=req.input_tokens,
            output_tokens=req.output_tokens,
            model=req.model,
        )
        return {
            "tokens_used": budget.tokens_used,
            "remaining": budget.remaining,
            "cost_usd": budget.cost_usd,
            "exhausted": budget.is_exhausted,
        }

    @app.post("/api/v1/llm/route")
    async def llm_route(req: LLMRouteRequest):
        return await admiral.route_llm_request(
            req.task_type, req.prompt, agent_id=req.agent_id
        )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        connections.append(websocket)

        async def _broadcast(event: OrchestrationEvent) -> None:
            payload = {
                "event_type": event.event_type,
                "correlation_id": event.correlation_id,
                "source_component": event.source_component,
                "payload": event.payload,
            }
            for ws in list(connections):
                try:
                    await ws.send_json(payload)
                except Exception:
                    if ws in connections:
                        connections.remove(ws)

        for topic in ("triage", "budget", "reporting"):
            admiral.event_bus.subscribe(topic, _broadcast)

        try:
            while True:
                # Keep the socket open; inbound messages are ignored.
                await websocket.receive_text()
        except WebSocketDisconnect:
            if websocket in connections:
                connections.remove(websocket)

    return app
