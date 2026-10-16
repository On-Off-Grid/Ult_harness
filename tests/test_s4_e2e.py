# tests/test_s4_e2e.py
"""S4 — End-to-end integration gates.

Three sub-gates (plan v3 S4.1–S4.3):

  S4.1  test_s41  — one full dry-run on a legitimate sample target walks the
                    entire control-plane graph (config → scope gate → model
                    route → dispatch → triage → noise filter → report → mempalace
                    write-back) with the report landing on disk.
  S4.2  test_s42  — negative test: an OUT-OF-SCOPE request is blocked by the
                    egress proxy (403) AND logged to egress_proxy.jsonl, while
                    an in-scope request is allowed.
  S4.3  test_s43  — budget test: an Ollama-only config (no Groq / no premium
                    keys) can never route a task to a PAID tier (LOCAL-preferred
                    → LOCAL; PAID-preferred → fail-fast NoBudgetError), and a
                    recorded LOCAL run is zero-cost with a reconciled ledger. A
                    live Ollama round-trip (skipped if Ollama is down) proves the
                    LOCAL path actually serves a request and the ledger stays
                    consistent.

The dry-run path is driven as a subprocess exactly as the operator runs it
(`python main.py init` + `run --dry-run`), matching Gate S3's invocation.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
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
        capture_output=True, text=True, timeout=180,
        cwd=str(REPO_ROOT),
    )


# ── Fixtures ──────────────────────────────────────────────────────────────
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


def _init(scope_file: Path, workspace: Path) -> None:
    proc = _run_cli(
        "init", "--platform", "hackerone", "--program", "acme-corp",
        "--scope-file", str(scope_file), "--researcher", "operator",
        "--workspace", str(workspace),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── S4.1 — full dry-run graph walk ────────────────────────────────────────
class TestS41FullDryRun:
    """Gate S4.1: one full local-model dry-run walks the whole graph and the
    report lands on disk, platform-tailored."""

    def test_full_dry_run_walks_graph_and_writes_report(self, scope_file, workspace):
        _init(scope_file, workspace)
        proc = _run_cli("run", "--program", "acme-corp", "--dry-run",
                        "--workspace", str(workspace))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        out = proc.stdout

        # Every pipeline stage must be reached in order.
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
            assert marker in out, f"missing stage in dry-run output: {marker!r}\n{out}"

        # The final status line must reflect a single confirmed, reported finding.
        status_line = [l for l in out.splitlines() if l.startswith("[dry-run] status")]
        assert status_line, "no status line emitted"
        status = json.loads(status_line[0].split("status      : ", 1)[1])
        assert status["hunt"] == "active"
        assert status["dry_run"] is True
        assert status["platform"] == "hackerone"
        assert status["findings"]["confirmed"] == 1
        assert status["reports_written"] == 1
        assert status["kill_switch"] is False
        # Budget ledger must be present and well-formed. A dry-run makes no real
        # LLM calls (the mocked specialist bypasses router.route()), so cost is
        # zero and the agent count may be 0 — the ledger must be consistent.
        budget = status["budget"]
        assert budget["total_cost_usd"] == 0.0, \
            f"dry-run must record zero cost: {budget}"
        assert budget["total_tokens"] >= 0
        assert budget["agents"] >= 0

        # The confirmed report actually landed on disk, platform-tailored.
        reports = list((workspace / "acme-corp" / "reports").glob("*.md"))
        assert len(reports) == 1, f"expected exactly one report, got {reports}"
        body = reports[0].read_text(encoding="utf-8")
        assert "**Platform:** hackerone" in body
        assert "CWE-89" in body  # SQLi → CWE-89 per the taxonomy


# ── S4.2 — egress proxy blocks + logs out-of-scope traffic ────────────────
class TestS42EgressBlocksAndLogs:
    """Gate S4.2: an out-of-scope request is dropped (403) and logged, an
    in-scope request is allowed (200). This is the negative path that the
    ScopeGate / egress proxy enforces as the network backstop."""

    @pytest.fixture
    def proxy(self, clean_env, scope_csv, monkeypatch):
        monkeypatch.setenv("HARNESS_SCOPE_FILE", str(scope_csv))
        monkeypatch.setenv("HARNESS_SCOPE_FORMAT", "hackerone_csv")
        monkeypatch.setenv("HARNESS_PROGRAM_HANDLE", "acme")
        import compliance.egress_proxy as ep
        return ep.EgressProxy()

    def test_out_of_scope_blocked_and_logged(
        self, proxy, make_flow, fake_response_make,
    ):
        # In-scope → allowed.
        flow_ok = make_flow("http://www.example.com/")
        proxy.request(flow_ok)
        assert flow_ok.response.status == 200

        # Out-of-scope → blocked with a synthetic 403.
        flow_bad = make_flow("http://evil.com/secret")
        proxy.request(flow_bad)
        assert flow_bad.response.status == 403

        # The block must be recorded in the egress log with the drop reason.
        log = Path(proxy.log_path)
        assert log.exists(), "egress proxy did not write its log"
        entries = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
        drop_entries = [
            e for e in entries
            if e["data"]["url"] == "http://evil.com/secret"
        ]
        assert drop_entries, "out-of-scope request was not logged"
        last = drop_entries[-1]
        assert "DROP" in last["msg"], f"expected a DROP decision, got {last['msg']!r}"
        assert last["data"]["host"] == "evil.com"
        assert last["data"]["reason"] in ("dry_run_simulation", "scope_gate_denied")

        # The allow must also be logged.
        allow_entries = [
            e for e in entries if e["data"]["url"] == "http://www.example.com/"
        ]
        assert allow_entries, "in-scope request was not logged"
        assert "ALLOW" in allow_entries[-1]["msg"]


# ── S4.3 — Ollama-only budget: zero paid-tier calls ───────────────────────
def _ollama_is_up() -> bool:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=4
        ) as r:
            data = json.loads(r.read().decode())
        return bool(data.get("models"))
    except Exception:
        return False


@pytest.fixture
def ollama_available():
    return _ollama_is_up()


class TestS43OllamaOnlyBudget:
    """Gate S4.3: with only Ollama available (no Groq, no premium keys), no task
    can ever be routed to a PAID tier.

    The router's fallback chain only goes UP the ladder (LOCAL → PAID_FREE →
    PAID_PREMIUM); it never falls back DOWN to LOCAL for a PAID-preferred task.
    So under an Ollama-only config the invariant the budget gate must hold is:

      * LOCAL-preferred task  → resolves to LOCAL (a $0 model).
      * PAID-preferred task   → resolves to LOCAL only via its explicit LOCAL
        entry, OR raises NoBudgetError (fail-fast) when its preferred tier is
        PAID. It must NEVER silently pick a PAID model.

    This is the "zero paid-tier calls" guarantee: there is no code path that
    spends money when no paid backend is configured.
    """

    def _router(self, clean_env, monkeypatch):
        from core.config import HarnessConfig
        from budget.model_router import ModelRouter
        from budget.token_tracker import TokenTracker
        for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        cfg = HarnessConfig(dry_run=True, groq_api_key=None,
                            workspace_dir=clean_env)
        tracker = TokenTracker()
        router = ModelRouter(cfg, tracker)
        # Force the LOCAL-only scenario regardless of Ollama reachability: the
        # budget gate is about what the router *would* call, decided purely from
        # configured backends (groq=None, no premium).
        router._ollama_available = True
        assert router._groq_available is False
        assert router._premium_keys == {}
        return cfg, tracker, router

    def test_no_task_ever_resolves_to_paid_tier(self, clean_env, monkeypatch):
        """The core S4.3 guarantee: under Ollama-only, no task resolves to a
        PAID tier (it is either LOCAL or fails fast)."""
        from budget.model_router import (
            MODEL_ROUTING_TABLE, ModelTier, NoBudgetError,
        )
        _, _, router = self._router(clean_env, monkeypatch)
        for task in MODEL_ROUTING_TABLE:
            try:
                tier, model = router.resolve_model(task)
            except NoBudgetError:
                # Fail-fast on a PAID-preferred task = safe (no spend).
                continue
            # Any successful resolution MUST be LOCAL.
            assert tier == ModelTier.LOCAL, (
                f"task {task!r} resolved to {tier.value}/{model} "
                f"— a paid tier must be unreachable under Ollama-only"
            )

    def test_local_preferred_resolves_local_and_zero_cost(
        self, clean_env, monkeypatch,
    ):
        """A LOCAL-preferred task routes to a $0 model and the ledger records
        zero cost; per-agent sums reconcile with the total."""
        from budget.model_router import ModelTier
        import asyncio
        _, tracker, router = self._router(clean_env, monkeypatch)

        async def _go():
            tier, model = router.resolve_model("payload_craft")
            assert tier == ModelTier.LOCAL
            await tracker.record_usage(
                agent_id="sqli_specialist", task_id="task_1",
                input_tokens=1000, output_tokens=500, model=model,
            )
            await tracker.record_usage(
                agent_id="sqli_specialist", task_id="task_2",
                input_tokens=200, output_tokens=100, model=model,
            )

        asyncio.run(_go())

        summary = tracker.get_wing_summary()
        assert summary["total_cost_usd"] == 0.0, \
            f"Ollama-only run recorded cost: {summary}"
        # Ledger consistency: per-agent sum == total; history length matches.
        per_agent_sum = sum(a["tokens_used"] for a in summary["agents"].values())
        assert per_agent_sum == summary["total_tokens"] == 1800
        assert summary["history_len"] == 2
        # Only the local model is on record — no paid model ever touched.
        recorded_models = {r.model for r in tracker._history}
        assert len(recorded_models) == 1
        assert next(iter(recorded_models)) == "qwen2.5-coder:7b"

    @pytest.mark.skipif(not _ollama_is_up(), reason="Ollama not reachable")
    def test_live_ollama_roundtrip_records_local_zero_cost(
        self, clean_env, monkeypatch, ollama_available,
    ):
        """Real end-to-end LOCAL call: the router actually serves a prompt from
        Ollama and the ledger records it as LOCAL / zero-cost. Skipped if
        Ollama is down (this is a live-model E2E, not a unit test)."""
        from budget.model_router import ModelTier
        import asyncio

        cfg, tracker, router = self._router(clean_env, monkeypatch)
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=4) as r:
            names = [m["name"] for m in json.loads(r.read().decode()).get("models", [])]
        assert names, "Ollama reports no models"
        live_model = next(
            (m for m in names if "qwen" in m.lower() or "llama" in m.lower()),
            names[0],
        )

        async def _go():
            resp = await router._call_ollama(
                live_model, "Reply with the single word: OK", max_tokens=16
            )
            await tracker.record_usage(
                agent_id="e2e", task_id="live_ollama",
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens, model=resp.model,
            )
            return resp

        resp = asyncio.run(_go())
        assert resp.tier == ModelTier.LOCAL
        assert resp.model == live_model
        assert resp.text.strip(), "Ollama returned empty text"

        summary = tracker.get_wing_summary()
        assert summary["total_cost_usd"] == 0.0
        per_agent_sum = sum(a["tokens_used"] for a in summary["agents"].values())
        assert per_agent_sum == summary["total_tokens"]
        recorded_models = {r.model for r in tracker._history}
        assert recorded_models == {live_model}
