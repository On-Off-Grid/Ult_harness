# tests/test_s5_router.py
"""S5a — multi-provider model router gates (mock-tested, keyless).

These gates exercise the S5 router WITHOUT any live key or network: HTTP is
injected via ``ModelRouter._http`` (an ``async fn(method, url, headers,
payload, timeout) -> (status, json_dict)`` callable) and the provider registry
is built from explicit ``HarnessConfig`` fields (never ``os.environ``).

Covered (per the plan's Gate S5):
  Gate 1 — table integrity: every entry + chain stop has a tier, a model with a
           cost entry, and an enabled provider under the FULL config.
  Gate 3 — 429 rotation: groq 429 → openrouter serves, response provenance says
           openrouter, and BOTH provider URLs were hit in order.
  Gate 4 — scrub hard rule: a secret-bearing prompt is re-routed to local only;
           NO cloud URL (incl. RESTRICTED-lane gemini) is ever called.
  Gate 5 — per-provider ledger buckets: groq + ollama each get calls==1, $0.
  Gate 6 — projection: a standard session stays under the $0.50 budget line.
Plus: LOCAL_HEAVY off/on, two-model consensus agreement, all-429 →
NoBudgetError, discovery fail-open, and the Ollama-only never-paid invariant.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

import pytest

from core.config import HarnessConfig
from budget.model_router import (
    ModelRouter, ModelTier, LLMResponse, NoBudgetError,
    MODEL_ROUTING_TABLE, FALLBACK_CHAIN, TIER_DEFAULTS,
    LOCAL_LIGHT_PRIMARY, LOCAL_HEAVY_MODEL, G120,
    OR_27B_FREE, GEMINI_FLASH,
)
from budget.providers import RateLimited
from budget.token_tracker import TokenTracker, MODEL_COSTS
from compliance.scrub import scrub

# A prompt that trips the scrubber (openai_key pattern) — used by Gate 4.
SECRET_PROMPT = (
    "Triage this JS bundle: const apiKey = "
    '"sk-proj-AB12cd34EF56gh78IJ90kl12mn34OP"; fetch("/x");'
)
assert scrub(SECRET_PROMPT).found, "test fixture must trip the scrubber"

# A benign prompt that must NEVER trip the scrubber (incl. the word "token").
BENIGN_PROMPT = "Extract the endpoint paths from this XHR snippet: /api/users/{id}"
assert scrub(BENIGN_PROMPT).clean, "test fixture must pass the scrubber"

SECRET_Y = re.compile(r"sk-proj-[A-Za-z0-9]{10,}")


# ── Full-keyed config (the "operator has everything" scenario) ─────────────
def full_cfg() -> HarnessConfig:
    return HarnessConfig(
        groq_api_key="G",
        openrouter_api_key="O",
        mistral_api_key="M",
        github_token="GT",
        gemini_api_key="GEM",
        local_heavy_url="http://127.0.0.1:9999/v1",
    )


def _mk(router: ModelRouter, tracker: TokenTracker = None):
    router.tracker = tracker
    return router


# ── Fake HTTP transports ───────────────────────────────────────────────────
@dataclass
class HttpLog:
    calls: list = field(default_factory=list)    # (method, url) in order
    bodies: list = field(default_factory=list)   # payload per call, same order
    status_for: dict = field(default_factory=dict)   # url-substring -> status
    json_for: dict = field(default_factory=dict)     # url-substring -> body
    order: list = field(default_factory=list)
    fail_models: set = field(default_factory=set)    # payload["model"] -> 429

    def sub(self, url: str) -> str:
        for key in list(self.status_for) + list(self.json_for):
            if key in url:
                return key
        return "?"


def make_http(log: HttpLog):
    """Async fake transport. Records every (method, url). Raises RateLimited on
    429 (so the router's rotation path fires) — mirrors providers.chat()."""
    async def fake_http(method, url, headers, payload, timeout=60):
        log.calls.append((method, url))
        log.bodies.append(payload)
        log.order.append(log.sub(url))
        if isinstance(payload, dict) and payload.get("model") in log.fail_models:
            raise RateLimited(f"fake model-limited: {payload.get('model')}")
        sub = log.sub(url)
        status = log.status_for.get(sub, 200)
        if status == 429:
            raise RateLimited(f"fake {sub}: 429")
        body = log.json_for.get(sub)
        if body is None:
            body = _default_body(method, url, payload)
        return status, body
    return fake_http


def _default_body(method, url, payload):
    """Sensible 200 bodies so each adapter parses something real."""
    if "/api/generate" in url:                      # ollama
        return {"response": "OLLAMA-OK", "model": (payload or {}).get("model", ""),
                "prompt_eval_count": 5, "eval_count": 7}
    if ":generateContent" in url:                   # gemini
        return {"candidates": [{"content": {"parts": [{"text": "GEMINI-OK"}]}}],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 6}}
    if url.endswith("/models") or "/api/tags" in url:  # discovery
        return {"data": [{"id": "probe-model"}]}
    # openai-compat
    return {"choices": [{"message": {"content": "CLOUD-OK"}}],
            "model": (payload or {}).get("model", ""),
            "usage": {"prompt_tokens": 8, "completion_tokens": 12}}


