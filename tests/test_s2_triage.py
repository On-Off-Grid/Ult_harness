# tests/test_s2_triage.py  — S2.6: triage/noise_filter.py + state_machine.py
"""Known-FP samples are dropped with the right reason; the state machine only
allows legal transitions and requires an FP reason for FALSE_POSITIVE."""
from __future__ import annotations

import asyncio

import pytest

from core.event_bus import InMemoryEventBus
from core.types import Task, VulnCategory, VulnStatus
from triage.noise_filter import DropReason, Finding, NoiseFilter
from triage.state_machine import (
    InvalidTransitionError,
    TriageStateMachine,
    TRANSITION_EVENTS,
    VALID_TRANSITIONS,
)


# ── NoiseFilter ─────────────────────────────────────────────────────────

def _finding(title, desc, cat="xss"):
    return Finding(
        finding_id="f1", title=title, description=desc,
        vuln_category=cat, endpoint="http://example.com/",
    )


def test_missing_security_headers_dropped():
    res = NoiseFilter().filter(_finding(
        "Missing Security Header", "CSP header is not set on the page"))
    assert res.passed is False
    assert res.reason is DropReason.MISSING_SECURITY_HEADERS


def test_self_xss_dropped():
    res = NoiseFilter().filter(_finding(
        "Self-XSS in console", "attack requires pasting payload into own browser console"))
    assert res.passed is False
    assert res.reason is DropReason.SELF_XSS


def test_rate_limit_absence_dropped():
    res = NoiseFilter().filter(_finding(
        "Rate limit on login",
        "no rate limit on the login endpoint — unlimited attempts possible",
        "rce"))
    assert res.passed is False
    assert res.reason is DropReason.RATE_LIMIT_ABSENCE


def test_real_finding_passes():
    res = NoiseFilter().filter(_finding(
        "SQL Injection in login", "error-based sqli via the username parameter", cat="sqli"))
    assert res.passed is True
    assert res.reason is None


def test_title_match_alone_is_not_enough():
    # Both title AND description keywords must match before dropping.
    res = NoiseFilter().filter(_finding(
        "Missing Security Header", "remote code execution in upload handler", cat="rce"))
    assert res.passed is True


def test_drop_summary_and_total():
    nf = NoiseFilter()
    nf.filter(_finding("Self-XSS", "paste into own browser console"))
    nf.filter(_finding("Missing Security Header", "hsts header absent"))
    assert nf.total_dropped == 2
    summary = nf.get_drop_summary()
    assert summary[DropReason.SELF_XSS.value] == 1
    assert summary[DropReason.MISSING_SECURITY_HEADERS.value] == 1


def test_extra_patterns_can_be_injected():
    nf = NoiseFilter(extra_patterns=[{
        "title_contains": ["totally-unique-noise"],
        "desc_contains": ["synthetic-marker"],
        "reason": DropReason.BEST_PRACTICE,
    }])
    # Keywords are substring-matched against the LOWERCASED title, so the
    # injected keyword must appear verbatim (with hyphens) in the title.
    res = nf.filter(_finding("totally-unique-noise detected", "synthetic-marker present", "business_logic"))
    assert res.passed is False
    assert res.reason is DropReason.BEST_PRACTICE


# ── TriageStateMachine ──────────────────────────────────────────────────

def _task(tid="t1"):
    return Task(
        task_id=tid, wing_id="w", specialist_id="sqli",
        correlation_id="c", target_endpoint="http://x/", vuln_category=VulnCategory.SQLI,
    )


@pytest.mark.parametrize(
    "start,target",
    [
        (VulnStatus.IDENTIFIED, VulnStatus.VALIDATING),
        (VulnStatus.VALIDATING, VulnStatus.CONFIRMED),
        (VulnStatus.VALIDATING, VulnStatus.CHAINED),
        (VulnStatus.CONFIRMED, VulnStatus.CHAINED),
        (VulnStatus.IDENTIFIED, VulnStatus.OUT_OF_SCOPE),
    ],
)
def test_legal_transitions_applied(run_async, start, target):
    sm = TriageStateMachine()
    task = _task()
    task.status = start

    async def scenario():
        await sm.transition(task, target, evidence={"poc": "x"})
        return task.status

    assert run_async(scenario()) is target


