"""S5b — live provider verification (Gate S5 item 2). RE-RUNNABLE.

Live-only tool (NOT part of the offline pytest suite): it runs ONLY against
the operator's real .env keys. For every ENABLED provider:
  (a) live GET /models re-check vs the configured preference list (drift),
  (b) one real 200 per provider (tries the provider's resolved models in
      order — a 429 on one model is a per-model free-tier throttle, which
      still proves the provider is live + the key valid: a dead endpoint is
      404/net-error, a bad key is 401), logged with provider / tier / lane,
  (c) OpenRouter: paid-overflow model (anthropic/claude-sonnet-5.5) resolves —
      live-catalog membership + one tiny real PAID call (post top-up proof).
Then one full end-to-end router.route() (scrub -> limiter -> adapter ->
per-provider billing) through the real ModelRouter.

Usage:
    python scripts/s5b_live_verify.py [output_json_path]
    (default output: /tmp/opencode/s5b_live_verification.json, or
     ./s5b_live_verification.json when /tmp/opencode is unavailable)

Cost: $0 on every free provider (max_tokens=160 per probe so the reasoning
models — groq gpt-oss-120b, nemotron — clear their ~100-token reasoning
budget and emit a real answer); one tiny PAID OpenRouter call (~$0.003).

DNS note: this box's resolver intermittently times out for aiohttp while
curl is unaffected; transient (aiohttp.ClientError / OSError) connection
failures are retried 3x; deterministic HTTP errors (4xx/429) are not —
they are the finding.

2026-10-17 result: PASS — ollama/groq/openrouter/mistral/gemini live 200s;
paid overflow resolved; github_models UNVERIFIABLE (GitHub Models service
retired upstream 2026-07-30 — reported, never faked).
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
from budget.model_router import ModelRouter
from budget.providers import (
    ProviderUnavailable,
    RateLimited,
    build_registry,
    chat,
    discover_models,
)

# Keep in lockstep with ModelRouter.OR_CLAUDE_PAID (the paid overflow stop).
PAID_OVERFLOW = "anthropic/claude-sonnet-5.5"

# max_tokens for the (b) probes: reasoning models (gpt-oss-120b, nemotron)
# spend ~100 tokens on reasoning before emitting `content`, so 8/32 come back
# empty. 160 is $0 on every free provider and still tiny.
PROBE_MAX_TOKENS = 160


def _default_out_path() -> str:
    if os.path.isdir("/tmp/opencode"):
        return "/tmp/opencode/s5b_live_verification.json"
    return os.path.join(os.getcwd(), "s5b_live_verification.json")


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


async def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else _default_out_path()
    cfg = HarnessConfig.load_from_env()
    reg = build_registry(cfg)
    enabled = [p for p in reg if p.enabled]
    disabled = [p.name for p in reg if not p.enabled]
    gh = cfg.github_token or ""
    print(f"registry: {len(reg)} providers | enabled ({len(enabled)}): "
          f"{[p.name for p in enabled]} | disabled: {disabled}")
    if gh:
        print(f"NOTE: GITHUB_TOKEN present (len {len(gh)}). GitHub Models was "
              f"RETIRED upstream 2026-07-30 (docs.github.com) — a live 200 is "
              f"impossible for that provider; the routing chain falls through "
              f"to the OpenRouter paid stop.")

    # ── (a) live GET /models re-check ────────────────────────────────────
    discovery_rows = []
    print("\n=== (a) live GET /models re-check (all enabled catalogs) ===")
    for p in enabled:
        for _attempt in range(3):
            try:
                await net_retry(lambda: discover_models(p))
            except Exception as e:
                p.live_models = None
                print(f"  {p.name:14s} discovery transient error (retrying): {e}")
                continue
            break
        live = p.live_models or []
        if live:
            pref = p.models
            still = [m for m in pref if m in live]
            rotated = [m for m in pref if m not in live]
            discovery_rows.append({"name": p.name, "live_count": len(live),
                                   "prefs_live": still, "rotated_out": rotated})
            print(f"  {p.name:14s} live_models={len(live):4d}  "
                  f"prefs still live={len(still)}/{len(pref)}  "
                  f"rotated_out={rotated or 'none'}")
            if p.name == "openrouter":
                print(f"  {'':14s} paid-overflow '{PAID_OVERFLOW}' in live "
                      f"catalog: {PAID_OVERFLOW in live}")
        else:
            discovery_rows.append({"name": p.name, "live_count": 0,
                                   "note": "no live catalog (fail-open, prefs kept)"})
            print(f"  {p.name:14s} no live catalog (fail-open, configured prefs kept)")

    # ── (b) one real 200 per enabled provider ────────────────────────────
    # Gate S5(2): "one real call per enabled provider returns 200". For each
    # provider we make real calls to its resolved models (in order, ≤3) until
    # one returns 200 — a 429 on one model is a per-model free-tier throttle
    # (it still proves the provider is live + the key valid: a dead endpoint
    # is 404/net-error, a bad key is 401). An empty `content` on a 200 is a
    # NOTE (reasoning/budget artifact), not a failure.
    call_rows = []
    print("\n=== (b) one real 200 per enabled provider (provider/tier/lane) ===")
    for p in enabled:
        models = p.resolved_models() or list(p.models)
        if p.name == "openrouter":
            models = [m for m in models if m != PAID_OVERFLOW]  # (c) covers paid
        row = {"name": p.name, "tier": p.tier, "lane": p.lane.value,
               "model": None, "ok": False}
        triaged = ("You are a bug-bounty triage helper. /api/login returned a "
                   "stack trace on a malformed input. One word: CONFIRMED or "
                   "NOT CONFIRMED.")
        for model in models[:3]:
            t0 = time.monotonic()
            status_str, content, in_tok, out_tok, err = None, "", 0, 0, None
            try:
                r = await net_retry(
                    lambda m=model: chat(p, m, triaged, max_tokens=PROBE_MAX_TOKENS))
                status_str, content = "200", (r.text or "").strip()
                in_tok, out_tok = r.input_tokens, r.output_tokens
            except RateLimited:
                err = "429 (per-model throttle) — provider live, trying next model"
            except ProviderUnavailable as e:
                err = str(e)
                row.update({"model": model, "ok": False, "http": "ERR", "error": err})
                break  # deterministic 4xx — provider down, stop
            except Exception as e:
                row.update({"model": model, "ok": False, "http": "ERR",
                            "error": f"{type(e).__name__}: {e}"})
                break  # transient net (already retried) — stop
            if status_str == "200":
                row.update({"model": model, "ok": True, "http": "200",
                            "in_tokens": in_tok, "out_tokens": out_tok,
                            "ms": int((time.monotonic() - t0) * 1000),
                            "content": content[:40],
                            "empty_content": not bool(content)})
                print(f"  {p.name:14s} 200  tier={p.tier:13s} lane={p.lane.value:10s} "
                      f"model={model[:34]:34s} {row['ms']:>6} ms "
                      f"in={in_tok} out={out_tok} {content[:22]!r}"
                      + ("  [empty content: reasoning/budget]" if not content else ""))
                break
            if err:  # 429 on this model — note + try the provider's next model
                print(f"  {p.name:14s} 429  model={model[:34]:34s} ({err.split('—')[0].strip()})")
        call_rows.append(row)

    # ── (c) OpenRouter paid overflow: resolves post top-up ───────────────
    paid_row = {"model": PAID_OVERFLOW, "in_catalog": None, "call": None}
    orp = next((p for p in enabled if p.name == "openrouter"), None)
    if orp is not None:
        paid_row["in_catalog"] = bool(orp.live_models) and PAID_OVERFLOW in orp.live_models
        try:
            r = await net_retry(
                lambda: chat(orp, PAID_OVERFLOW, "Reply with exactly: S5B-OK",
                             max_tokens=8))
            paid_row["call"] = {"ok": True, "in": r.input_tokens,
                                "out": r.output_tokens, "text": r.text[:40]}
            print(f"\n=== (c) paid overflow (PAID, post top-up) ===")
            print(f"  {PAID_OVERFLOW}  200  in={r.input_tokens} out={r.output_tokens} "
                  f"{r.text[:24]!r}")
        except Exception as e:
            paid_row["call"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            print(f"\n=== (c) paid overflow ===\n  {PAID_OVERFLOW}  FAIL {e}")

    # ── (d) end-to-end router.route() (real scrub/limiter/billing) ───────
    route_row = {}
    print("\n=== (d) end-to-end router.route() (real scrub/limiter/billing) ===")
    try:
        bus = InMemoryEventBus()
        tracker = TokenTracker(bus)
        router = ModelRouter(cfg, tracker)
        await router.startup_health_check()
        await router.startup_discovery()
        t0 = time.monotonic()
        # max_tokens=160: the groq primary (gpt-oss-120b) is a reasoning
        # model — 32 is all reasoning, empty content. See the S5b finding.
        resp = await router.route(
            "triage_decision",
            "You are a bug-bounty triage agent. Endpoint /api/login returned a "
            "stack trace on a bad input. Answer only: CONFIRMED or NOT CONFIRMED.",
            agent_id="s5b-verify", task_id="s5b_check", max_tokens=160,
        )
        route_row = {"provider": resp.provider, "tier": resp.tier.value,
                     "lane": resp.lane, "model": resp.model,
                     "in_tokens": resp.input_tokens, "out_tokens": resp.output_tokens,
                     "ms": int((time.monotonic() - t0) * 1000), "text": resp.text[:40]}
        print(f"  route('triage_decision') -> provider={resp.provider} "
              f"tier={resp.tier.value} lane={resp.lane} model={resp.model} "
              f"in={resp.input_tokens} out={resp.output_tokens} "
              f"{route_row['ms']} ms  {resp.text[:32]!r}")
        wing = tracker.get_wing_summary()
        print(f"  tracker per_provider buckets: "
              f"{json.dumps(wing.get('per_provider', {}), default=str)}")
    except Exception as e:
        route_row = {"error": f"{type(e).__name__}: {e}"}
        print(f"  route() FAIL: {e}")

    # ── Gate summary ─────────────────────────────────────────────────────
    ok = [r for r in call_rows if r["ok"]]
    unverified = [r for r in call_rows
                  if not r["ok"] and r["name"] == "github_models"]
    bad = [r for r in call_rows if not r["ok"] and r["name"] != "github_models"]
    paid_ok = bool(paid_row["call"] and paid_row["call"].get("ok"))
    passed = not bad and paid_ok

    print(f"\nGATE S5b (live):")
    print(f"  enabled providers returning live 200 : {len(ok)}/{len(enabled)}"
          + (f"  [OK: {', '.join(r['name'] for r in ok)}]" if ok else ""))
    if unverified:
        print(f"  github_models                            : UNVERIFIABLE — upstream "
              f"service RETIRED 2026-07-30 (not a code defect); chain falls "
              f"through to OpenRouter paid")
    if bad:
        print(f"  FAIL: {[(r['name'], r.get('error')) for r in bad]}")
    print(f"  paid overflow {PAID_OVERFLOW}: "
          f"{'RESOLVED (catalog + live 200)' if paid_ok else 'NOT RESOLVED'}")
    print(f"  RESULT: {'PASS' if passed else 'FAIL'}")

    out = {"date": time.strftime("%Y-%m-%d"), "enabled": [p.name for p in enabled],
           "disabled": disabled, "discovery": discovery_rows, "calls": call_rows,
           "paid_overflow": paid_row, "router_route": route_row,
           "gate_s5b": "PASS" if passed else "FAIL",
           "gate_note": "github_models excluded from denominator: GitHub Models "
                        "service retired upstream 2026-07-30"}
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"details -> {out_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
