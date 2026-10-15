# tests/test_s3_admiral.py
"""S3.1 — OpAdmiral core: dispatch, scope kill switch, triage pipeline,
dual-session validation, approval gate, component-wiring hooks (4.6/4.7),
status + mempalace write-back.

All tests drive the pure-Python core with mocked component calls (no network,
no LLM, no chromadb) — the same path the Gate-S3 dry-run uses.
"""
from __future__ import annotations

import json

import pytest

from budget.model_router import LLMResponse, ModelTier, NoBudgetError
from core.config import HarnessConfig
from core.types import (
    MultiSessionContext,
    Platform,
    ScopeMatchType,
    ScopeRule,
    TargetScope,
    VulnCategory,
    VulnStatus,
)
from orchestrator.admiral import OpAdmiral, build_graph
from reporting.writers import ReportGateError
from triage.noise_filter import Finding
from triage.state_machine import InvalidTransitionError


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def scope() -> TargetScope:
    return TargetScope(
        program_handle="test-program",
        platform=Platform.HACKERONE,
        in_scope=[ScopeRule(pattern="*.example.com", match_type=ScopeMatchType.WILDCARD)],
        out_of_scope=[ScopeRule(pattern="legacy.example.com", match_type=ScopeMatchType.EXACT)],
    )


@pytest.fixture
def config(clean_env) -> HarnessConfig:
    return HarnessConfig(dry_run=True, workspace_dir=clean_env)


@pytest.fixture
def graph(config, scope):
    return build_graph(config, scope)


@pytest.fixture
def admiral(graph) -> OpAdmiral:
    return graph["admiral"]


class _MockSpecialist:
    """Mocked component call: returns canned findings, records the target."""

    def __init__(self, findings):
        self._findings = findings
        self.calls = []

    @property
    def category(self) -> VulnCategory:
        return VulnCategory.SQLI

    async def scan(self, target, scope, session_ctx, correlation_id):
        self.calls.append(target)
        return list(self._findings)


def _sql_finding(endpoint="https://app.example.com/login") -> Finding:
    return Finding(
        finding_id="f_sql_1",
        title="SQL injection on login endpoint",
        description="The user field reflects a SQL error indicating injectable query.",
        vuln_category="sqli",
        endpoint=endpoint,
        evidence={"request": "POST /login", "response": "500 syntax error near '\"'"},
        confidence=0.8,
        metadata={"specialist": "sqli_specialist"},
    )


def _noise_finding(endpoint="https://app.example.com/login") -> Finding:
    return Finding(
        finding_id="f_noise_1",
        title="Missing security header on login",
        description="CSP and HSTS headers are absent.",
        vuln_category="xss",
        endpoint=endpoint,
    )


def _idor_finding(matrix, endpoint="https://app.example.com/account/42") -> Finding:
    return Finding(
        finding_id="f_idor_1",
        title="IDOR on account resource",
        description="User B accessed User A's account via sequential object id.",
        vuln_category="idor",
        endpoint=endpoint,
        evidence={"matrix": matrix},
        confidence=0.7,
        metadata={"specialist": "idor_specialist"},
    )


# ── Dispatch ──────────────────────────────────────────────────────────────

class TestDispatch:
    def test_in_scope_dispatch_runs_mocked_specialist(self, admiral, run_async):
        mock = _MockSpecialist([_sql_finding()])
        task = admiral.make_task("sqli_specialist", "https://app.example.com/login",
                                 VulnCategory.SQLI)
        result = run_async(admiral.dispatch(task, specialist=mock,
                                            session_ctx=MultiSessionContext()))
        assert result.status == "ok"
        assert len(result.findings) == 1
        assert mock.calls == ["https://app.example.com/login"]
        assert task.status == VulnStatus.IDENTIFIED  # dispatch alone does not triage

    def test_dispatch_without_specialist_is_dry_run(self, admiral, run_async):
        task = admiral.make_task("sqli_specialist", "https://app.example.com/login",
                                 VulnCategory.SQLI)
        result = run_async(admiral.dispatch(task))
        assert result.status == "ok"
        assert result.findings == []
        assert "dry-run" in result.detail

    def test_out_of_scope_target_rejected(self, admiral, run_async):
        task = admiral.make_task("sqli_specialist", "https://evil.com/login",
                                 VulnCategory.SQLI)
        result = run_async(admiral.dispatch(task))
        assert result.status == "skipped_out_of_scope"
        assert task.status == VulnStatus.OUT_OF_SCOPE
        assert admiral.scope_violations == ["https://evil.com/login"]

    def test_explicit_out_of_scope_rule_rejected(self, admiral, run_async):
        task = admiral.make_task("sqli_specialist", "https://legacy.example.com/x",
                                 VulnCategory.SQLI)
        result = run_async(admiral.dispatch(task))
        assert result.status == "skipped_out_of_scope"

    def test_kill_switch_halts_hunt_after_threshold(self, admiral, run_async):
        for i in range(3):
            task = admiral.make_task(
                "sqli_specialist", f"https://evil{i}.com/x", VulnCategory.SQLI)
            result = run_async(admiral.dispatch(task))
            assert result.status == "skipped_out_of_scope"
        assert admiral.halted is True

        task = admiral.make_task("sqli_specialist", "https://app.example.com/ok",
                                 VulnCategory.SQLI)
        mock = _MockSpecialist([_sql_finding()])
        result = run_async(admiral.dispatch(task, specialist=mock))
        assert result.status == "skipped_halted"
        assert mock.calls == []  # nothing may be scanned once halted

    def test_specialist_crash_is_isolated(self, admiral, run_async):
        class _Boom:
            async def scan(self, target, scope, session_ctx, correlation_id):
                raise RuntimeError("boom")

        task = admiral.make_task("sqli_specialist", "https://app.example.com/login",
                                 VulnCategory.SQLI)
        result = run_async(admiral.dispatch(task, specialist=_Boom()))
        assert result.status == "error"
        assert "boom" in result.detail
        assert admiral.halted is False  # one crash does not halt the hunt


