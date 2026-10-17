# tests/test_s8_oob.py
"""S8.1 — OOB correlation (Interactsh): the receive side.

Gate S8.1 (specs/assembly_plan_v3.md):
- A mocked Interactsh (injected ``http`` seam) returns a callback -> the
  admiral's receive side confirms the finding (existing finding enriched, or
  a blind finding synthesized) — no LLM in the loop, no network.
- OOB disabled / dead Interactsh / no engine -> clean no-op: zero network
  calls, ``poll_oob() == 0``, never raises.

Engine-lifecycle detail (register / polling parse / dedup / fail-open) is
covered here; the payload-shape contract lives in tests/test_s2_header_oob.py.
"""
from __future__ import annotations

import pytest

from compliance.oob_engine import OOBEngine, OOBCallback
from core.config import HarnessConfig
from core.event_bus import InMemoryEventBus
from core.types import (
    Platform,
    ScopeMatchType,
    ScopeRule,
    TargetScope,
    VulnStatus,
)
from orchestrator.admiral import OpAdmiral
from triage.noise_filter import Finding


# ── fixtures (mirror tests/test_s3_admiral.py) ────────────────────────────

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


def _mock_interactsh(data: list | None = None, register: dict | None = None):
    """Stand-in for the Interactsh HTTP API behind the engine's ``http`` seam.

    Records every ``(method, url)`` call and serves canned register/polling
    bodies. ``state["data"]`` is mutable, so a poll can be fed callbacks
    after the engine starts."""
    state: dict = {"data": list(data or [])}
    calls: list = []

    async def http(method, url, headers, payload, timeout=15):
        calls.append((method, url))
        if method == "POST" and url.endswith("/register"):
            return 200, register or {
                "collaborator": "deadbeef00",
                "collaborator_token": "tok1234567890abc",
            }
        if method == "POST" and url.endswith("/polling"):
            return 200, {"data": state["data"]}
        if method == "DELETE" and url.endswith("/deregister"):
            return 200, {}
        return 404, {}

    http.calls = calls            # type: ignore[attr-defined]
    http.state = state            # type: ignore[attr-defined]
    return http


def _dns_cb(host: str) -> dict:
    return {"type": "dns", "timestamp": "2026-10-17T00:00:01Z",
            "raw": {"Name": host}}


def _host_of(payload: str) -> str:
    return payload[len("http://"): -1]


# ── Engine lifecycle ───────────────────────────────────────────────────────