# ── Gate 1: table integrity ────────────────────────────────────────────────
def test_gate1_table_integrity_full_config():
    """Every preferred stop AND every chain stop must resolve to an enabled,
    available provider under the full config (2026 catalog is stable)."""
    r = ModelRouter(full_cfg())
    by_model = {}
    for p in r._registry:
        if p.enabled and p.available:
            for m in p.models:
                by_model.setdefault(m, []).append(p.name)

    for task, entry in MODEL_ROUTING_TABLE.items():
        assert entry["tier"] in {t.value for t in ModelTier}, task
        assert entry["model"], task
        models = [entry["model"]] + [s[1] for s in entry.get("chain", [])]
        for m in models:
            assert m in by_model, f"{task}: model '{m}' has no enabled provider"
            assert m in MODEL_COSTS, f"{task}: model '{m}' has no cost entry"
    # TIER_DEFAULTS too (fallback terminal targets).
    for tier, m in TIER_DEFAULTS.items():
        assert m in by_model, f"TIER_DEFAULTS[{tier.value}]: '{m}' has no provider"


def test_table_local_only_tasks_are_local():
    for task, entry in MODEL_ROUTING_TABLE.items():
        if entry.get("local_only"):
            assert entry["tier"] == "LOCAL", task


# ── Gate 3: 429 rotation groq -> openrouter ────────────────────────────────
def test_gate3_groq_429_rotates_to_openrouter(run_async):
    cfg = full_cfg()
    tracker = TokenTracker()
    r = _mk(ModelRouter(cfg, tracker), tracker)

    log = HttpLog(status_for={"groq": 429, "openrouter": 200})
    r._http = make_http(log)

    resp = run_async(r.route("scope_interpret", "scope this target: *.example.com"))
    assert resp.text == "CLOUD-OK"
    assert resp.provider == "openrouter"            # provenance of the winner
    assert resp.model == OR_27B_FREE                # the chain stop served
    assert resp.tier is ModelTier.PAID_FREE
    # BOTH URLs hit, in order: groq first (429), then openrouter.
    hosts = [u.split("/")[2] for (_, u) in log.calls]
    assert hosts == ["api.groq.com", "openrouter.ai"]
    # Billing landed in the openrouter bucket (the one that actually served).
    per = tracker.get_wing_summary()["per_provider"]
    assert "openrouter" in per and per["openrouter"]["calls"] == 1


