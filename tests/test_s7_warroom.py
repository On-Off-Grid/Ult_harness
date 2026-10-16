# tests/test_s7_warroom.py
"""S7 — operator war-room dashboard (own UI, same-origin on :8001).

Everything is driven through FastAPI's TestClient against a real ``OpAdmiral``
from ``build_graph`` — no network, no live keys, no npm. This is the Gate-S7
surface:

  S7.1  static serving — ``/``, ``/war_room``, ``/static/{app.js,style.css}``
        render; path-traversal on ``/static/`` is refused (404).
  S7.2  operator controls — ``POST /api/v1/halt`` flips the kill switch and a
        halted admiral skips new dispatch; ``POST /api/v1/resume`` clears it;
        both are idempotent. ``confirm``/``reject`` mutate a VALIDATING finding.
  S7.3  data feeds — ``/api/v1/providers`` mirrors the router snapshot;
        ``/api/v1/status`` carries per-provider budget buckets + the $0.50
        projection + the RESTRICTED-lane scrub re-route counter.

T3MP3ST is a design reference only (AGPL) — nothing of its code is vendored.
"""
from __future__ import annotations

import pytest

from core.config import HarnessConfig
from core.types import (
    Platform, ScopeMatchType, ScopeRule, TargetScope, VulnCategory,
)
from orchestrator.admiral import OpAdmiral, build_graph, create_app


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def scope() -> TargetScope:
    return TargetScope(
        program_handle="warroom-test",
        platform=Platform.HACKERONE,
        in_scope=[ScopeRule(pattern="*.example.com", match_type=ScopeMatchType.WILDCARD)],
        out_of_scope=[ScopeRule(pattern="legacy.example.com", match_type=ScopeMatchType.EXACT)],
    )


@pytest.fixture
def full_config(clean_env, monkeypatch) -> HarnessConfig:
    """A full multi-provider config so the registry/panels are populated.

    Registry is built from these config fields (never os.environ), so the
    OPENAI/ANTHROPIC env (used only for the compat availability signal) is
    stripped for determinism.
    """
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return HarnessConfig(
        dry_run=True,
        workspace_dir=clean_env,
        groq_api_key="G",
        openrouter_api_key="O",
        gemini_api_key="GEM",
        local_heavy_url="http://127.0.0.1:9999/v1",
    )


@pytest.fixture
def graph(scope, full_config):
    return build_graph(full_config, scope)


@pytest.fixture
def admiral(graph) -> OpAdmiral:
    return graph["admiral"]


@pytest.fixture
def client(admiral):
    from fastapi.testclient import TestClient
    return TestClient(create_app(admiral))


def _bountiable_finding(fid="f_s7_1", endpoint="https://app.example.com/login"):
    return {
        "finding_id": fid,
        "title": "SQL injection on login endpoint",
        "description": "The user field reflects a SQL error indicating an injectable query.",
        "vuln_category": "sqli",
        "endpoint": endpoint,
        "evidence": {"request": "POST /login", "response": "500 syntax error near '\"'"},
        "confidence": 0.85,
        "metadata": {"specialist": "sqli_specialist"},
    }


# ── S7.1 — static serving ────────────────────────────────────────────────

class TestStaticServing:
    def test_index_serves_dashboard_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "ULT_HARNESS" in r.text
        assert "war room" in r.text.lower()

    def test_war_room_alias(self, client):
        r = client.get("/war_room")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_static_js_and_css(self, client):
        js = client.get("/static/app.js")
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]
        assert "renderStatus" in js.text
        css = client.get("/static/style.css")
        assert css.status_code == 200
        assert "text/css" in css.headers["content-type"]

    def test_static_path_traversal_refused(self, client):
        # The defense-in-depth guard: only the three known assets are servable.
        assert client.get("/static/../../core/config.py").status_code == 404
        assert client.get("/static/..%2F..%2Fcore%2Fconfig.py").status_code == 404

    def test_static_unknown_file_404(self, client):
        assert client.get("/static/does-not-exist.js").status_code == 404


# ── S7.2 — operator controls ─────────────────────────────────────────────

