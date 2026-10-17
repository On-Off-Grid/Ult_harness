# tests/test_s2_header_oob.py  — S2.4: compliance/header_injector.py + oob_engine.py
"""Header injection on a sample request; OOB payload generation + callback log."""
from __future__ import annotations

import asyncio
import json
import os

import pytest

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