class TestEngineLifecycle:
    def test_register_populates_session(self, run_async):
        http = _mock_interactsh()
        eng = OOBEngine(mode="public", base_domain="oast.pro", http=http)
        run_async(eng.init())
        assert eng.initialized is True
        assert eng.callback_domain == "tok1234567890abc.oast.pro"
        assert ("POST", "https://oast.pro/register") in http.calls

    def test_public_mode_uses_oast_pro_api(self, run_async):
        # The config default is the web portal (interactsh.com) — the public
        # HTTP API lives on oast.pro, so public mode must target oast.pro.
        http = _mock_interactsh()
        eng = OOBEngine(mode="public", interactsh_url="https://interactsh.com",
                        http=http)
        run_async(eng.init())
        assert http.calls[0] == ("POST", "https://oast.pro/register")
        assert eng.base_domain == "oast.pro"

    def test_selfhosted_uses_configured_url(self, run_async):
        http = _mock_interactsh()
        eng = OOBEngine(mode="selfhosted",
                        interactsh_url="http://oast.local:9090", http=http)
        run_async(eng.init())
        assert http.calls[0] == ("POST", "http://oast.local:9090/register")
        assert eng.base_domain == "oast.local"

    def test_register_network_error_is_fail_open(self, run_async):
        async def broken_http(method, url, headers, payload, timeout=15):
            raise ConnectionError("boom")

        eng = OOBEngine(mode="public", base_domain="oast.pro", http=broken_http)
        run_async(eng.init())
        assert eng.initialized is False
        # Send side still works (placeholder shape); receive side stays empty.
        p = eng.generate_payload()
        assert p.startswith("http://") and p.endswith("/")
        assert run_async(eng.poll_callbacks()) == []

    def test_register_bad_status_is_fail_open(self, run_async):
        async def http_500(method, url, headers, payload, timeout=15):
            return 500, {"error": "nope"}

        eng = OOBEngine(mode="public", base_domain="oast.pro", http=http_500)
        run_async(eng.init())
        assert eng.initialized is False

    def test_register_missing_fields_is_fail_open(self, run_async):
        http = _mock_interactsh(register={"unexpected": "shape"})
        eng = OOBEngine(mode="public", base_domain="oast.pro", http=http)
        run_async(eng.init())
        assert eng.initialized is False

    def test_disabled_mode_makes_zero_network_calls(self, run_async):
        http = _mock_interactsh()
        eng = OOBEngine(mode="off", base_domain="oast.pro", http=http)
        assert eng.enabled is False
        run_async(eng.init())
        p = eng.generate_payload()
        assert p.startswith("http://")
        assert run_async(eng.poll_callbacks()) == []
        run_async(eng.close())
        assert http.calls == []   # zero network, by definition of disabled

    def test_api_token_sent_as_bearer_when_set(self, run_async):
        seen = {}

        async def http(method, url, headers, payload, timeout=15):
            seen["headers"] = dict(headers)
            if url.endswith("/register"):
                return 200, {"collaborator": "c", "collaborator_token": "t"}
            return 200, {"data": []}

        eng = OOBEngine(mode="public", base_domain="oast.pro",
                        api_token="sekret-token", http=http)
        run_async(eng.init())
        assert seen["headers"].get("Authorization") == "Bearer sekret-token"


# ── Polling: parse + dedup ─────────────────────────────────────────────────

class TestPolling:
    def test_polling_parses_dns_http_smtp(self, run_async):
        data = [
            _dns_cb("a1b2.tok1234567890abc.oast.pro"),
            {"type": "http", "timestamp": "t2",
             "raw": {"Host": "a1b2.tok1234567890abc.oast.pro", "Path": "/"}},
            {"type": "smtp", "timestamp": "t3",
             "raw": {"Sender": "svc@example.com"}},
        ]
        eng = OOBEngine(mode="public", base_domain="oast.pro",
                        http=_mock_interactsh(data=data))
        run_async(eng.init())
        cbs = run_async(eng.poll_callbacks())
        assert [c.type for c in cbs] == ["dns", "http", "smtp"]
        assert cbs[0].callback == "a1b2.tok1234567890abc.oast.pro"
        assert cbs[0].timestamp == "2026-10-17T00:00:01Z"

    def test_polling_tolerates_legacy_dict_of_lists_shape(self, run_async):
        http = _mock_interactsh()
        eng = OOBEngine(mode="public", base_domain="oast.pro", http=http)
        run_async(eng.init())
        # Older API: data = {dns: [...], http: [...]} (records carry no type).
        http.state["data"] = {
            "dns": [{"raw": {"Name": "x.y.oast.pro"}, "timestamp": "t"}],
            "http": [{"raw": {"Host": "x.y.oast.pro"}, "timestamp": "t"}],
        }
        cbs = run_async(eng.poll_callbacks())
        assert [c.type for c in cbs] == ["dns", "http"]

    def test_polling_dedupes_repeated_interactions(self, run_async):
        data = [_dns_cb("a.b.oast.pro"), _dns_cb("a.b.oast.pro")]
        eng = OOBEngine(mode="public", base_domain="oast.pro",
                        http=_mock_interactsh(data=data))
        run_async(eng.init())
        first = run_async(eng.poll_callbacks())
        second = run_async(eng.poll_callbacks())
        assert len(first) == 1
        assert second == []

    def test_poll_before_init_returns_empty_without_network(self, run_async):
        http = _mock_interactsh()
        eng = OOBEngine(mode="public", base_domain="oast.pro", http=http)
        assert run_async(eng.poll_callbacks()) == []
        assert http.calls == []


