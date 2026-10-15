# tests/test_s2_egress_proxy.py  — S2.3: compliance/egress_proxy.py
"""Replay the shipped 20-line fixture and assert block/allow decisions reproduce.

The fixture ``workspace/default-wing/logs/egress_proxy.jsonl`` was produced by a
single ``*.example.com`` wildcard scope under dry-run. We reconstruct that scope,
run ``EgressProxy.request`` over the same URLs via a duck-typed flow, and assert
the recorded WOULD ALLOW / WOULD DROP outcome is reproduced for every line.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import compliance.egress_proxy as ep
from compliance.egress_proxy import EgressProxy

# The 20-line run-evidence fixture. The canonical copy is committed under
# tests/fixtures/ (workspace/*/logs is gitignored runtime state); if the
# committed fixture is missing, fall back to the live location.
_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = _ROOT / "tests" / "fixtures" / "egress_proxy.jsonl"
if not FIXTURE.exists():
    FIXTURE = _ROOT / "workspace" / "default-wing" / "logs" / "egress_proxy.jsonl"

# Decision string -> expected dry-run HTTP status.
ALLOW = "[DRY-RUN WOULD ALLOW]"
DROP = "[DRY-RUN WOULD DROP]"


@pytest.fixture
def proxy(clean_env, scope_csv, monkeypatch):
    """EgressProxy built from the reconstructed ``*.example.com`` scope (dry-run)."""
    monkeypatch.setenv("HARNESS_SCOPE_FILE", str(scope_csv))
    monkeypatch.setenv("HARNESS_SCOPE_FORMAT", "hackerone_csv")
    monkeypatch.setenv("HARNESS_PROGRAM_HANDLE", "acme")
    return EgressProxy()


def _status_for(proxy, url, make_flow, _fake_response_make):
    flow = make_flow(url)
    proxy.request(flow)
    return flow.response.status


def test_fixture_reproduces_recorded_decisions(proxy, make_flow, fake_response_make):
    assert FIXTURE.exists(), f"fixture missing: {FIXTURE}"
    lines = [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]
    assert len(lines) == 20, f"expected 20 fixture lines, got {len(lines)}"

    mismatches = []
    for entry in lines:
        url = entry["data"]["url"]
        recorded = entry["msg"]
        status = _status_for(proxy, url, make_flow, fake_response_make)
        want = 200 if recorded == ALLOW else 403
        if status != want:
            mismatches.append((url, recorded, status))
    assert not mismatches, f"replay diverged from fixture: {mismatches}"


def test_replay_counts_match_fixture(proxy, make_flow, fake_response_make):
    """Aggregate allow/drop tally must equal the fixture's tally."""
    lines = [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]
    fixture_allow = sum(1 for l in lines if l["msg"] == ALLOW)
    fixture_drop = sum(1 for l in lines if l["msg"] == DROP)

    statuses = [_status_for(proxy, l["data"]["url"], make_flow, fake_response_make) for l in lines]
    replay_allow = sum(1 for s in statuses if s == 200)
    replay_drop = sum(1 for s in statuses if s == 403)

    assert (replay_allow, replay_drop) == (fixture_allow, fixture_drop)
    assert fixture_allow + fixture_drop == 20


@pytest.mark.parametrize(
    "url,want_status",
    [
        ("http://www.example.com/", 200),   # in scope
        ("http://app.example.com/", 200),   # in scope
        ("http://example.com/", 403),       # apex not matched by *.example.com
        ("http://evil.com/", 403),          # out of scope
    ],
)
def test_individual_decisions(proxy, make_flow, fake_response_make, url, want_status):
    assert _status_for(proxy, url, make_flow, fake_response_make) == want_status


def test_osint_header_abuse_dropped_even_if_in_scope(proxy, make_flow, fake_response_make):
    """X-Harness-Traffic: osint on a NON-osint-allowlisted host must be dropped,
    even though www.example.com is in program scope (defense-in-depth)."""
    flow = make_flow("http://www.example.com/", headers={"X-Harness-Traffic": "osint"})
    proxy.request(flow)
    assert flow.response.status == 403


def test_osint_header_on_allowlisted_host_allowed(proxy, make_flow, fake_response_make):
    """osint flag on a real OSINT-allowlisted domain is allowed through."""
    flow = make_flow("https://api.github.com/repos/x", headers={"X-Harness-Traffic": "osint"})
    proxy.request(flow)
    assert flow.response.status == 200


def test_logs_jsonl_is_written(proxy, make_flow, fake_response_make, clean_env):
    """The proxy must append a JSON-lines entry per decision to its log path."""
    flow = make_flow("http://www.example.com/")
    proxy.request(flow)
    log = Path(proxy.log_path)
    assert log.exists()
    entries = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert entries, "no log entry written"
    last = entries[-1]
    assert last["component"] == "egress_proxy"
    assert last["msg"] == ALLOW
    assert last["data"]["host"] == "www.example.com"


def test_passive_cdn_is_classified_passive(proxy, make_flow, fake_response_make):
    """Passive CDN traffic is logged as passive and allowed through.

    The passive-CDN branch in ``request`` logs ``[PASSIVE CDN]`` and returns
    WITHOUT setting a response — i.e. it lets the flow pass to origin rather
    than synthesizing a 200. In the fake flow that means ``flow.response``
    stays None."""
    flow = make_flow("https://fonts.googleapis.com/css2?family=Inter")
    proxy.request(flow)
    assert flow.response is None, "passive CDN must pass through, not be answered"
    last = [json.loads(l) for l in Path(proxy.log_path).read_text().splitlines() if l.strip()][-1]
    assert last["msg"] == "[PASSIVE CDN]"
    assert last["data"]["passive"] is True
