# budget/token_tracker.py
"""Per-agent, per-task token consumption tracker with hard-cap enforcement.

Every LLM call in the harness is metered here. The tracker:
  1. Records input/output tokens + estimated cost per call.
  2. Publishes budget_warning and budget_exhausted events to the EventBus.
  3. Persists usage summaries to mempalace (when available).
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

from core.types import TokenBudget, OrchestrationEvent

logger = logging.getLogger(__name__)

# ── Cost table: USD per 1M tokens (input / output) ──────────────────────
MODEL_COSTS: Dict[str, Dict[str, float]] = {
    # LOCAL tier — $0.00
    "qwen2.5-coder:7b":    {"input": 0.0,    "output": 0.0},
    "qwen2.5-coder:3b":    {"input": 0.0,    "output": 0.0},
    "llama3.1:8b":          {"input": 0.0,    "output": 0.0},
    "mistral:7b":           {"input": 0.0,    "output": 0.0},
    # PAID_FREE tier — $0.00 (Groq free)
    "llama-3.1-70b-versatile": {"input": 0.0, "output": 0.0},
    "llama-3.1-8b-instant":    {"input": 0.0, "output": 0.0},
    "mixtral-8x7b-32768":      {"input": 0.0, "output": 0.0},
    "gemma2-9b-it":            {"input": 0.0, "output": 0.0},
    # PAID_PREMIUM tier
    "gpt-4o":              {"input": 2.50,   "output": 10.00},
    "gpt-4o-mini":         {"input": 0.15,   "output": 0.60},
    "claude-sonnet-4":     {"input": 3.00,   "output": 15.00},
    # Dated alias used by MODEL_ROUTING_TABLE (chain_narrative). S2 fix:
    # without this entry the router's premium task was silently costed at $0.
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku":        {"input": 0.25,   "output": 1.25},
}


@dataclass
class UsageRecord:
    """Single LLM call usage record."""
    agent_id: str
    task_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


class TokenTracker:
    """Tracks token consumption per agent and enforces budget caps.

    Usage:
        tracker = TokenTracker(event_bus=bus)
        tracker.record_usage("sqli_specialist", "task_001", 500, 200, "qwen2.5-coder:7b")
        if tracker.is_budget_exhausted("sqli_specialist"):
            # stop dispatching to this agent
    """

    def __init__(self, event_bus=None, default_budget: Optional[TokenBudget] = None):
        self._budgets: Dict[str, TokenBudget] = {}
        self._history: List[UsageRecord] = []
        self._event_bus = event_bus
        self._default_budget = default_budget or TokenBudget()

    def _ensure_budget(self, agent_id: str) -> TokenBudget:
        """Lazily create a budget for an agent on first use."""
        if agent_id not in self._budgets:
            self._budgets[agent_id] = TokenBudget(
                warning_threshold=self._default_budget.warning_threshold,
                hard_cap=self._default_budget.hard_cap,
            )
        return self._budgets[agent_id]

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate USD cost from the model price table."""
        costs = MODEL_COSTS.get(model, {"input": 0.0, "output": 0.0})
        return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

    async def record_usage(
        self,
        agent_id: str,
        task_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> TokenBudget:
        """Record a single LLM call's token consumption.

        Returns the updated budget for the agent.
        Publishes budget_warning / budget_exhausted events as needed.
        """
        budget = self._ensure_budget(agent_id)
        total_tokens = input_tokens + output_tokens
        cost = self._estimate_cost(model, input_tokens, output_tokens)

        budget.tokens_used += total_tokens
        budget.cost_usd += cost

        record = UsageRecord(
            agent_id=agent_id,
            task_id=task_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self._history.append(record)

        logger.info(
            "token_usage",
            extra={
                "agent_id": agent_id,
                "task_id": task_id,
                "model": model,
                "tokens": total_tokens,
                "cost_usd": cost,
                "budget_remaining": budget.remaining,
            },
        )

        # Emit warning event at threshold
        if (
            self._event_bus
            and budget.tokens_used >= budget.warning_threshold
            and (budget.tokens_used - total_tokens) < budget.warning_threshold
        ):
            await self._event_bus.publish(
                "budget",
                OrchestrationEvent(
                    event_type="budget_warning",
                    correlation_id=task_id,
                    source_component=agent_id,
                    payload={
                        "tokens_used": budget.tokens_used,
                        "hard_cap": budget.hard_cap,
                        "pct": round(budget.tokens_used / budget.hard_cap * 100, 1),
                    },
                ),
            )

        # Emit exhausted event at hard cap
        if (
            self._event_bus
            and budget.is_exhausted
            and (budget.tokens_used - total_tokens) < budget.hard_cap
        ):
            await self._event_bus.publish(
                "budget",
                OrchestrationEvent(
                    event_type="budget_exhausted",
                    correlation_id=task_id,
                    source_component=agent_id,
                    payload={
                        "tokens_used": budget.tokens_used,
                        "hard_cap": budget.hard_cap,
                    },
                ),
            )

        return budget

    def get_agent_budget(self, agent_id: str) -> TokenBudget:
        """Return the current budget state for a specific agent."""
        return self._ensure_budget(agent_id)

    def is_budget_exhausted(self, agent_id: str) -> bool:
        """Quick check: has this agent exceeded its hard cap?"""
        return self._ensure_budget(agent_id).is_exhausted

    def get_wing_summary(self, wing_id: str = "") -> Dict:
        """Aggregate token usage across all agents for a wing/session.

        Returns a dict suitable for JSON serialization and War Room display.
        """
        total_tokens = sum(b.tokens_used for b in self._budgets.values())
        total_cost = sum(b.cost_usd for b in self._budgets.values())
        per_agent = {
            aid: {
                "tokens_used": b.tokens_used,
                "remaining": b.remaining,
                "cost_usd": round(b.cost_usd, 6),
                "exhausted": b.is_exhausted,
            }
            for aid, b in self._budgets.items()
        }
        return {
            "wing_id": wing_id,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "agent_count": len(self._budgets),
            "agents": per_agent,
            "history_len": len(self._history),
        }

    def set_agent_budget(self, agent_id: str, warning: int, hard_cap: int) -> None:
        """Override the default budget for a specific agent."""
        budget = self._ensure_budget(agent_id)
        budget.warning_threshold = warning
        budget.hard_cap = hard_cap
