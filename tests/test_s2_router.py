# tests/test_s2_router.py  — S2.5: budget/model_router.py + token_tracker.py
"""Tier-routing table correctness + fallback chain + ledger/cost math.

NOTE: the plan's S2.5 wording (LOCAL_LIGHT -> LOCAL_HEAVY -> PAID_FREE ->
PAID_PREMIUM) describes the *new* 4-tier structure built in S5. The router
under audit is the existing 3-tier one (LOCAL / PAID_FREE / PAID_PREMIUM);
this file verifies it as-is and the S5 rework is tracked separately.
"""
from __future__ import annotations

import pytest

from core.config import HarnessConfig
from budget.model_router import (
    ModelRouter, ModelTier, LLMResponse,
    MODEL_ROUTING_TABLE, FALLBACK_CHAIN, TIER_DEFAULTS, NoBudgetError,
)
from budget.token_tracker import TokenTracker, MODEL_COSTS
from core.event_bus import InMemoryEventBus
from core.types import TokenBudget


# ── Tier routing table ──────────────────────────────────────────────────

def test_all_table_entries_use_known_tiers():
    valid = {t.value for t in ModelTier}
    for task, entry in MODEL_ROUTING_TABLE.items():
        assert entry["tier"] in valid, f"{task} uses unknown tier {entry['tier']}"
        assert entry["model"], f"{task} has no model"


def test_fallback_chain_terminal_at_premium():
    assert FALLBACK_CHAIN[ModelTier.PAID_PREMIUM] == []
    # Every tier's fallback chain eventually reaches PAID_PREMIUM (a terminal).
    for tier in (ModelTier.LOCAL, ModelTier.PAID_FREE):
        chain = FALLBACK_CHAIN[tier]
        assert chain, f"{tier} has no fallback chain"
        assert ModelTier.PAID_PREMIUM in chain


def _router(ollama=True, groq=True, premium=False, monkeypatch=None):
    cfg = HarnessConfig(groq_api_key="GROQ_TEST" if groq else None)
    if monkeypatch is not None:
        if premium:
            monkeypatch.setenv("OPENAI_API_KEY", "OPENAI_TEST")
            monkeypatch.setenv("ANTHROPIC_API_KEY", "ANTHROPIC_TEST")
        else:
            monkeypatch.delenv("OPENAI_API_KEY", raising=False)
            monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = ModelRouter(cfg)
    r._ollama_available = ollama
    return r


def test_local_task_resolves_local(monkeypatch):
    r = _router(ollama=True, groq=True, monkeypatch=monkeypatch)
    tier, model = r.resolve_model("payload_craft")  # table: LOCAL, qwen2.5-coder:7b
    assert tier is ModelTier.LOCAL
    assert model == "qwen2.5-coder:7b"


def test_paid_free_task_resolves_paid_free(monkeypatch):
    r = _router(ollama=True, groq=True, monkeypatch=monkeypatch)
    tier, model = r.resolve_model("scope_interpret")  # table: PAID_FREE
    assert tier is ModelTier.PAID_FREE
    assert model == "llama-3.1-70b-versatile"


def test_premium_task_resolves_premium(monkeypatch):
    r = _router(ollama=True, groq=True, premium=True, monkeypatch=monkeypatch)
    tier, model = r.resolve_model("chain_narrative")  # table: PAID_PREMIUM, claude-sonnet-4
    assert tier is ModelTier.PAID_PREMIUM
    assert model == "claude-sonnet-4-20250514"


def test_fallback_local_to_paid_free_when_ollama_down(monkeypatch):
    r = _router(ollama=False, groq=True, monkeypatch=monkeypatch)
    # Ollama down + Groq up: LOCAL task must fall back to PAID_FREE default.
    tier, model = r.resolve_model("payload_craft")
    assert tier is ModelTier.PAID_FREE
    assert model == TIER_DEFAULTS[ModelTier.PAID_FREE]


def test_unknown_task_defaults_to_local(monkeypatch):
    r = _router(ollama=True, groq=True, monkeypatch=monkeypatch)
    tier, model = r.resolve_model("totally_bogus_task")
    assert tier is ModelTier.LOCAL
    assert model == TIER_DEFAULTS[ModelTier.LOCAL]


def test_no_backend_raises_no_budget(monkeypatch):
    r = _router(ollama=False, groq=False, premium=False, monkeypatch=monkeypatch)
    with pytest.raises(NoBudgetError):
        r.resolve_model("payload_craft")


