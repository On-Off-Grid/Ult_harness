# tests/test_s2_sessions.py  — S2.7: sessions/session_manager.py + agents/dual_session_tester.py
"""Session lifecycle (bootstrap / refresh / shutdown) verified WITHOUT network
by monkeypatching `_login`, plus the 4-session IDOR/BAC matrix tester.

The real `_login` does a live aiohttp POST; here we replace it with a stub so
the test exercises the harness-side logic (context building, header shaping,
refresh loop, task cancellation) deterministically.
"""
from __future__ import annotations

import asyncio

import pytest

from agents.dual_session_tester import DualSessionTester
from core.types import MultiSessionContext
from sessions.session_manager import SessionManager


# ── SessionManager (network-free via _login stub) ───────────────────────

def test_build_auth_headers_shapes_token(monkeypatch):
    hi = SessionManager._build_auth_headers({"token": "TOK123", "token_type": "Bearer"})
    assert hi == {"Authorization": "Bearer TOK123"}
    # No token -> no header at all (never an empty "Bearer ").
    assert SessionManager._build_auth_headers({"token": ""}) == {}
    # Non-Bearer token types are honored.
    assert SessionManager._build_auth_headers({"token": "T", "token_type": "Token"}) == {"Authorization": "Token T"}


def test_bootstrap_with_empty_creds_is_network_free(run_async):
    """No credentials configured -> context built, all persona headers empty,
    unauth empty, and NO login request attempted."""
    sm = SessionManager(auth_config={})
    calls: list[str] = []

    async def _login_stub(persona, creds):
        calls.append(persona)
        assert creds is None
        return {"token": "", "token_type": "Bearer"}

    sm._login = _login_stub  # type: ignore[method-assign]

    async def scenario():
        ctx = await sm.bootstrap_sessions()
        assert sm._refresh_task is not None
        await sm.shutdown()
        return ctx

    ctx = run_async(scenario())
    assert set(calls) == {"user_a", "user_b", "admin"}
    assert ctx.user_a_headers == {}
    assert ctx.user_b_headers == {}
    assert ctx.admin_headers == {}
    assert ctx.unauth_headers == {}


def test_bootstrap_with_creds_injects_bearer_headers(run_async):
    sm = SessionManager(auth_config={"user_a": {"login_url": "http://x/login", "payload": {}}})
    tokens = {"user_a": "TOK_A", "user_b": "", "admin": "TOK_ADMIN"}

    async def _login_stub(persona, creds):
        return {"token": tokens.get(persona, ""), "token_type": "Bearer"}

    sm._login = _login_stub  # type: ignore[method-assign]

    async def scenario():
        ctx = await sm.bootstrap_sessions()
        await sm.shutdown()
        return ctx

    ctx = run_async(scenario())
    assert ctx.user_a_headers == {"Authorization": "Bearer TOK_A"}
    assert ctx.admin_headers == {"Authorization": "Bearer TOK_ADMIN"}
    assert ctx.user_b_headers == {}  # persona without creds stays empty


def test_force_refresh_updates_tokens_in_place(run_async):
    # Long interval: this test drives refreshes manually, so the background
    # loop must not fire and race the assertions.
    sm = SessionManager(auth_config={}, refresh_interval_minutes=25)
    state = {"v": 1}

    async def _login_stub(persona, creds):
        return {"token": f"TOK_v{state['v']}", "token_type": "Bearer"}

    sm._login = _login_stub  # type: ignore[method-assign]

    async def scenario():
        ctx = await sm.bootstrap_sessions()
        first = dict(ctx.user_a_headers)
        state["v"] = 2
        await sm.force_refresh()
        second = dict(ctx.user_a_headers)
        await sm.shutdown()
        return first, second, ctx

    first, second, ctx = run_async(scenario())
    assert first == {"Authorization": "Bearer TOK_v1"}
    assert second == {"Authorization": "Bearer TOK_v2"}
    # force_refresh reuses the same context object (in-place mutation).
    assert ctx.user_a_headers == second


def test_shutdown_cancels_refresh_loop(run_async):
    sm = SessionManager(auth_config={}, refresh_interval_minutes=25)
    # Interval must be stored in seconds (25 min -> 1500 s).
    assert sm.refresh_interval == 1500

    async def _login_stub(persona, creds):
        return {"token": "", "token_type": "Bearer"}

    sm._login = _login_stub  # type: ignore[method-assign]

    async def scenario():
        await sm.bootstrap_sessions()
        task = sm._refresh_task
        assert task is not None and not task.done()
        await sm.shutdown()
        assert task.cancelled() or task.done()

    run_async(scenario())


