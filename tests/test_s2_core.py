# tests/test_s2_core.py  — S2.1: core/ (types, config, event_bus)
"""Import + instantiate + publish/subscribe round-trip."""
from __future__ import annotations

import pytest

from core.types import (
    Platform, ScopeMatchType, VulnCategory, VulnStatus,
    ScopeRule, TargetScope, PlatformHeaders, MultiSessionContext,
    TokenBudget, Task, OrchestrationEvent,
)
from core.config import HarnessConfig
from core.event_bus import InMemoryEventBus, IEventBus


def test_types_import_and_instantiate():
    rule = ScopeRule(pattern="*.example.com", match_type=ScopeMatchType.WILDCARD, description="web")
    scope = TargetScope(
        program_handle="acme", platform=Platform.HACKERONE,
        in_scope=[rule], out_of_scope=[], rate_limit_rps=5.0, max_concurrent=2,
    )
    assert scope.in_scope[0].match_type is ScopeMatchType.WILDCARD
    assert scope.program_handle == "acme"

    headers = PlatformHeaders.for_platform(Platform.BUGCROWD, "souhail")
    assert "X-Bugcrowd-Researcher" in headers.headers
    assert "souhail" in headers.user_agent

    ctx = MultiSessionContext()
    assert ctx.unauth_headers == {}

    task = Task("t1", "w", "sqli", "c", "http://x/", VulnCategory.SQLI)
    assert task.status is VulnStatus.IDENTIFIED  # default

    ev = OrchestrationEvent("finding_confirmed", "c", "sqli")
    assert ev.event_type == "finding_confirmed"


def test_token_budget_math():
    b = TokenBudget(warning_threshold=50_000, hard_cap=100_000, tokens_used=70_000)
    assert b.remaining == 30_000
    assert not b.is_exhausted
    b.tokens_used = 100_000
    assert b.is_exhausted
    assert b.remaining == 0


def test_config_load_from_env_isolated(monkeypatch):
    monkeypatch.setenv("HARNESS_DRY_RUN", "true")
    monkeypatch.setenv("EGRESS_PROXY_PORT", "9999")
    monkeypatch.setenv("HARNESS_API_PORT", "8050")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = HarnessConfig.load_from_env()
    assert cfg.dry_run is True
    assert cfg.egress_proxy_port == 9999
    assert cfg.api_port == 8050
    assert cfg.groq_api_key is None


def test_event_bus_roundtrip(run_async):
    async def scenario():
        bus = InMemoryEventBus()
        received: list[str] = []

        async def cb(ev: OrchestrationEvent):
            received.append(ev.event_type)

        sub_id = bus.subscribe("findings", cb)
        await bus.publish(
            "findings",
            OrchestrationEvent("finding_confirmed", "c1", "sqli"),
        )
        assert received == ["finding_confirmed"]

        # Unsubscribe, then publish again — nothing new should arrive.
        bus.unsubscribe(sub_id)
        await bus.publish("findings", OrchestrationEvent("noise", "c2", "sqli"))
        assert received == ["finding_confirmed"]

        # A different topic with no subscribers must not raise.
        await bus.publish("unknown_topic", OrchestrationEvent("x", "c3", "sqli"))
        return received

    assert run_async(scenario()) == ["finding_confirmed"]


def test_i_event_bus_is_abstract_interface():
    # The interface declares the three required methods.
    for name in ("publish", "subscribe", "unsubscribe"):
        assert callable(getattr(IEventBus, name))
    assert issubclass(InMemoryEventBus, IEventBus)