# ── Match: claim a callback back to its registration ───────────────────────

class TestMatch:
    def _engine_with_callback(self, run_async):
        """Registered engine whose poll returns a callback for its own
        embedded payload."""
        http = _mock_interactsh()
        eng = OOBEngine(mode="public", base_domain="oast.pro", http=http)
        run_async(eng.init())
        payload = eng.generate_payload(context={
            "endpoint": "https://app.example.com/api",
            "category": "ssrf",
        })
        http.state["data"] = [_dns_cb(_host_of(payload))]
        cbs = run_async(eng.poll_callbacks())
        return eng, payload, cbs

    def test_match_claims_registration_once(self, run_async):
        eng, payload, cbs = self._engine_with_callback(run_async)
        reg = eng.match(cbs[0])
        assert reg is not None
        assert reg["url"] == payload
        assert reg["context"]["category"] == "ssrf"
        # Same callback again -> already claimed.
        assert eng.match(cbs[0]) is None

    def test_unrelated_callback_matches_nothing(self, run_async):
        eng, payload, cbs = self._engine_with_callback(run_async)
        other = OOBCallback(type="dns", timestamp="t",
                            raw={"Name": "zzzz.other.oast.pro"},
                            callback="zzzz.other.oast.pro")
        assert eng.match(other) is None


# ── Admiral receive side (the S8.1 gate) ───────────────────────────────────

def _ssrf_finding(payload: str) -> Finding:
    return Finding(
        finding_id="f_ssrf_1",
        title="SSRF on fetch endpoint",
        description="The url parameter is fetched server-side.",
        vuln_category="ssrf",
        endpoint="https://app.example.com/fetch",
        evidence={"payload": "http://127.0.0.1:80", "oob_payload": payload},
        confidence=0.6,
        metadata={"specialist": "ssrf_specialist"},
    )