def test_refresh_loop_reapplies_tokens_without_new_task(run_async):
    """The background loop must re-login and mutate the existing context, and
    a subsequent shutdown must still find the original task (not a second one)."""
    sm = SessionManager(auth_config={}, refresh_interval_minutes=0)  # 0 s -> refresh immediately
    hits: list[str] = []

    async def _login_stub(persona, creds):
        if persona == "user_a":
            hits.append(persona)
        return {"token": f"tok-{len(hits)}", "token_type": "Bearer"}

    sm._login = _login_stub  # type: ignore[method-assign]

    async def scenario():
        ctx = await sm.bootstrap_sessions()
        # Let the 0-second refresh loop fire once.
        await asyncio.sleep(0.05)
        await sm.shutdown()
        return ctx, list(hits)

    ctx, hits = run_async(scenario())
    # Bootstrap (1) + at least one loop iteration.
    assert len(hits) >= 2
    assert ctx.user_a_headers  # token was applied by the loop


# ── DualSessionTester ───────────────────────────────────────────────────

def test_dual_session_tester_instantiates():
    t = DualSessionTester(proxy_url="http://127.0.0.1:8080")
    assert t.proxy_url == "http://127.0.0.1:8080"
    assert DualSessionTester().proxy_url is None


def test_matrix_persona_order_and_header_merge(run_async, monkeypatch):
    """Verify the 4-persona matrix order and that persona headers are merged
    over caller headers — using a stubbed ClientSession (no network)."""
    import aiohttp

    seen_order: list[tuple[str, dict]] = []

    class _FakeResp:
        status = 200

        async def text(self):
            return "ok"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _FakeSession:
        def __init__(self, **kw):
            self.kw = kw

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def request(self, method, url, json=None, headers=None, proxy=None, timeout=None):
            persona = headers.get("X-Persona-Probe")
            seen_order.append((persona, {k: v for k, v in headers.items() if k != "X-Persona-Probe"}))

            class _Ctx:
                async def __aenter__(self):
                    return _FakeResp()

                async def __aexit__(self, *a):
                    return False

            return _Ctx()

    monkeypatch.setattr(aiohttp, "ClientSession", _FakeSession)

    t = DualSessionTester(proxy_url="http://127.0.0.1:8080")
    ctx = MultiSessionContext(
        user_a_headers={"Authorization": "Bearer A", "X-Persona-Probe": "a"},
        user_b_headers={"Authorization": "Bearer B", "X-Persona-Probe": "b"},
        admin_headers={"Authorization": "Bearer Z", "X-Persona-Probe": "z"},
        unauth_headers={"X-Persona-Probe": "none"},
    )

    async def scenario():
        return await t.run_matrix("http://x/api/1", "GET", ctx, headers={"X-Custom": "1"})

    result = run_async(scenario())
    assert [p for p, _ in seen_order] == ["a", "b", "z", "none"]
    # Custom caller header is merged in for every persona; unauth gets NO auth header.
    for _, merged in seen_order:
        assert merged.get("X-Custom") == "1"
    unauth_merged = dict(seen_order[-1][1])
    assert "Authorization" not in unauth_merged
    # Result has an entry per persona.
    assert set(result.keys()) == {"user_a", "user_b", "admin", "unauth"}


def _matrix(user_a=200, user_b=403, admin=200, unauth=401):
    return {
        name: {"status": code, "length": 10, "is_success": 200 <= code < 300}
        for name, code in [("user_a", user_a), ("user_b", user_b),
                           ("admin", admin), ("unauth", unauth)]
    }


def test_analyze_results_clean_access_control():
    """Owner OK, peer denied, unauth denied -> no IDOR, no BAC."""
    is_idor, is_bac, desc = DualSessionTester.analyze_results(_matrix())
    assert is_idor is False and is_bac is False


def test_analyze_results_idor_detected():
    """Peer (User B) successfully accessed the owner's resource -> IDOR."""
    is_idor, is_bac, desc = DualSessionTester.analyze_results(_matrix(user_b=200))
    assert is_idor is True
    assert "IDOR" in desc


def test_analyze_results_bac_detected():
    """Unauthenticated request succeeded -> BAC."""
    is_idor, is_bac, desc = DualSessionTester.analyze_results(_matrix(unauth=200))
    assert is_bac is True
    assert "BAC" in desc


def test_analyze_results_both_idor_and_bac():
    is_idor, is_bac, desc = DualSessionTester.analyze_results(_matrix(user_b=200, unauth=200))
    assert is_idor is True and is_bac is True


def test_analyze_results_inconclusive_when_owner_fails():
    """If the owner can't even access the resource, the matrix is meaningless."""
    is_idor, is_bac, desc = DualSessionTester.analyze_results(
        _matrix(user_a=403, user_b=200, unauth=200))
    assert is_idor is False and is_bac is False
    assert "inconclusive" in desc.lower()