# ── Triage pipeline ───────────────────────────────────────────────────────

class TestIngest:
    def test_full_pipeline_ingests_to_validating(self, admiral, run_async):
        result = run_async(admiral.ingest_finding(_sql_finding()))
        assert result.action == "ingested"
        assert result.status == VulnStatus.VALIDATING
        task = admiral.tasks[result.task_id]
        assert task.vuln_category == VulnCategory.SQLI
        assert admiral.task_by_finding["f_sql_1"] == result.task_id

    def test_ingest_accepts_raw_dict(self, admiral, run_async):
        result = run_async(admiral.ingest_finding({
            "finding_id": "f_dict_1",
            "title": "SQL injection on login endpoint",
            "description": "SQL error in response.",
            "vuln_category": "sqli",
            "endpoint": "https://app.example.com/login",
            "evidence": {"poc": "1' OR '1'='1"},
        }))
        assert result.action == "ingested"
        assert result.status == VulnStatus.VALIDATING

    def test_noise_pattern_dropped_before_triage(self, admiral, run_async):
        result = run_async(admiral.ingest_finding(_noise_finding()))
        assert result.action == "dropped_noise"
        assert result.reason == "missing_security_headers"
        assert result.task_id is None
        assert admiral.tasks == {}  # nothing entered the state machine

    def test_out_of_scope_finding_dropped(self, admiral, run_async):
        result = run_async(admiral.ingest_finding(_sql_finding(endpoint="https://evil.com/x")))
        assert result.action == "dropped_out_of_scope"
        assert admiral.tasks == {}


# ── Dual-session validation hook ──────────────────────────────────────────

_IDOR_MATRIX = {
    "user_a": {"status": 200, "is_success": True, "length": 120},
    "user_b": {"status": 200, "is_success": True, "length": 120},
    "admin":  {"status": 200, "is_success": True, "length": 120},
    "unauth": {"status": 403, "is_success": False, "length": 10},
}
_CLEAN_MATRIX = {
    "user_a": {"status": 200, "is_success": True, "length": 120},
    "user_b": {"status": 403, "is_success": False, "length": 10},
    "admin":  {"status": 200, "is_success": True, "length": 120},
    "unauth": {"status": 403, "is_success": False, "length": 10},
}


class TestDualSessionHook:
    def test_idor_matrix_produces_idor_verdict(self, admiral, run_async):
        result = run_async(admiral.ingest_finding(_idor_finding(_IDOR_MATRIX)))
        assert result.action == "ingested"
        assert result.validation.startswith("IDOR:")
        task = admiral.tasks[result.task_id]
        assert task.metadata["dual_session"].startswith("IDOR:")

    def test_clean_matrix_produces_no_bug_verdict(self, admiral, run_async):
        result = run_async(admiral.ingest_finding(_idor_finding(_CLEAN_MATRIX)))
        assert result.validation.startswith("NO_BUG:")

    def test_non_idor_category_skips_hook(self, admiral, run_async):
        f = _sql_finding()
        f.evidence = {"matrix": _IDOR_MATRIX}  # matrix present but category is sqli
        result = run_async(admiral.ingest_finding(f))
        assert result.validation == ""


# ── Operator approval + report gate ───────────────────────────────────────

