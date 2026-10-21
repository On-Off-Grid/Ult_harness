# tests/test_s2_header_oob.py  — S2.4: compliance/header_injector.py + oob_engine.py
"""Header injection on a sample request; OOB payload generation + callback log."""
from __future__ import annotations

import asyncio
import json
import os

import pytest

import time

import compliance.oob_engine as oe
from compliance.header_injector import HeaderInjector, PlatformProfile
from compliance.oob_engine import OOBEngine, OOBCallback


# ── HeaderInjector ──────────────────────────────────────────────────────

def _profile(**over):
    base = dict(
        platform="hackerone", program_handle="acme", researcher_username="souhail",
        headers={"Authorization": "Bearer TOK"}, rate_limit_rps=1000.0,
        max_concurrent_requests=3, auth={"token": "TOK"},
    )
    base.update(over)
    return PlatformProfile(**base)


def test_get_headers_returns_merged_copy():
    hi = HeaderInjector(_profile())
    h = hi.get_headers()
    assert h["Authorization"] == "Bearer TOK"
    # A defensive copy — mutating the result must not touch the injector.
    h["Authorization"] = "mutated"
    assert hi.get_headers()["Authorization"] == "Bearer TOK"


def test_export_headers_file_writes_flat_key_value(tmp_path):
    hi = HeaderInjector(_profile(headers={"Authorization": "Bearer TOK", "X-Custom": "yes"}))
    out = tmp_path / "out" / "headers.txt"
    hi.export_headers_file(str(out))
    text = out.read_text()
    # Go tools read this as "key: value" lines via HARNESS_HEADERS_FILE.
    assert "Authorization: Bearer TOK" in text
    assert "X-Custom: yes" in text
    # No JSON / no trailing comma — strictly flat.
    assert "{" not in text


def test_rate_limit_context_manager_is_async():
    # rate_limit() is an `async def` that RETURNS an async context manager:
    # `async with await hi.rate_limit(): ...`
    hi = HeaderInjector(_profile(rate_limit_rps=1000.0))

    async def scenario():
        calls = 0
        async with await hi.rate_limit():
            calls += 1
        return calls

    assert asyncio.run(scenario()) == 1


def test_header_injector_from_profile_json_file(tmp_path):
    """`HeaderInjector.from_profile` loads a platform_profile.json (what
    `main.py init` writes) and exposes the merged headers + a UA."""
    profile_path = tmp_path / "platform_profile.json"
    profile_path.write_text(json.dumps({
        "platform": "bugcrowd", "program_handle": "acme", "researcher_username": "souhail",
        "headers": {"X-Bugcrowd-Researcher": "souhail"}, "rate_limit_rps": 2.5,
        "max_concurrent_requests": 4, "auth": {},
    }))
    hi = HeaderInjector.from_profile(str(profile_path))
    h = hi.get_headers()
    assert h["X-Bugcrowd-Researcher"] == "souhail"
    # A User-Agent is auto-injected if the profile didn't provide one.
    assert h["User-Agent"]
    assert "bugcrowd" in h["User-Agent"]
    # Rate-limit config is parsed to the right types.
    assert hi._rate_limit_rps == 2.5
    assert hi._min_interval == pytest.approx(1.0 / 2.5)


# ── OOBEngine (S8.1: real Interactsh lifecycle behind the http seam) ─────

def _mock_interactsh(data: list | None = None, register: dict | None = None):
    """Stand-in for the Interactsh HTTP API behind the engine's ``http`` seam.

    Records every ``(method, url)`` call and serves canned register/polling
    bodies — no network in tests. ``state["data"]`` is mutable, so a poll can
    be fed callbacks after the engine starts."""
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


def test_oob_init_registers_session():
    http = _mock_interactsh()
    eng = OOBEngine(mode="public", base_domain="oast.me", http=http)
    assert eng.session_id is None
    asyncio.run(eng.init())
    assert eng.session_id and len(eng.session_id) > 0
    assert eng.initialized is True
    assert eng.callback_domain == "tok1234567890abc.oast.me"
    assert ("POST", "https://oast.pro/register") in http.calls


def test_oob_generate_payload_shape():
    http = _mock_interactsh()
    eng = OOBEngine(mode="public", base_domain="oast.me", http=http)
    asyncio.run(eng.init())
    payload = eng.generate_payload()
    # Shape: http://<token>.<session>.<domain>/
    assert payload.startswith("http://")
    assert payload.endswith("/")
    host = payload[len("http://"): -1]
    labels = host.split(".")
    # Shape: <token>.<session_id>.<base_domain> where base_domain may itself
    # be multi-label ("oast.me" has 2 labels) -> at least 3 labels total.
    assert host.endswith(".oast.me")
    assert len(labels) >= 3, f"expected token.session.domain, got {host}"
    # Each call yields a unique subdomain token.
    assert eng.generate_payload() != eng.generate_payload()