# ── Gate 4: scrub hard rule — secret never leaves the machine ─────────────
def test_gate4_secret_prompt_reroutes_to_ollama_only(run_async):
    cfg = full_cfg()
    tracker = TokenTracker()
    r = _mk(ModelRouter(cfg, tracker), tracker)

    log = HttpLog()
    r._http = make_http(log)

    resp = run_async(r.route("scope_interpret", SECRET_PROMPT))
    assert resp.provider == "ollama"
    assert resp.tier is ModelTier.LOCAL
    assert resp.raw.get("scrub_rerouted"), "response must surface the re-route"
    # NO cloud URL may be touched — including RESTRICTED-lane gemini.
    for (_, u) in log.calls:
        assert "127.0.0.1" in u, f"secret prompt leaked to cloud URL: {u}"
        assert "generativelanguage.googleapis.com" not in u
        assert "api.groq.com" not in u
        assert "openrouter.ai" not in u


def test_gate4_secret_on_local_heavy_task_never_touches_gemini(run_async):
    """dataflow_analysis prefers LOCAL_HEAVY; with a secret it must stay local
    (27B first, then 8B) and MUST NOT fall to the RESTRICTED gemini stop."""
    cfg = full_cfg()
    r = _mk(ModelRouter(cfg, TokenTracker()), None)
    log = HttpLog()
    r._http = make_http(log)

    resp = run_async(r.route("dataflow_analysis", SECRET_PROMPT))
    assert resp.tier is ModelTier.LOCAL_HEAVY
    assert resp.provider == "local_heavy"           # the declared local stop won
    for (_, u) in log.calls:
        assert "9999" in u, f"secret prompt leaked off-machine: {u}"


def test_gate4_scrub_refuses_when_no_local_backend(run_async):
    cfg = full_cfg()
    cfg.ollama_url = ""                              # force LOCAL off
    r = ModelRouter(cfg, TokenTracker())
    r._ollama_available = False
    r._local_heavy_available = False
    r._http = make_http(HttpLog())

    with pytest.raises(NoBudgetError, match="refusing to send to the cloud"):
        run_async(r.route("scope_interpret", SECRET_PROMPT))


def test_scrub_benign_payloads_never_block():
    """High precision: common hunt content (incl. the word 'token') passes."""
    assert scrub(BENIGN_PROMPT).clean
    assert scrub("the JWT header decodes to a session token header").clean
    assert scrub("x-access-token: <redacted> in the response header").clean
    assert scrub("curl -H 'Authorization: Bearer $TOKEN' https://x.example").clean


# ── Gate 5: per-provider ledger buckets ────────────────────────────────────
def test_gate5_per_provider_buckets(run_async):
    cfg = full_cfg()
    tracker = TokenTracker()
    r = _mk(ModelRouter(cfg, tracker), tracker)
    r._http = make_http(HttpLog())

    run_async(r.route("payload_craft", "craft a UNION SELECT payload",
                      agent_id="sqli", task_id="t1"))      # LOCAL (ollama)
    run_async(r.route("scope_interpret", "scope: *.example.com",
                      agent_id="recon", task_id="t2"))     # PAID_FREE (groq)

    per = tracker.get_wing_summary()["per_provider"]
    assert per["ollama"]["calls"] == 1
    assert per["groq"]["calls"] == 1
    assert set(per) == {"ollama", "groq"}               # no other provider billed
    assert tracker.get_wing_summary()["total_cost_usd"] == 0.0


# ── Gate 6: session projection under the $0.50 line ───────────────────────
def test_gate6_standard_session_projection_within_budget():
    t = TokenTracker()
    proj = t.project_standard_session()
    assert proj["budget_line_usd"] == 0.50
    assert proj["within_budget"] is True
    assert proj["projected_cost_usd"] <= 0.50


# ── LOCAL_HEAVY off / on toggle ────────────────────────────────────────────
def test_local_heavy_off_falls_back_up_only(run_async):
    """LOCAL_HEAVY-preferred task with the GPU off: up-only fallback to the
    FREE pool (never DOWN to LOCAL), served by groq (full config)."""
    cfg = HarnessConfig(groq_api_key="G", openrouter_api_key="O")  # no local_heavy_url
    r = _mk(ModelRouter(cfg, TokenTracker()), None)
    r._http = make_http(HttpLog())

    resp = run_async(r.route("dataflow_analysis", "trace this taint flow in the bundle"))
    assert resp.tier is ModelTier.PAID_FREE
    assert resp.provider == "groq"                     # TIER_DEFAULTS[PAID_FREE] = G120
    assert resp.model == G120