def test_illegal_backward_transition_rejected(run_async):
    sm = TriageStateMachine()
    task = _task()

    async def scenario():
        await sm.transition(task, VulnStatus.VALIDATING)
        with pytest.raises(InvalidTransitionError):
            await sm.transition(task, VulnStatus.IDENTIFIED)  # backwards

    run_async(scenario())
    assert task.status is VulnStatus.VALIDATING  # unchanged


def test_direct_jump_identified_to_confirmed_rejected(run_async):
    sm = TriageStateMachine()
    task = _task()

    async def scenario():
        with pytest.raises(InvalidTransitionError):
            await sm.transition(task, VulnStatus.CONFIRMED)  # must go via VALIDATING

    run_async(scenario())


def test_terminal_states_reject_all(run_async):
    for terminal in (VulnStatus.FALSE_POSITIVE, VulnStatus.CHAINED, VulnStatus.OUT_OF_SCOPE):
        assert VALID_TRANSITIONS[terminal] == []
        sm = TriageStateMachine()
        task = _task(tid=f"t_{terminal.value}")
        task.status = terminal

        async def scenario(task=task):
            for target in VulnStatus:
                with pytest.raises(InvalidTransitionError):
                    await sm.transition(task, target)

        run_async(scenario())


def test_fp_requires_reason(run_async):
    sm = TriageStateMachine()
    task = _task(tid="t_fp")

    async def scenario():
        await sm.transition(task, VulnStatus.VALIDATING)
        with pytest.raises(InvalidTransitionError):
            await sm.transition(task, VulnStatus.FALSE_POSITIVE)  # no reason
        await sm.transition(task, VulnStatus.FALSE_POSITIVE, fp_reason="known FP pattern: clickjacking on public page")
        return task.status

    assert run_async(scenario()) is VulnStatus.FALSE_POSITIVE


def test_transition_history_recorded(run_async):
    sm = TriageStateMachine()
    task = _task(tid="t_hist")

    async def scenario():
        await sm.transition(task, VulnStatus.VALIDATING, evidence={"req": "..."})
        await sm.transition(task, VulnStatus.CONFIRMED, evidence={"poc": "..."})

    run_async(scenario())
    hist = sm.get_history("t_hist")
    assert [r.to_status for r in hist] == [VulnStatus.VALIDATING, VulnStatus.CONFIRMED]
    assert hist[0].from_status is VulnStatus.IDENTIFIED
    # Filtered lookup for an unknown task returns empty, not an error.
    assert sm.get_history("nope") == []


def test_events_published_per_target_status(run_async):
    bus = InMemoryEventBus()
    events: list[str] = []

    async def cb(ev):
        events.append(ev.event_type)

    bus.subscribe("triage", cb)
    sm = TriageStateMachine(event_bus=bus)
    task = _task(tid="t_ev")

    async def scenario():
        await sm.transition(task, VulnStatus.VALIDATING)
        await sm.transition(task, VulnStatus.CONFIRMED)

    run_async(scenario())
    assert events == [TRANSITION_EVENTS[VulnStatus.VALIDATING],
                      TRANSITION_EVENTS[VulnStatus.CONFIRMED]]
    assert events == ["validation_started", "finding_confirmed"]


def test_status_counts_reflect_latest_state(run_async):
    sm = TriageStateMachine()

    async def scenario():
        t1 = _task(tid="a")
        t2 = _task(tid="b")
        await sm.transition(t1, VulnStatus.VALIDATING)
        await sm.transition(t1, VulnStatus.CONFIRMED)
        await sm.transition(t2, VulnStatus.VALIDATING)
        await sm.transition(t2, VulnStatus.FALSE_POSITIVE, fp_reason="test")

    run_async(scenario())
    counts = sm.get_status_counts()
    assert counts["confirmed"] == 1
    assert counts["false_positive"] == 1
    assert "validating" not in counts  # superseded