def test_oob_generate_payload_without_init_still_works():
    # Defensive: generate_payload() self-initializes if init() wasn't awaited.
    http = _mock_interactsh()
    eng = OOBEngine(mode="public", base_domain="oast.fun", http=http)
    payload = eng.generate_payload()
    assert payload.endswith(".oast.fun/")
    assert http.calls == []   # no network attempted on the send side


def test_oob_poll_and_close():
    http = _mock_interactsh()
    eng = OOBEngine(mode="public", base_domain="oast.me", http=http)

    async def scenario():
        await eng.init()
        assert await eng.poll_callbacks() == []   # no interactions yet
        assert ("POST", "https://oast.pro/polling") in http.calls
        await eng.close()
        assert eng._closed is True
        assert ("DELETE", "https://oast.pro/deregister") in http.calls
        # After close, polling yields nothing.
        assert await eng.poll_callbacks() == []

    asyncio.run(scenario())


def test_oob_callback_dataclass_shape():
    cb = OOBCallback(type="dns", timestamp="2026-08-10T00:00:00Z",
                     raw={"host": "abc123.session.oast.me"})
    assert cb.type == "dns"
    assert cb.raw["host"].endswith("oast.me")


# ── OOBEngine: stale-session recovery (public Interactsh keys sessions by
#    User-Agent — a live session under the SAME UA makes the next register
#    answer 400 "correlation-id provided already exists") ──────────────────

def _mock_interactsh_stale(register: list):
    """Interactsh stand-in that returns ONE canned register response per
    register call (register[i] on the i+1-th POST /register), recording the
    User-Agent of every call so UA rotation is observable. No network."""
    calls: list = []
    state = {"n": 0}

    async def http(method, url, headers, payload, timeout=15):
        calls.append((method, url, headers.get("User-Agent", "")))
        if method == "POST" and url.endswith("/register"):
            body = register[min(state["n"], len(register) - 1)]
            state["n"] += 1
            return body
        if method == "DELETE" and url.endswith("/deregister"):
            return 200, {}
        return 404, {}

    http.calls = calls            # type: ignore[attr-defined]
    return http


def test_oob_ua_is_unique_per_instance():
    ok = (200, {"collaborator": "c", "collaborator_token": "t"})
    a = OOBEngine(mode="public", base_domain="oast.me",
                  http=_mock_interactsh_stale(register=[ok]))
    b = OOBEngine(mode="public", base_domain="oast.me",
                  http=_mock_interactsh_stale(register=[ok]))
    assert a._ua != b._ua  # two hunts must never share a session key
    assert a._ua.startswith("ult-harness/3.0/")
    asyncio.run(a.init())
    reg_calls = [c for c in a.http.calls if c[1].endswith("/register")]
    assert reg_calls and reg_calls[0][2] == a._ua  # register carries the UA


def test_oob_stale_session_rotates_ua_and_retries():
    # First register (stale session under this UA) -> 400 "already exists";
    # the engine rotates its UA once and the second register succeeds.
    http = _mock_interactsh_stale(register=[
        (400, {"error": "correlation-id provided already exists"}),
        (200, {"collaborator": "collab2", "collaborator_token": "tok999"}),
    ])
    eng = OOBEngine(mode="public", base_domain="oast.me", http=http)
    ua0 = eng._ua
    asyncio.run(eng.init())
    assert eng.initialized is True
    assert eng.collision_token == "tok999"
    regs = [c for c in http.calls if c[1].endswith("/register")]
    assert len(regs) == 2
    assert regs[0][2] == ua0            # attempt 1 under the original UA
    assert regs[1][2] != ua0            # attempt 2 under the rotated UA
    assert regs[1][2].startswith("ult-harness/3.0/")


def test_oob_stale_session_twice_fails_open():
    # Two stale 400s (e.g. a UA collision in a row) -> give up cleanly:
    # unregistered, payloads still well-formed, nothing raised.
    http = _mock_interactsh_stale(register=[
        (400, {"error": "correlation-id provided already exists"}),
        (400, {"error": "correlation-id provided already exists"}),
    ])
    eng = OOBEngine(mode="public", base_domain="oast.me", http=http)
    asyncio.run(eng.init())
    assert eng.initialized is False
    assert eng.session_id is None
    regs = [c for c in http.calls if c[1].endswith("/register")]
    assert len(regs) == 2               # at most one retry — no hammering
    assert eng.generate_payload().endswith(".oast.me/")  # fail-open payloads


