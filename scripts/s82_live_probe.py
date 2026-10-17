"""S8.2 — live empty-content probe (Gate S8.2 item 2). RE-RUNNABLE.

Live-only tool (NOT part of the offline pytest suite): runs ONLY against the
operator's real .env keys. It is the LIVE half of the S8.2 gate; the offline
half is TestS82EmptyContentGuard in tests/test_s5_router.py (mock-tested).

What it proves: a REAL reasoning primary (Groq ``openai/gpt-oss-120b``) served
by ``ModelRouter.route("triage_decision", ...)`` with **NO explicit max_tokens**
returns a NON-EMPTY verdict. That is the exact S5b failure class S8.2 fixes —
a small/None budget let the ~100-token reasoning trace eat the whole allotment
and the API returned a 200 with an empty body. The fix: every stop now asks for
a concrete task-sized budget (TASK_MAX_TOKENS["triage_decision"] = 160 clears
the reasoning budget), and a still-empty 200 is retried once at 3x before being
flagged raw["empty_content"]=True for the agent to decide.

So the probe deliberately does NOT pass max_tokens — the per-task floor must be
what produces the answer. It also reports whether the empty-content guard had
to engage (empty_content flag / second call) on the real model.

Usage:
    python scripts/s82_live_probe.py [output_json_path]
    (default output: /tmp/opencode/s82_live_probe.json, or
     ./s82_live_probe.json when /tmp/opencode is unavailable)

Cost: $0 — a single Groq free-tier triage_decision call (max_tokens=160).
It rotates to the next PAID_FREE stop only if Groq hard-fails, never to a paid
stop for this task, so worst case is still $0.

DNS note: this box's resolver intermittently times out for aiohttp while curl
is unaffected; transient (aiohttp.ClientError / OSError) connection failures
are retried 3x; deterministic HTTP errors (4xx/429) are not — they are the
finding.
"""
import asyncio
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

from dotenv import load_dotenv

load_dotenv(".env", override=False)

import aiohttp

from core.config import HarnessConfig
from core.event_bus import InMemoryEventBus
from budget.token_tracker import TokenTracker
from budget.model_router import ModelRouter, TASK_MAX_TOKENS, G120
from budget.providers import ProviderUnavailable, RateLimited, build_registry


def _default_out_path() -> str:
    if os.path.isdir("/tmp/opencode"):
        return "/tmp/opencode/s82_live_probe.json"
    return os.path.join(os.getcwd(), "s82_live_probe.json")


async def net_retry(coro_fn, attempts=3, delay=1.0):
    """Retry only transient network errors (DNS/TLS/connect); deterministic
    HTTP-level outcomes (RateLimited / ProviderUnavailable / 4xx) propagate."""
    last = None
    for i in range(attempts):
        try:
            return await coro_fn()
        except (aiohttp.ClientError, OSError) as e:
            last = e
            if i < attempts - 1:
                await asyncio.sleep(delay * (i + 1))
    raise last


# The real triage use-case, benign (no secrets — must not trip the scrubber).
TRIAGE_PROMPT = (
    "You are a bug-bounty triage agent. Endpoint /api/login returned a stack "
    "trace on a bad input. Answer only: CONFIRMED or NOT CONFIRMED."
)


async def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else _default_out_path()
    cfg = HarnessConfig.load_from_env()
    reg = build_registry(cfg)
    enabled = [p.name for p in reg if p.enabled]
    floor = TASK_MAX_TOKENS.get("triage_decision")
    print(f"registry enabled: {enabled}")
    print(f"triage_decision per-task budget floor (S8.2): {floor}")
    if not any("groq" in n for n in enabled):
        print("FAIL: Groq is not enabled — the S8.2 live probe needs the real "
              "GROQ_API_KEY from .env")
        return 1

    bus = InMemoryEventBus()
    tracker = TokenTracker(bus)
    router = ModelRouter(cfg, tracker)
    await router.startup_health_check()
    await router.startup_discovery()

    row = {"floor": floor, "provider": None, "tier": None, "model": None,
           "in_tokens": None, "out_tokens": None, "ms": None, "text": None,
           "empty_content": None, "ok": False}
    print("\n=== S8.2 live probe: route('triage_decision', <real Groq>, no "
          "explicit max_tokens) ===")
    try:
        t0 = time.monotonic()
        # Deliberately NO max_tokens kwarg — the S8.2 per-task floor must be
        # what clears the reasoning budget and yields a real verdict.
        resp = await net_retry(lambda: router.route(
            "triage_decision", TRIAGE_PROMPT,
            agent_id="s82-probe", task_id="s82_check",
        ))
        row.update({
            "provider": resp.provider, "tier": resp.tier.value,
            "model": resp.model, "in_tokens": resp.input_tokens,
            "out_tokens": resp.output_tokens,
            "ms": int((time.monotonic() - t0) * 1000),
            "text": (resp.text or "").strip(),
            "empty_content": bool(resp.raw.get("empty_content")),
            "ok": bool((resp.text or "").strip())
                 and not resp.raw.get("empty_content"),
        })
        wing = tracker.get_wing_summary()
        row["per_provider"] = wing.get("per_provider", {})
        print(f"  provider={resp.provider} tier={resp.tier.value} "
              f"model={resp.model} in={resp.input_tokens} out={resp.output_tokens} "
              f"{row['ms']} ms")
        print(f"  verdict: {resp.text[:60]!r}")
        print(f"  empty_content flag: {bool(resp.raw.get('empty_content'))}")
        print(f"  ledger: {json.dumps(row['per_provider'], default=str)}")
    except (RateLimited, ProviderUnavailable) as e:
        row["error"] = f"{type(e).__name__}: {e}"
        print(f"  deterministic provider outcome: {e}")
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
        print(f"  probe FAIL: {e}")

    passed = bool(row["ok"])
    print(f"\nGATE S8.2 (live): {'PASS' if passed else 'FAIL'} — "
          f"{'real Groq triage_decision returned a non-empty, unflagged verdict'
           if passed else 'triage_decision did not yield a non-empty verdict'}")

    out = {"date": time.strftime("%Y-%m-%d"), "enabled": enabled, **row,
           "gate_s82_live": "PASS" if passed else "FAIL",
           "note": "one $0 Groq free-tier call; no explicit max_tokens passed "
                   "(S8.2 per-task floor must clear the reasoning budget)"}
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"details -> {out_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