class TestControls:
    def test_halt_flips_kill_switch_and_status(self, client, admiral, run_async):
        assert admiral.halted is False
        r = client.post("/api/v1/halt")
        assert r.status_code == 200
        assert r.json() == {"halted": True, "changed": True}
        assert admiral.halted is True
        st = client.get("/api/v1/status").json()
        assert st["hunt"] == "halted"
        assert st["kill_switch"] is True

    def test_halt_is_idempotent(self, client, run_async):
        assert client.post("/api/v1/halt").json()["changed"] is True
        second = client.post("/api/v1/halt").json()
        assert second["halted"] is True
        assert second["changed"] is False          # already halted → no-op

    def test_resume_clears_halt(self, client, admiral, run_async):
        client.post("/api/v1/halt")
        assert admiral.halted is True
        r = client.post("/api/v1/resume")
        assert r.json() == {"halted": False, "changed": True}
        assert admiral.halted is False
        # Resume-when-active is a no-op.
        assert client.post("/api/v1/resume").json()["changed"] is False

    def test_halted_admiral_skips_new_dispatch(self, client, admiral, run_async, scope):
        client.post("/api/v1/halt")
        task = admiral.make_task(
            "sqli_specialist", "https://app.example.com/login", VulnCategory.SQLI
        )
        result = run_async(admiral.dispatch(task, specialist=None))
        assert result.status == "skipped_halted"

    def test_confirm_validating_finding(self, client, run_async):
        ing = client.post("/api/triage/callback", json=_bountiable_finding("f_conf")).json()
        assert ing["action"] == "ingested", ing
        task_id = ing["task_id"]
        assert ing["status"] == "validating"
        r = client.post(f"/api/triage/{task_id}/confirm", json={"evidence": {}})
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"

    def test_reject_validating_finding_with_fp_reason(self, client, run_async):
        ing = client.post("/api/triage/callback", json=_bountiable_finding("f_rej")).json()
        assert ing["action"] == "ingested", ing
        task_id = ing["task_id"]
        r = client.post(f"/api/triage/{task_id}/reject",
                        json={"fp_reason": "operator false-positive (war room)"})
        assert r.status_code == 200
        assert r.json()["status"] == "false_positive"

    def test_confirm_unknown_task_404(self, client):
        r = client.post("/api/triage/does-not-exist/confirm", json={"evidence": {}})
        assert r.status_code == 404

    def test_v1_finding_confirm_endpoint(self, client):
        ing = client.post("/api/triage/callback", json=_bountiable_finding("f_v1c")).json()
        assert ing["action"] == "ingested", ing
        r = client.post(f"/api/v1/finding/{ing['task_id']}/confirm", json={"evidence": {}})
        assert r.status_code == 200
        body = r.json()
        assert body["finding_id"] == ing["task_id"]
        assert body["status"] == "confirmed"

    def test_v1_finding_reject_endpoint(self, client):
        ing = client.post("/api/triage/callback", json=_bountiable_finding("f_v1r")).json()
        assert ing["action"] == "ingested", ing
        r = client.post(f"/api/v1/finding/{ing['task_id']}/reject",
                        json={"fp_reason": "operator false-positive (war room)"})
        assert r.status_code == 200
        assert r.json()["status"] == "false_positive"

    def test_v1_finding_unknown_404(self, client):
        assert client.post("/api/v1/finding/nope/confirm",
                           json={"evidence": {}}).status_code == 404
        assert client.post("/api/v1/finding/nope/reject",
                           json={"fp_reason": "x"}).status_code == 404


# ── S7.3 — data feeds ────────────────────────────────────────────────────

class TestFeeds:
    def test_providers_endpoint_mirrors_router_snapshot(self, client, admiral):
        snap = client.get("/api/v1/providers").json()
        assert snap == admiral.model_router.provider_status()
        names = {p["name"] for p in snap}
        # Full config → the local + free-pool providers are all present.
        assert {"ollama", "local_heavy", "groq", "openrouter", "gemini"} <= names
        for p in snap:
            for key in ("name", "tier", "lane", "enabled", "available",
                        "has_key", "models", "rpm", "rpd", "hourly_cost"):
                assert key in p

    def test_degraded_provider_shows_down_badge_and_is_excluded(self, scope, clean_env, monkeypatch):
        """S7.3 gate: a 429-limited / unavailable provider gets the ``down``
        badge in the feed and is dropped from failover candidates."""
        for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        cfg = HarnessConfig(
            dry_run=True, workspace_dir=clean_env,
            groq_api_key="G", openrouter_api_key="O",
        )
        g = build_graph(cfg, scope)
        router = g["model_router"]
        # Simulate groq going 429-limited (the S5 fail-open path).
        groq = next(p for p in router._registry if p.name == "groq")
        groq.available = False

        from fastapi.testclient import TestClient
        snap = TestClient(create_app(g["admiral"])).get("/api/v1/providers").json()
        row = next(p for p in snap if p["name"] == "groq")
        assert row["enabled"] is True        # it IS configured (has a key)
        assert row["available"] is False     # but it's down → "down" badge
        assert row["has_key"] is True
        # A down provider must not be a failover candidate for its tier.
        from budget.providers import providers_for_tier
        names = [p.name for p in providers_for_tier(router._registry, groq.tier)]
        assert "groq" not in names

    def test_status_feed_carries_budget_routing_lanes(self, client, admiral):
        st = client.get("/api/v1/status").json()
        # Budget: per-provider buckets + the $0.50 projection + GPU meter.
        b = st["budget"]
        assert b["budget_line_usd"] == 0.50
        assert isinstance(b["per_provider"], dict)
        assert "gpu_hours" in b
        proj = b["projection"]
        assert proj["budget_line_usd"] == 0.50
        assert proj["projected_cost_usd"] <= 0.50
        assert proj["within_budget"] is True
        # Routing: one snapshot row per registry provider.
        assert isinstance(st["routing"], list) and len(st["routing"]) >= 1
        assert all("lane" in p for p in st["routing"])
        # Lanes: the RESTRICTED re-route counter is wired to the router.
        assert st["lanes"]["scrub_reroutes"] == admiral.model_router.scrub_reroutes

    def test_scrub_counter_wiring(self, client, admiral):
        assert client.get("/api/v1/status").json()["lanes"]["scrub_reroutes"] == 0
        # Simulate the scrub hard-rule firing (the increment itself is proven
        # by the S5 gate tests) and confirm the feed reflects it.
        admiral.model_router._scrub_reroutes = 3
        assert client.get("/api/v1/status").json()["lanes"]["scrub_reroutes"] == 3

    def test_findings_endpoint(self, client, run_async):
        client.post("/api/triage/callback", json=_bountiable_finding("f_list"))
        listing = client.get("/api/v1/findings").json()
        assert isinstance(listing, list) and len(listing) >= 1
        row = listing[0]
        for key in ("task_id", "status", "specialist", "category", "endpoint", "title"):
            assert key in row
