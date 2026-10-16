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
# S5 note: costs are per-MODEL. The same model name can be free or paid
# depending on the PROVIDER (e.g. gpt-4o is $0 on GitHub Models' free tier
# but paid on OpenRouter) — see _estimate_cost() for the provider override.
MODEL_COSTS: Dict[str, Dict[str, float]] = {
    # LOCAL tier — $0.00
    "qwen2.5-coder:7b":    {"input": 0.0,    "output": 0.0},
    "qwen2.5-coder:3b":    {"input": 0.0,    "output": 0.0},
    "llama3.1:8b":          {"input": 0.0,    "output": 0.0},
    "mistral:7b":           {"input": 0.0,    "output": 0.0},
    # S5: LOCAL_LIGHT (Ollama) — the security-tuned primary + fallbacks
    "hf.co/dr-ry/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M": {"input": 0.0, "output": 0.0},
    "qwen2.5:7b":           {"input": 0.0,    "output": 0.0},
    # S5: LOCAL_HEAVY (Qwen3.8-27B on GPU — $0/token; GPU-hours metered separately)
    "qwen3.8-27b":          {"input": 0.0,    "output": 0.0},
    # PAID_FREE tier — $0.00 (Groq free)
    "llama-3.1-70b-versatile": {"input": 0.0, "output": 0.0},
    "llama-3.1-8b-instant":    {"input": 0.0, "output": 0.0},
    "mixtral-8x7b-32768":      {"input": 0.0, "output": 0.0},
    "gemma2-9b-it":            {"input": 0.0, "output": 0.0},
    # S5: Groq 2026 live catalog
    "openai/gpt-oss-120b":     {"input": 0.0, "output": 0.0},
    "qwen/qwen3.8-27b":        {"input": 0.0, "output": 0.0},
    "openai/gpt-oss-20b":      {"input": 0.0, "output": 0.0},
    # S5: OpenRouter :free models ($0 on the free tier)
    "qwen/qwen3.8-27b:free":      {"input": 0.0, "output": 0.0},
    "nvidia/nemotron-3-ultra:free": {"input": 0.0, "output": 0.0},
    "poolside/laguna-s-2.1:free":  {"input": 0.0, "output": 0.0},
    # S5: Mistral (code lane)
    "codestral":              {"input": 0.0, "output": 0.0},
    "mistral-small-latest":   {"input": 0.0, "output": 0.0},
    "ministral-3-14b-latest": {"input": 0.0, "output": 0.0},
    # S5: Gemini (free tier)
    "gemini-2.5-flash":       {"input": 0.0, "output": 0.0},
    "gemini-2.5-flash-lite":  {"input": 0.0, "output": 0.0},
    # S5: GitHub Models free frontier (gpt-4o / claude are $0 on that provider)
    "claude-3-5-sonnet":      {"input": 0.0, "output": 0.0},
    # S5: Cloudflare Workers AI
    "@cf/openai/gpt-oss-120b": {"input": 0.0, "output": 0.0},
    # PAID_PREMIUM tier
    "gpt-4o":              {"input": 2.50,   "output": 10.00},
    "gpt-4o-mini":         {"input": 0.15,   "output": 0.60},
    "claude-sonnet-4":     {"input": 3.00,   "output": 15.00},
    # Dated alias used by MODEL_ROUTING_TABLE (chain_narrative). S2 fix:
    # without this entry the router's premium task was silently costed at $0.
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku":        {"input": 0.25,   "output": 1.25},
    # S5: OpenRouter paid overflow (post top-up)
    "anthropic/claude-sonnet-4": {"input": 3.00, "output": 15.00},
}