class TestAdmiralReceiveSide:
    def test_callback_confirms_existing_finding(self, config, scope, run_async):
        eng = OOBEngine(mode="public", base_domain="oast.pro",
                        http=_mock_interactsh())
        adm = OpAdmiral(config=config, scope=scope, oob_engine=eng)
        run_async(eng.init())

        payload = eng.generate_payload(context={
            "endpoint": "https://app.example.com/fetch",
            "category": "ssrf",
            "correlation_id": "corr-1",
        })
        ing = run_async(adm.ingest_finding(_ssrf_finding(payload)))
        assert ing.action == "ingested"

        host = _host_of(payload)
        eng.http.state["data"] = [_dns_cb(host)]

        confirmed = run_async(adm.poll_oob())
        assert confirmed == 1
        f = adm.findings["f_ssrf_1"]
        assert f.evidence["oob_confirmed"] is True
        assert f.evidence["oob_callback"] == f"dns on {host}"
        task = adm.tasks[adm.task_by_finding["f_ssrf_1"]]
        assert task.status == VulnStatus.CONFIRMED
        assert adm.oob_confirmed == 1

    def test_callback_synthesizes_blind_finding(self, config, scope, run_async):
        eng = OOBEngine(mode="public", base_domain="oast.pro",
                        http=_mock_interactsh())
        adm = OpAdmiral(config=config, scope=scope, oob_engine=eng)
        run_async(eng.init())

        # No local finding was produced — the OOB callback is the only signal.
        payload = eng.generate_payload(context={
            "endpoint": "https://app.example.com/fetch",
            "category": "ssrf",
        })
        eng.http.state["data"] = [_dns_cb(_host_of(payload))]

        confirmed = run_async(adm.poll_oob())
        assert confirmed == 1
        new_ids = [fid for fid in adm.findings if fid.startswith("oob_")]
        assert len(new_ids) == 1
        f = adm.findings[new_ids[0]]
        assert f.title == "Blind SSRF confirmed via out-of-band callback"
        assert f.vuln_category == "ssrf"
        assert f.evidence["oob_confirmed"] is True
        assert f.evidence["oob_payload"] == payload
        task = adm.tasks[adm.task_by_finding[new_ids[0]]]
        assert task.status == VulnStatus.CONFIRMED

    def test_unrelated_callback_confirms_nothing(self, config, scope, run_async):
        eng = OOBEngine(mode="public", base_domain="oast.pro",
                        http=_mock_interactsh())
        adm = OpAdmiral(config=config, scope=scope, oob_engine=eng)
        run_async(eng.init())
        eng.generate_payload(context={"endpoint": "https://app.example.com/a",
                                      "category": "ssrf"})
        # A callback for a host this session never embedded.
        eng.http.state["data"] = [_dns_cb("zzzz.other.oast.pro")]
        assert run_async(adm.poll_oob()) == 0
        assert adm.findings == {}
        assert adm.oob_confirmed == 0

    def test_disabled_oob_is_a_clean_noop(self, config, scope, run_async):
        http = _mock_interactsh()
        eng = OOBEngine(mode="off", base_domain="oast.pro", http=http)
        adm = OpAdmiral(config=config, scope=scope, oob_engine=eng)
        assert adm.oob_enabled is False
        assert run_async(adm.poll_oob()) == 0
        assert http.calls == []

    def test_admiral_without_engine_is_a_clean_noop(self, config, scope, run_async):
        adm = OpAdmiral(config=config, scope=scope)
        assert adm.oob_enabled is False
        assert run_async(adm.poll_oob()) == 0

    def test_dead_interactsh_never_breaks_poll(self, config, scope, run_async):
        async def broken(method, url, headers, payload, timeout=15):
            raise ConnectionError("down")

        eng = OOBEngine(mode="public", base_domain="oast.pro", http=broken)
        adm = OpAdmiral(config=config, scope=scope, oob_engine=eng)
        run_async(eng.init())   # fails open (still unregistered)
        assert run_async(adm.poll_oob()) == 0

    def test_poll_oob_publishes_event(self, config, scope, run_async):
        events = []
        bus = InMemoryEventBus()

        async def sink(ev):
            events.append(ev)

        bus.subscribe("triage", sink)
        eng = OOBEngine(mode="public", base_domain="oast.pro",
                        http=_mock_interactsh())
        adm = OpAdmiral(config=config, scope=scope, event_bus=bus, oob_engine=eng)
        run_async(eng.init())
        payload = eng.generate_payload(context={
            "endpoint": "https://app.example.com/x", "category": "rce",
            "correlation_id": "corr-9",
        })
        eng.http.state["data"] = [_dns_cb(_host_of(payload))]
        run_async(adm.poll_oob())
        oob_events = [e for e in events if e.event_type == "oob_confirmed"]
        assert len(oob_events) == 1
        assert oob_events[0].source_component == "oob_correlate"
        assert oob_events[0].correlation_id == "corr-9"

    def test_status_feed_carries_oob(self, config, scope):
        eng = OOBEngine(mode="public", base_domain="oast.pro",
                        http=_mock_interactsh())
        adm = OpAdmiral(config=config, scope=scope, oob_engine=eng)
        st = adm.status()
        assert st["oob"] == {
            "enabled": True,
            "session_registered": False,
            "callbacks_confirmed": 0,
        }


# ── Live-path poll loop (main._oob_poll_loop) ─────────────────────────────

class TestOOBPollLoop:
    def test_loop_polls_repeatedly_and_survives_errors(self, run_async):
        import asyncio

        import main as harness_main

        calls = []

        class _Admiral:
            async def poll_oob(self):
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("transient")   # must not kill the loop
                return 0

        async def scenario():
            task = asyncio.create_task(
                harness_main._oob_poll_loop(_Admiral(), interval=0.01)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return calls

        calls = run_async(scenario())
        # Polled repeatedly, and the first (erroring) iteration didn't stop it.
        assert len(calls) >= 3