def test_local_heavy_on_serves_27b_and_meters_gpu_hours(run_async):
    cfg = full_cfg()
    tracker = TokenTracker()
    r = _mk(ModelRouter(cfg, tracker), tracker)
    r._http = make_http(HttpLog())

    resp = run_async(r.route("dataflow_analysis", "trace this taint flow"))
    assert resp.tier is ModelTier.LOCAL_HEAVY
    assert resp.provider == "local_heavy"
    assert resp.model == LOCAL_HEAVY_MODEL
    # GPU-hours were metered (wall-clock of the call, $0 on the dev pack).
    assert tracker.get_wing_summary()["gpu_hours"] >= 0.0
    # $0 token cost: the GPU cost is the hourly meter, not per-token.
    assert tracker.get_wing_summary()["total_cost_usd"] == 0.0


def test_restricted_lane_gemini_serves_when_groq_absent(run_async):
    """With LOCAL_HEAVY and Groq absent, dataflow_analysis reaches its
    RESTRICTED-lane chain stop: gemini-2.5-flash (free tier = $0 cost, but the
    data lane is RESTRICTED — scrubbed-content only)."""
    cfg = HarnessConfig(gemini_api_key="GEM")         # only cloud provider = gemini
    r = _mk(ModelRouter(cfg, TokenTracker()), None)
    r._http = make_http(HttpLog())

    resp = run_async(r.route("dataflow_analysis", "trace this taint flow"))
    assert resp.tier is ModelTier.PAID_FREE
    assert resp.provider == "gemini"
    assert resp.model == GEMINI_FLASH
    assert resp.lane == "RESTRICTED"


def test_local_heavy_unavailable_rotates_past_its_stop(run_async):
    """With the LOCAL_HEAVY stop down, the stop list advances to the fallback
    tier's default model (groq gpt-oss-120b) — the declared gemini chain stop is
    only reached if that default provider then fails."""
    cfg = full_cfg()
    r = _mk(ModelRouter(cfg, TokenTracker()), None)
    r._local_heavy_available = False                   # GPU died / not pinged
    r._http = make_http(HttpLog())

    resp = run_async(r.route("dataflow_analysis", "trace this taint flow"))
    assert resp.tier is ModelTier.PAID_FREE
    assert resp.provider == "groq"
    assert resp.model == G120


# ── Two-model consensus (vuln_confirm / idor_matrix_analyze) ───────────────
def test_consensus_agreement_both_confirm(run_async):
    cfg = full_cfg()
    tracker = TokenTracker()
    r = _mk(ModelRouter(cfg, tracker), tracker)

    log = HttpLog(json_for={
        "groq": {"choices": [{"message": {"content": "CONFIRMED: SQLi on /login"}}]},
        "9999": {"choices": [{"message": {"content": "Yes, this is a valid finding."}}]},
    })
    r._http = make_http(log)

    resp = run_async(r.route("vuln_confirm", "does /login reflect the input unsanitized?"))
    c = resp.raw["consensus"]
    assert c["agreement"] is True
    assert c["primary_confirms"] is True
    assert c["agree_confirms"] is True
    assert c["agree_provider"] == "local_heavy"        # GPU 27B preferred
    # Both calls billed: primary (groq) + consensus partner (local_heavy).
    per = tracker.get_wing_summary()["per_provider"]
    assert per["groq"]["calls"] == 1
    assert per["local_heavy"]["calls"] == 1