def test_startup_health_check_promotes_local_when_ollama_unreachable(monkeypatch):
    """When Ollama is unreachable but Groq is configured, startup must not raise
    and must mark Ollama unavailable (LOCAL tasks will fall back to PAID_FREE)."""
    import asyncio
    cfg = HarnessConfig(groq_api_key="GROQ_TEST", ollama_url="http://127.0.0.1:1")
    r = ModelRouter(cfg)
    asyncio.run(r.startup_health_check())  # port 1 is closed -> unreachable
    assert r._ollama_available is False
    # And a LOCAL task now resolves to the PAID_FREE fallback.
    tier, _ = r.resolve_model("payload_craft")
    assert tier is ModelTier.PAID_FREE


# ── TokenTracker ledger math ────────────────────────────────────────────

def test_cost_math_paid_model():
    t = TokenTracker()
    # claude-sonnet-4: input $3/1M, output $15/1M
    cost = t._estimate_cost("claude-sonnet-4", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(3.0 + 15.0)


def test_every_routed_model_has_a_cost_entry():
    """Invariant: any model in the routing table must exist in MODEL_COSTS,
    otherwise premium usage is silently recorded as $0 (S2 finding — the
    claude-sonnet-4-20250514 alias was missing until it was added)."""
    for task, entry in MODEL_ROUTING_TABLE.items():
        assert entry["model"] in MODEL_COSTS, (
            f"{task} routes to '{entry['model']}' which has no cost entry "
            f"(usage would be counted as $0)"
        )


def test_cost_math_local_model_is_free():
    t = TokenTracker()
    cost = t._estimate_cost("qwen2.5-coder:7b", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.0


def test_unknown_model_costs_zero():
    t = TokenTracker()
    # An unlisted model must be treated as $0 (fail-safe, not a crash).
    assert t._estimate_cost("brand-new-model", 1_000_000, 1_000_000) == 0.0


def test_record_usage_accumulates_tokens_and_cost():
    t = TokenTracker()

    async def scenario():
        await t.record_usage("sqli", "task_1", 1000, 500, "claude-sonnet-4")
        b = t.get_agent_budget("sqli")
        assert b.tokens_used == 1500
        expected_cost = (1000 * 3.0 + 500 * 15.0) / 1_000_000
        assert b.cost_usd == pytest.approx(expected_cost)

    import asyncio
    asyncio.run(scenario())


def test_budget_exhaustion_detection():
    t = TokenTracker(default_budget=TokenBudget(warning_threshold=100, hard_cap=200))

    async def scenario():
        await t.record_usage("x", "t1", 150, 0, "qwen2.5-coder:7b")
        assert not t.is_budget_exhausted("x")
        await t.record_usage("x", "t2", 60, 0, "qwen2.5-coder:7b")  # total 210 > 200
        assert t.is_budget_exhausted("x")

    import asyncio
    asyncio.run(scenario())


def test_budget_warning_and_exhausted_events_published(run_async):
    """Crossing the warning threshold publishes budget_warning; crossing the
    hard cap publishes budget_exhausted — and only the crossing call does."""
    bus = InMemoryEventBus()
    events: list[str] = []

    async def cb(ev):
        events.append(ev.event_type)

    bus.subscribe("budget", cb)
    t = TokenTracker(event_bus=bus, default_budget=TokenBudget(warning_threshold=100, hard_cap=150))

    async def scenario():
        await t.record_usage("x", "t1", 120, 0, "qwen2.5-coder:7b")  # crosses 100 warning, < 150 cap
        await t.record_usage("x", "t2", 50, 0, "qwen2.5-coder:7b")   # total 170 > 150 cap
        return list(events)

    got = run_async(scenario())
    assert "budget_warning" in got
    assert "budget_exhausted" in got
    # Exactly one of each — the non-crossing second warning must not re-fire.
    assert got.count("budget_warning") == 1
    assert got.count("budget_exhausted") == 1


def test_wing_summary_aggregates():
    t = TokenTracker()

    async def scenario():
        await t.record_usage("a", "t", 1000, 100, "qwen2.5-coder:7b")
        await t.record_usage("b", "t", 500, 50, "llama3.1:8b")
        return t.get_wing_summary("wing-1")

    import asyncio
    s = asyncio.run(scenario())
    assert s["wing_id"] == "wing-1"
    assert s["agent_count"] == 2
    assert s["total_tokens"] == 1000 + 100 + 500 + 50
    assert s["agents"]["a"]["tokens_used"] == 1100
    assert s["agents"]["b"]["tokens_used"] == 550
    assert s["total_cost_usd"] == 0.0  # both local/free models
    assert s["history_len"] == 2


def test_set_agent_budget_overrides_default():
    t = TokenTracker(default_budget=TokenBudget(warning_threshold=100, hard_cap=200))
    t.set_agent_budget("vip", warning=10, hard_cap=20)
    b = t.get_agent_budget("vip")
    assert b.warning_threshold == 10
    assert b.hard_cap == 20
    # Other agents keep the default.
    assert t.get_agent_budget("other").hard_cap == 200