def test_oob_other_register_error_does_not_retry():
    # A non-stale error (e.g. 403 rate limit) must NOT burn the retry:
    # one register call, then fail-open.
    http = _mock_interactsh_stale(register=[
        (403, {"error": "rate limit exceeded"}),
        (200, {"collaborator": "x", "collaborator_token": "y"}),
    ])
    eng = OOBEngine(mode="public", base_domain="oast.me", http=http)
    asyncio.run(eng.init())
    assert eng.initialized is False
    regs = [c for c in http.calls if c[1].endswith("/register")]
    assert len(regs) == 1


# ── OOBEngine: background re-registration (public Interactsh keys sessions
#    by CLIENT IP — a stale session from a previously-killed hunt blocks new
#    registers with 400 until the server-side TTL lapses; the poll loop must
#    retry on a throttle rather than give up at boot) ──────────────────────

def test_maintain_retries_register_when_unregistered():
    # init() hits a persistent stale 400 (an IP-keyed session a killed hunt
    # left behind) and stays unregistered. maintain() — called from the poll
    # loop — must re-attempt a register once the throttle has elapsed, and
    # register successfully the moment the stale slot frees up.
    ok = (200, {"collaborator": "c", "collaborator_token": "tok-late"})
    http = _mock_interactsh_stale(register=[
        (400, {"error": "correlation-id provided already exists"}),
        (400, {"error": "correlation-id provided already exists"}),
        ok, ok, ok,
    ])
    eng = OOBEngine(mode="public", base_domain="oast.me", http=http)
    asyncio.run(eng.init())
    assert eng.initialized is False  # boot was blocked by the stale session

    # Throttle not elapsed yet -> maintain() is a no-op.
    asyncio.run(eng.maintain())
    regs = [c for c in http.calls if c[1].endswith("/register")]
    assert len(regs) == 2            # init's two attempts, no extra from maintain

    # Fast-forward past the throttle -> maintain() retries and registers.
    eng._last_reregister -= oe.REREGISTER_RETRY_SECONDS + 1
    asyncio.run(eng.maintain())
    regs = [c for c in http.calls if c[1].endswith("/register")]
    assert len(regs) == 3
    assert eng.initialized is True
    assert eng.collision_token == "tok-late"


def test_maintain_does_nothing_when_registered_or_disabled():
    # A registered session must not be re-registered (no churn), and a
    # disabled engine must never touch the network.
    http = _mock_interactsh()
    eng = OOBEngine(mode="public", base_domain="oast.me", http=http)
    asyncio.run(eng.init())
    assert eng.initialized is True
    n_before = len([c for c in http.calls if c[1].endswith("/register")])
    eng._last_reregister -= oe.REREGISTER_RETRY_SECONDS + 1  # force-throttle
    asyncio.run(eng.maintain())
    n_after = len([c for c in http.calls if c[1].endswith("/register")])
    assert n_after == n_before       # registered -> no re-register

    dis_http = _mock_interactsh()
    dis = OOBEngine(mode="off", base_domain="oast.me", http=dis_http)
    asyncio.run(dis.maintain())
    assert dis_http.calls == []      # disabled -> no network at all


def test_maintain_throttle_is_configurable():
    # The retry cadence is a module constant (so a hunt / a test can tune it),
    # and it is honored: two maintains within the window issue exactly one
    # extra register.
    orig = oe.REREGISTER_RETRY_SECONDS
    try:
        oe.REREGISTER_RETRY_SECONDS = 3600.0  # very long window
        http = _mock_interactsh_stale(register=[
            (400, {"error": "correlation-id provided already exists"}),
            (400, {"error": "correlation-id provided already exists"}),
            (400, {"error": "correlation-id provided already exists"}),
        ])
        eng = OOBEngine(mode="public", base_domain="oast.me", http=http)
        asyncio.run(eng.init())
        eng._last_reregister -= 3601.0
        asyncio.run(eng.maintain())      # eligible -> one register
        asyncio.run(eng.maintain())      # still within window -> no register
        regs = [c for c in http.calls if c[1].endswith("/register")]
        assert len(regs) == 3
        assert time.monotonic() - eng._last_reregister < 3600.0
    finally:
        oe.REREGISTER_RETRY_SECONDS = orig