def test_consensus_negation_is_not_a_confirmation(run_async):
    """'NOT CONFIRMED' must NOT count as a confirmation (substring trap)."""
    cfg = full_cfg()
    r = _mk(ModelRouter(cfg, TokenTracker()), None)
    log = HttpLog(json_for={
        "groq": {"choices": [{"message": {"content": "CONFIRMED: IDOR on /invoice"}}]},
        "9999": {"choices": [{"message": {"content": "NOT CONFIRMED — needs auth"}}]},
    })
    r._http = make_http(log)

    resp = run_async(r.route("idor_matrix_analyze", "matrix rows for /invoice/{id}"))
    c = resp.raw["consensus"]
    assert c["primary_confirms"] is True
    assert c["agree_confirms"] is False
    assert c["agreement"] is False


def test_consensus_fails_open_when_no_partner(run_async):
    """Second opinion unavailable -> agreement=None, primary verdict stands.

    groq-only config: the primary (gpt-oss-120b) succeeds; the only 27B partner
    (also on groq) is 429-limited and there is no GPU 27B, so the consensus
    fail-opens to the primary alone."""
    cfg = HarnessConfig(groq_api_key="G")              # no local_heavy, no 2nd provider
    r = _mk(ModelRouter(cfg, TokenTracker()), None)
    log = HttpLog(fail_models={"qwen/qwen3.8-27b"})    # partner model is 429-limited
    r._http = make_http(log)

    resp = run_async(r.route("vuln_confirm", "confirm this finding"))
    assert resp.provider == "groq"                     # primary served
    c = resp.raw["consensus"]
    assert c["agreement"] is None
    assert "reason" in c


# ── Exhaustion: every stop 429s / unavailable ──────────────────────────────
def test_all_stops_429_raises_no_budget(run_async):
    cfg = full_cfg()
    r = _mk(ModelRouter(cfg, TokenTracker()), None)
    # groq + openrouter both 429; the task's stops only include those two.
    log = HttpLog(status_for={"groq": 429, "openrouter": 429})
    r._http = make_http(log)

    with pytest.raises(NoBudgetError, match="all provider stops failed"):
        run_async(r.route("scope_interpret", "scope: *.example.com"))


def test_provider_unavailable_rotates(run_async):
    """A 500 (ProviderUnavailable) on the first stop rotates to the next."""
    cfg = full_cfg()
    r = _mk(ModelRouter(cfg, TokenTracker()), None)
    log = HttpLog(status_for={"groq": 500, "openrouter": 200},
                  json_for={"openrouter": {"choices": [{"message": {"content": "OR-OK"}}]}})
    r._http = make_http(log)

    resp = run_async(r.route("scope_interpret", "scope: *.example.com"))
    assert resp.provider == "openrouter"
    assert resp.text == "OR-OK"


# ── Discovery: fail-open + runtime catalog reconciliation ──────────────────
def test_startup_discovery_fail_open(run_async, monkeypatch):
    """Discovery must never break startup: a hard failure keeps preferences."""
    cfg = full_cfg()
    r = ModelRouter(cfg, TokenTracker())

    async def boom(method, url, headers, payload, timeout=10):
        raise RuntimeError("network down")

    r._http = boom
    run_async(r.startup_discovery())               # must not raise
    # Preferences intact: groq still hosts G120, routing unaffected.
    p = r._provider("groq")
    assert p.live_models is None
    assert G120 in p.models


def test_discovery_reconciles_rotated_catalog(run_async):
    """If a configured model rotated out of the live catalog, route() calls the
    first live model instead (never a dead name)."""
    cfg = full_cfg()
    r = _mk(ModelRouter(cfg, TokenTracker()), None)

    log = HttpLog(json_for={
        # groq's live catalog no longer lists G120; it now lists a rotated name.
        "groq": {"choices": [{"message": {"content": "ROTATED-OK"}}], "model": "rotated-1"},
    })
    r._http = make_http(log)

    # Simulate discovery: groq live catalog = one rotated model.
    groq = r._provider("groq")
    groq.live_models = ["gpt-oss-120b-rotated-2026"]

    resp = run_async(r.route("scope_interpret", "scope: *.example.com"))
    assert resp.provider == "groq"
    # The call went to the live model, not the stale configured name.
    i = next(n for n, c in enumerate(log.calls) if "api.groq.com" in c[1])
    assert log.bodies[i]["model"] == "gpt-oss-120b-rotated-2026"