class TestApprovalAndReporting:
    def _validated(self, admiral, run_async) -> str:
        result = run_async(admiral.ingest_finding(_sql_finding()))
        return result.task_id

    def test_report_refused_before_confirmation(self, admiral, run_async, scope):
        task_id = self._validated(admiral, run_async)
        with pytest.raises(ReportGateError):
            admiral.generate_report(task_id, scope.platform)
        assert admiral.reports == []

    def test_confirm_then_report_writes_file(self, admiral, run_async, scope, config):
        task_id = self._validated(admiral, run_async)
        run_async(admiral.confirm_finding(task_id, evidence={"poc": "x' OR 1=1--"}))
        report = admiral.generate_report(task_id, scope.platform)
        assert report.path.exists()
        assert report.path.name.endswith("_sqli.md")
        assert report.cwe == 89
        body = report.path.read_text(encoding="utf-8")
        assert "CWE-89" in body
        assert "CONFIRMED" in body
        assert admiral.reports == [report]

    def test_reject_requires_fp_reason(self, admiral, run_async):
        task_id = self._validated(admiral, run_async)
        with pytest.raises(InvalidTransitionError):
            run_async(admiral.reject_finding(task_id, fp_reason=""))
        run_async(admiral.reject_finding(task_id, fp_reason="known to program"))
        assert admiral.tasks[task_id].status == VulnStatus.FALSE_POSITIVE

    def test_confirm_refuses_unknown_task(self, admiral, run_async):
        with pytest.raises(KeyError):
            run_async(admiral.confirm_finding("nope"))


# ── Component-wiring hooks (4.6 / 4.7) ────────────────────────────────────

class TestComponentWiringHooks:
    def test_record_tokens_updates_ledger(self, admiral, run_async):
        budget = run_async(admiral.record_tokens(
            agent_id="adhd_engine", task_id="t1",
            input_tokens=100, output_tokens=50, model="llama-3.1-70b-versatile",
        ))
        assert budget.tokens_used == 150
        assert budget.cost_usd >= 0.0
        summary = admiral.token_tracker.get_wing_summary()
        assert summary["total_tokens"] == 150

    def test_route_llm_request_delegates_to_router(self, admiral, run_async, monkeypatch):
        async def _fake_ollama(model, prompt, **kwargs):
            return LLMResponse(text="payload-idea", model=model,
                               tier=ModelTier.LOCAL,
                               input_tokens=10, output_tokens=20)

        monkeypatch.setattr(admiral.model_router, "_call_ollama", _fake_ollama)
        out = run_async(admiral.route_llm_request("payload_craft", "Give me a payload"))
        assert out["text"] == "payload-idea"
        assert out["tier"] == "LOCAL"
        assert out["input_tokens"] == 10
        # billing flowed into the tracker via ModelRouter
        assert admiral.token_tracker.get_wing_summary()["total_tokens"] == 30

    def test_route_llm_request_propagates_no_budget(self, admiral, run_async, monkeypatch):
        admiral.model_router._ollama_available = False
        admiral.model_router._groq_available = False
        admiral.model_router._premium_keys = {}
        with pytest.raises(NoBudgetError):
            run_async(admiral.route_llm_request("payload_craft", "x"))


# ── Status + memory write-back ────────────────────────────────────────────

class TestStatusAndMemory:
    def test_status_payload_shape(self, admiral, run_async):
        run_async(admiral.ingest_finding(_sql_finding()))
        status = admiral.status()
        assert status["hunt"] == "active"
        assert status["dry_run"] is True
        assert status["program"] == "test-program"
        assert status["platform"] == "hackerone"
        assert status["tasks_total"] == 1
        assert status["findings"]["validating"] == 1
        assert status["scope_violations"] == 0
        assert status["kill_switch"] is False

    def test_write_back_memory_dry_run_files_nothing(self, admiral, run_async, monkeypatch):
        result = run_async(admiral.ingest_finding(_sql_finding()))
        run_async(admiral.confirm_finding(result.task_id))

        calls = []

        def _forbidden(*a, **k):
            calls.append(a)
            raise AssertionError("chromadb must not be touched in dry-run")

        # Block the deferred import: mempalace/chromadb must stay unloaded.
        import builtins
        real_import = builtins.__import__

        def _guarded_import(name, *a, **k):
            if name.startswith("mempalace") or name.startswith("chromadb"):
                raise ImportError("blocked in dry-run test")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _guarded_import)
        drawers = run_async(admiral.write_back_memory())
        assert calls == []
        assert len(drawers) == 1
        drawer = drawers[0]
        assert drawer["wing"] == "test-program"
        assert drawer["room"] == "sqli"
        payload = json.loads(drawer["content"])
        assert payload["status"] == "confirmed"

    def test_write_back_memory_includes_fp_reason(self, admiral, run_async):
        result = run_async(admiral.ingest_finding(_sql_finding()))
        run_async(admiral.reject_finding(result.task_id, fp_reason="informational only"))
        drawers = run_async(admiral.write_back_memory())
        assert len(drawers) == 1
        payload = json.loads(drawers[0]["content"])
        assert payload["status"] == "false_positive"
        assert payload["fp_reason"] == "informational only"