# Providers where every model is $0 (free tier / self-hosted). The same model
# name is costed differently per provider — e.g. "gpt-4o" is $0 on github_models
# but paid on openrouter. A model ending in ":free" is always $0 regardless.
FREE_PROVIDERS = frozenset({
    "ollama", "local_heavy", "groq", "mistral", "gemini",
    "github_models", "cloudflare",
})


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
    # S5.4.6: provenance of the call (optional, backward-compatible).
    provider: str = "local"
    lane: Optional[str] = None
    tier: Optional[str] = None


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
        # ── S5.4.6: per-provider usage buckets + GPU-hour accumulator ──────
        self._provider_buckets: Dict[str, Dict[str, float]] = {}
        self._gpu_hours: float = 0.0

    def _ensure_budget(self, agent_id: str) -> TokenBudget:
        """Lazily create a budget for an agent on first use."""
        if agent_id not in self._budgets:
            self._budgets[agent_id] = TokenBudget(
                warning_threshold=self._default_budget.warning_threshold,
                hard_cap=self._default_budget.hard_cap,
            )
        return self._budgets[agent_id]

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int,
                       provider: Optional[str] = None) -> float:
        """Calculate USD cost from the model price table.

        Provider-aware: a ``":free"`` model is always $0, and a model served by a
        free-tier provider (e.g. ``gpt-4o`` on GitHub Models) is costed at $0 even
        though the bare name has paid rates for paid providers (OpenRouter).
        """
        if model.endswith(":free") or provider in FREE_PROVIDERS:
            return 0.0
        costs = MODEL_COSTS.get(model, {"input": 0.0, "output": 0.0})
        return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

    async def record_usage(
        self,
        agent_id: str,
        task_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
        provider: Optional[str] = None,
        lane: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> TokenBudget:
        """Record a single LLM call's token consumption.

        ``provider`` / ``lane`` / ``tier`` are optional S5 additions — when given,
        the call is also bucketed per-provider (S5.4.6). Existing callers that pass
        only the 5 original args behave exactly as before.

        Returns the updated budget for the agent.
        Publishes budget_warning / budget_exhausted events as needed.
        """
        budget = self._ensure_budget(agent_id)
        total_tokens = input_tokens + output_tokens
        cost = self._estimate_cost(model, input_tokens, output_tokens, provider=provider)

        budget.tokens_used += total_tokens
        budget.cost_usd += cost

        # S5.4.6: per-provider bucket (keyed by provider name, else "local").
        bucket_name = provider or "local"
        bucket = self._provider_buckets.setdefault(
            bucket_name, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0}
        )
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["cost_usd"] += cost
        bucket["calls"] += 1

        record = UsageRecord(
            agent_id=agent_id,
            task_id=task_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            provider=bucket_name,
            lane=lane,
            tier=tier,
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
            # ── S5.4.6: per-provider buckets + GPU-hour accumulator ───────
            "per_provider": {
                name: {
                    "input_tokens": b["input_tokens"],
                    "output_tokens": b["output_tokens"],
                    "cost_usd": round(b["cost_usd"], 6),
                    "calls": b["calls"],
                }
                for name, b in self._provider_buckets.items()
            },
            "gpu_hours": round(self._gpu_hours, 4),
            "history_len": len(self._history),
        }

    def record_gpu_hours(self, hours: float, cost_usd: float = 0.0) -> None:
        """Accumulate LOCAL_HEAVY GPU-hour usage (S5.4.6).

        ``cost_usd`` is the actual billed amount (0.0 while on a $0 dev pack).
        """
        if hours > 0:
            self._gpu_hours += hours

    def project_standard_session(self, mix=None) -> Dict:
        """S5.4.6 — project the cost of a STANDARD hunt session (excl. GPU).

        A standard session is a single-target hunt across all 12 phases. The
        default mix reflects the S5 routing table: the vast majority of calls are
        LOCAL / :free / free-frontier ($0). Only a small tail of PREMIUM overflow
        (OpenRouter paid, post top-up) costs anything. The projection MUST stay
        well under the $0.50 budget line (Gate S5.6).

        ``mix`` is an optional list of ``(model, provider, in_tok, out_tok, count)``
        tuples; when omitted the standard session mix above is used.
        """
        standard = [
            # (model, provider, in_tok, out_tok, count)
            ("hf.co/dr-ry/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M", "ollama", 1500, 400, 40),
            ("qwen3.8-27b", "local_heavy", 4000, 900, 6),            # deep reasoning (GPU, $0/token)
            ("openai/gpt-oss-120b", "groq", 1800, 500, 60),
            ("qwen/qwen3.8-27b:free", "openrouter", 1800, 500, 20),
            ("codestral", "mistral", 1500, 400, 6),
            ("gpt-4o", "github_models", 1600, 500, 8),                # free frontier
            ("anthropic/claude-sonnet-4", "openrouter", 2000, 1500, 2),  # paid overflow tail
        ]
        mix = mix if mix is not None else standard
        total = 0.0
        per = []
        for model, provider, in_tok, out_tok, count in mix:
            unit = self._estimate_cost(model, in_tok, out_tok, provider=provider)
            line = unit * count
            total += line
            per.append({"model": model, "provider": provider, "count": count,
                        "cost_usd": round(line, 6)})
        return {
            "projected_cost_usd": round(total, 6),
            "budget_line_usd": 0.50,
            "within_budget": total <= 0.50,
            "gpu_hours_excluded": True,
            "lines": per,
        }

    def set_agent_budget(self, agent_id: str, warning: int, hard_cap: int) -> None:
        """Override the default budget for a specific agent."""
        budget = self._ensure_budget(agent_id)
        budget.warning_threshold = warning
        budget.hard_cap = hard_cap