# ── Ollama-only: the never-paid invariant (S4.3, re-asserted for S5) ───────
def test_ollama_only_never_paid(run_async, monkeypatch):
    """With ONLY Ollama, every LOCAL task serves local; every cloud-preferred
    task fails fast (NoBudgetError). Nothing paid is ever resolvable."""
    for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
              "OPENROUTER_API_KEY", "GITHUB_TOKEN", "MISTRAL_API_KEY",
              "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    cfg = HarnessConfig(ollama_url="http://127.0.0.1:1")   # ollama "down" probe-safe
    r = ModelRouter(cfg, TokenTracker())
    r._ollama_available = True                            # force LOCAL on
    # No cloud provider in the registry (config-driven, env irrelevant).
    cloud = [p for p in r._registry if p.tier in ("PAID_FREE", "PAID_PREMIUM")]
    assert all(not p.enabled for p in cloud), "no cloud provider should be enabled"

    # LOCAL task resolves + serves local.
    tier, model = r.resolve_model("payload_craft")
    assert tier is ModelTier.LOCAL and model == LOCAL_LIGHT_PRIMARY

    # Cloud-preferred tasks must NOT silently resolve to a paid tier.
    for task in ("scope_interpret", "chain_narrative", "report_polish",
                 "dataflow_analysis", "vuln_confirm"):
        with pytest.raises(NoBudgetError):
            r.resolve_model(task)


# ── Resolve_model tier-fallback semantics (locked S2, S5 shape) ────────────
def test_resolve_ollama_down_promotes_local_to_free(run_async, monkeypatch):
    cfg = HarnessConfig(groq_api_key="G", ollama_url="http://127.0.0.1:1")
    r = ModelRouter(cfg, TokenTracker())
    r._ollama_available = False                           # simulate Ollama down
    tier, model = r.resolve_model("payload_craft")
    assert tier is ModelTier.PAID_FREE
    assert model == TIER_DEFAULTS[ModelTier.PAID_FREE] == G120


def test_resolve_premium_terminal_is_terminal():
    """PAID_PREMIUM is the terminal fallback: with only a premium backend, a
    LOCAL task still resolves (up-only), but there is no tier above premium."""
    cfg = HarnessConfig(github_token="GT")
    r = ModelRouter(cfg, TokenTracker())
    r._ollama_available = False
    r._local_heavy_available = False
    r._groq_available = False
    tier, model = r.resolve_model("payload_craft")
    assert tier is ModelTier.PAID_PREMIUM
    assert model == TIER_DEFAULTS[ModelTier.PAID_PREMIUM]


def test_no_backend_raises():
    cfg = HarnessConfig(ollama_url="")
    r = ModelRouter(cfg, TokenTracker())
    r._ollama_available = False
    with pytest.raises(NoBudgetError):
        r.resolve_model("payload_craft")


# ── provider_status (S7 dashboard feed) ────────────────────────────────────
def test_provider_status_shape():
    r = ModelRouter(full_cfg(), None)
    snap = r.provider_status()
    names = {s["name"] for s in snap}
    assert {"ollama", "local_heavy", "groq", "openrouter",
            "mistral", "github_models", "gemini"} <= names
    for s in snap:
        for key in ("name", "tier", "lane", "enabled", "available",
                    "has_key", "models", "hourly_cost"):
            assert key in s, f"provider_status missing {key}"
    # gemini is the RESTRICTED-lane free-tier provider (S5.3).
    gem = next(s for s in snap if s["name"] == "gemini")
    assert gem["tier"] == "PAID_FREE" and gem["lane"] == "RESTRICTED"
