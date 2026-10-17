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


# ── S5b — live-catalog reconciliation regressions (offline) ────────────────
# The S5b live run (2026-10-17) exposed three real defects that are now locked
# by these hermetic tests: (1) Gemini-native discovery parsed dict-strings,
# (2) default_http sent a JSON body on GET (Groq/Gemini 400), and
# (3) a placeholder .env key advertised a fake-enabled provider.

from budget.providers import build_registry, discover_models, Provider  # noqa: E402
from core.config import _clean_key  # noqa: E402
from budget.model_router import DEFAULT_TASK_MAX_TOKENS, TASK_MAX_TOKENS  # noqa: E402


def _gemini_provider():
    # Pick by name: index 0 is always ollama (registered unconditionally).
    return next(p for p in build_registry(HarnessConfig(gemini_api_key="K"))
                if p.name == "gemini")


def test_s5b_gemini_native_discovery_parses_clean_ids(run_async):
    """Gemini GET /models returns {"models":[{"name":"models/<id>"}]} (dicts,
    models/-prefixed) — NOT OpenAI's {"data":[{"id"}]}. The parser must yield
    bare IDs (the 2026-10 S5b bug turned them into str(dict) garbage, so
    resolved_models() then 'called' a model named "{'name': ...}" -> 404)."""
    p = _gemini_provider()
    seen = {}

    async def fake_http(method, url, headers, payload, timeout=10):
        seen["method"], seen["headers"] = method, headers
        return 200, {"models": [
            {"name": "models/gemini-3.1-flash-lite"},
            {"name": "models/gemini-3.8-flash"},
            {"name": "models/gemini-2.5-pro"},
        ]}

    run_async(discover_models(p, http=fake_http))
    # Clean, bare IDs — no "models/" prefix, no dict-string artifacts.
    assert p.live_models == ["gemini-3.1-flash-lite", "gemini-3.8-flash",
                             "gemini-2.5-pro"], p.live_models
    for m in p.live_models:
        assert m.startswith("models/") is False
        assert "{" not in m
    # resolved_models() must now return usable IDs (intersection of prefs + live).
    assert set(p.resolved_models()) <= set(p.live_models)
    # Gemini auth is the x-goog-api-key header, NOT Bearer (the S5b header fix).
    assert seen["method"] == "GET"
    assert seen["headers"].get("x-goog-api-key") == "K"
    assert "Authorization" not in seen["headers"]


def test_s5b_discovery_is_bodyless_get(monkeypatch):
    """default_http must not attach a JSON body to a GET — sending json={} adds a
    Content-Type: application/json body that Groq/Gemini reject with 400, so
    discovery silently failed open and drift went unseen (the S5b finding)."""
    from budget import providers
    import aiohttp
    captured = {}

    class _Resp:
        status = 200

        async def json(self, content_type=None):
            return {"data": [{"id": "x"}]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Sess:
        """Fake aiohttp.ClientSession: default_http does
        ``async with aiohttp.ClientSession() as session:`` then
        ``async with session.request(method, url, headers=..., json=..., ...)``."""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def request(self, method, url, headers=None, json=None, timeout=None):
            captured["method"] = method
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(aiohttp, "ClientSession", _Sess)
    import asyncio
    asyncio.run(providers.default_http("GET", "https://x/v1/models",
                                       {"Authorization": "Bearer k"}, {}))
    assert captured["method"] == "GET"
    assert captured["json"] is None, "GET must be bodyless"


def test_s5b_placeholder_key_counts_as_unset():
    """A half-filled .env (ghp_REPLACE_ME etc.) must not advertise a fake-enabled
    provider. _clean_key normalizes placeholder/empty values to None."""
    assert _clean_key(None) is None
    assert _clean_key("") is None
    assert _clean_key("   ") is None
    assert _clean_key("ghp_REPLACE_ME") is None
    assert _clean_key("sk-EXAMPLE_KEY_123") is None
    assert _clean_key("sk-change-me") is None
    # A genuine-looking key is kept verbatim.
    assert _clean_key("gsk_7cXYZ123") == "gsk_7cXYZ123"
    assert _clean_key("sk-or-v1-abcd1234") == "sk-or-v1-abcd1234"


def test_s5b_load_from_env_drops_placeholder_github(monkeypatch):
    """load_from_env must drop a placeholder GITHUB_TOKEN so github_models is not
    advertised as enabled (the S5b .env finding)."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_REPLACE_ME")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = HarnessConfig.load_from_env()
    assert cfg.github_token is None
    assert cfg.provider_enabled("github") is False


def test_s5b_2026_catalog_ids_are_costed_and_hosted():
    """Every model the router constants point at must have a MODEL_COSTS entry
    AND be hosted by an enabled provider under the full config — otherwise Gate 1
    (table integrity) or _estimate_cost would silently break after the 2026
    free-tier rotation. This pins the reconciled live IDs."""
    from budget.model_router import (
        OR_27B_FREE, NEMO_FREE, LAGUNA_FREE, CODESTRAL,
        GEMINI_FLASH, OR_CLAUDE_PAID,
    )
    pinned = {
        OR_27B_FREE, NEMO_FREE, LAGUNA_FREE, CODESTRAL, GEMINI_FLASH,
        OR_CLAUDE_PAID, G120, LOCAL_HEAVY_MODEL, LOCAL_LIGHT_PRIMARY,
    }
    for m in pinned:
        assert m in MODEL_COSTS, f"model '{m}' has no MODEL_COSTS entry"
    # The PAID_FREE :free trio + Gemini are $0; the paid overflow is not.
    for free in (OR_27B_FREE, NEMO_FREE, LAGUNA_FREE, GEMINI_FLASH):
        assert free.endswith(":free") or free in ("codestral-latest",
                                                  "gemini-3.1-flash-lite")
    c = MODEL_COSTS[OR_CLAUDE_PAID]
    assert c["input"] > 0 and c["output"] > 0  # the paid overflow actually costs
    # And each is hosted by some enabled provider (full config).
    r = ModelRouter(full_cfg())
    by_model = set()
    for p in r._registry:
        if p.enabled and p.available:
            by_model.update(p.models)
    for m in pinned:
        assert m in by_model, f"model '{m}' not hosted by any enabled provider"


# ── S8.2 — empty-content guard + per-task max_tokens (mock-tested) ─────────
# Failure class (S5b finding): reasoning primaries (gpt-oss-120b, nemotron
# :free) spend ~100 tokens reasoning *before* emitting content, so a small
# max_tokens returns a 200 with an empty body. The guard (model_router):
#   1. every stop asks for a concrete task-sized budget (TASK_MAX_TOKENS /
#      DEFAULT_TASK_MAX_TOKENS; an explicit caller max_tokens always wins);
#   2. a 200 with empty text + output_tokens>0 is retried ONCE at 3x the
#      budget on the same stop (a hard-failed retry keeps the original empty
#      result; a successful/still-empty retry folds the original call's tokens
#      into its usage so the ledger sees every token actually spent);
#   3. a still-empty stop becomes a rotation signal
#      (raw["empty_content"]=True); if EVERY stop "served 200 but empty" the
#      last empty response is surfaced to the agent — NOT a NoBudgetError;
#   4. "all stops hard-failed" is unchanged → NoBudgetError.
# Consensus on an empty verdict is fail-closed (documented, not changed).

def _openai_body(content, prompt_tokens=8, completion_tokens=12,
                 model="gpt-oss-120b"):
    """Minimal openai-compatible chat-completions body for the fakes below."""
    return {
        "choices": [{"message": {"content": content}}],
        "model": model,
        "usage": {"prompt_tokens": prompt_tokens,
                  "completion_tokens": completion_tokens},
    }


def _seq_http(sequences):
    """Stateful fake transport: per url-substring, returns scripted items in
    call order. An item is a body (=> 200) or a (status, body) tuple. The last
    item repeats once the list is down to one, so a stop with no scripted
    exhaustion keeps its final answer. Records (method, url, payload) in
    order; unmatched URLs fall back to _default_body (as make_http does)."""
    state = {k: list(v) for k, v in sequences.items()}
    calls = []

    async def http(method, url, headers, payload, timeout=60):
        calls.append((method, url, payload))
        for key, seq in state.items():
            if key in url:
                item = seq.pop(0) if len(seq) > 1 else seq[0]
                if isinstance(item, tuple):
                    status, body = item
                else:
                    status, body = 200, item
                return status, body
        return 200, _default_body(method, url, payload)

    http.calls = calls  # type: ignore[attr-defined]
    return http


class TestS82EmptyContentGuard:
    """Gate S8.2: a 200-with-empty-content must never masquerade as a
    success, and every stop must ask for a concrete task-sized budget."""

    def test_empty_retries_once_at_larger_budget_then_succeeds(self, run_async):
        cfg = full_cfg()
        tracker = TokenTracker()
        r = _mk(ModelRouter(cfg, tracker), tracker)
        http = _seq_http({
            "groq": [_openai_body("", completion_tokens=100),   # reasoning ate the budget
                     _openai_body("CONFIRMED")],                # 3x-budget retry: content
        })
        r._http = http

        resp = run_async(r.route("triage_decision", "is this finding in scope?"))

        assert resp.text == "CONFIRMED"
        assert resp.raw.get("empty_content") is None      # recovered, unflagged
        groq = [p for (_, u, p) in http.calls if "groq" in u]
        assert len(groq) == 2                             # 1 attempt + exactly 1 retry
        assert groq[0]["max_tokens"] == TASK_MAX_TOKENS["triage_decision"] == 160
        assert groq[1]["max_tokens"] == 480               # 3x the task budget
        # Ledger: one billed outcome carrying BOTH real calls' tokens.
        per = tracker.get_wing_summary()["per_provider"]
        assert per["groq"]["calls"] == 1
        assert per["groq"]["output_tokens"] == 100 + 12   # empty call + retry

    def test_still_empty_after_retry_rotates_to_next_stop(self, run_async):
        cfg = full_cfg()
        r = _mk(ModelRouter(cfg, TokenTracker()), None)
        http = _seq_http({
            "groq": [_openai_body("", completion_tokens=100),
                     _openai_body("", completion_tokens=150)],  # still empty on retry
        })
        r._http = http

        resp = run_async(r.route("scope_interpret", "scope: *.example.com"))

        # A stop empty on BOTH attempts is a rotation signal.
        assert resp.provider == "openrouter"
        assert resp.text == "CLOUD-OK"
        assert resp.raw.get("empty_content") is None
        groq = [p for (_, u, p) in http.calls if "groq" in u]
        assert len(groq) == 2                             # attempt + retry, no third
        assert groq[0]["max_tokens"] == 160
        assert groq[1]["max_tokens"] == 480

    def test_all_stops_empty_surfaces_flagged_not_no_budget(self, run_async):
        """'Served 200 but empty' on every stop is NOT a NoBudgetError — the
        last empty response comes back flagged so the AGENT decides."""
        cfg = full_cfg()
        tracker = TokenTracker()
        r = _mk(ModelRouter(cfg, tracker), tracker)
        http = _seq_http({
            "groq": [_openai_body("", completion_tokens=100),
                     _openai_body("", completion_tokens=150)],
            "openrouter": [_openai_body("", completion_tokens=80),
                           _openai_body("", completion_tokens=120)],
        })
        r._http = http

        resp = run_async(r.route("scope_interpret", "scope: *.example.com"))

        assert resp.text.strip() == ""
        assert resp.raw["empty_content"] is True
        assert resp.provider == "openrouter"              # the LAST empty stop
        # The empty responses still billed the tokens the reasoning consumed.
        per = tracker.get_wing_summary()["per_provider"]
        assert per["openrouter"]["calls"] == 1
        assert per["openrouter"]["output_tokens"] == 80 + 120

    def test_hard_fail_then_empty_surfaces_flagged(self, run_async):
        cfg = full_cfg()
        r = _mk(ModelRouter(cfg, TokenTracker()), None)
        http = _seq_http({
            "groq": [(500, {"error": "down"})],                       # hard fail
            "openrouter": [_openai_body("", completion_tokens=80),
                           _openai_body("", completion_tokens=120)],  # empty x2
        })
        r._http = http

        resp = run_async(r.route("scope_interpret", "scope: *.example.com"))

        assert resp.raw["empty_content"] is True
        assert resp.provider == "openrouter"
        assert resp.text.strip() == ""
        assert len([u for (_, u, _) in http.calls if "groq" in u]) == 1

    def test_all_hard_fail_still_raises_no_budget(self, run_async):
        """Unchanged contract: every stop HARD-failing is still a NoBudgetError
        — the S8.2 empty path only replaces the all-EMPTY case, never 5xx."""
        cfg = full_cfg()
        r = _mk(ModelRouter(cfg, TokenTracker()), None)
        http = _seq_http({
            "groq": [(500, {"error": "down"})],
            "openrouter": [(500, {"error": "down"})],
        })
        r._http = http

        with pytest.raises(NoBudgetError, match="all provider stops failed"):
            run_async(r.route("scope_interpret", "scope: *.example.com"))

    def test_retry_hard_failure_keeps_empty_and_rotates(self, run_async):
        """If the larger-budget retry itself 429s, the original empty 200 is
        kept (flagged) and rotation proceeds — no crash, no fake answer."""
        cfg = full_cfg()
        r = _mk(ModelRouter(cfg, TokenTracker()), None)
        http = _seq_http({
            "groq": [_openai_body("", completion_tokens=100), (429, {})],
            "openrouter": [_openai_body("OR-SERVED")],
        })
        r._http = http

        resp = run_async(r.route("scope_interpret", "scope: *.example.com"))

        assert resp.provider == "openrouter"
        assert resp.text == "OR-SERVED"
        assert len([u for (_, u, _) in http.calls if "groq" in u]) == 2

    def test_empty_zero_output_tokens_not_retried(self, run_async):
        """Heuristic boundary: empty text + output_tokens==0 is a genuine
        no-answer (nothing a bigger budget would fix) — no retry, just rotate."""
        cfg = full_cfg()
        r = _mk(ModelRouter(cfg, TokenTracker()), None)
        http = _seq_http({
            "groq": [_openai_body("", completion_tokens=0)],
        })
        r._http = http

        resp = run_async(r.route("scope_interpret", "scope: *.example.com"))

        assert len([u for (_, u, _) in http.calls if "groq" in u]) == 1   # no retry
        assert resp.provider == "openrouter"
        assert resp.text == "CLOUD-OK"

    def test_task_budget_floors_land_in_payload(self, run_async):
        """No explicit max_tokens → a concrete task budget is stamped on the
        wire (unmapped task → default floor, mapped task → its own floor)."""
        r = _mk(ModelRouter(full_cfg(), TokenTracker()), None)
        http = _seq_http({})
        r._http = http
        run_async(r.route("scope_interpret", "scope: *.example.com"))
        assert http.calls[0][2]["max_tokens"] == DEFAULT_TASK_MAX_TOKENS == 160

        r2 = _mk(ModelRouter(full_cfg(), TokenTracker()), None)
        http2 = _seq_http({})
        r2._http = http2
        run_async(r2.route("report_draft", "draft the report"))
        assert http2.calls[0][2]["max_tokens"] == TASK_MAX_TOKENS["report_draft"] == 2048

    def test_explicit_max_tokens_wins_over_task_map(self, run_async):
        cfg = full_cfg()
        r = _mk(ModelRouter(cfg, TokenTracker()), None)
        http = _seq_http({})
        r._http = http
        run_async(r.route("triage_decision", "is this in scope?", max_tokens=32))
        assert http.calls[0][2]["max_tokens"] == 32

    def test_local_stop_gets_task_budget_as_num_predict(self, run_async):
        """LOCAL stops receive the same task-sized budget (num_predict)."""
        cfg = full_cfg()
        r = _mk(ModelRouter(cfg, TokenTracker()), None)
        r._ollama_available = True
        http = _seq_http({})
        r._http = http

        run_async(r.route("error_classify", "classify this error body: 500"))
        ollama = [p for (_, u, p) in http.calls if "/api/generate" in u]
        assert ollama[0]["options"]["num_predict"] == TASK_MAX_TOKENS["error_classify"] == 128

    def test_local_empty_content_is_flagged(self, run_async, monkeypatch):
        """A LOCAL stop serving whitespace is flagged with the SAME contract as
        cloud stops (no retry locally — no reasoning budget to retry against),
        and a single empty LOCAL stop is surfaced, not crashed on."""
        cfg = full_cfg()
        r = _mk(ModelRouter(cfg, TokenTracker()), None)
        r._ollama_available = True
        seen = {}

        async def _empty_ollama(model, prompt, **kwargs):
            seen.update(kwargs)
            return LLMResponse(text="   ", model=model, tier=ModelTier.LOCAL,
                               input_tokens=5, output_tokens=9)

        monkeypatch.setattr(r, "_call_ollama", _empty_ollama)
        resp = run_async(r.route("error_classify", "classify this error body: 500"))

        assert resp.text == "   "
        assert resp.raw["empty_content"] is True
        assert seen["max_tokens"] == TASK_MAX_TOKENS["error_classify"] == 128

    def test_consensus_on_empty_primary_is_fail_closed(self, run_async):
        """Documented S8.2 behavior (unchanged): _verdict_confirms('') is
        False, so an empty primary can never yield agreement=True — even with a
        confirming partner (fail-closed)."""
        cfg = full_cfg()
        r = _mk(ModelRouter(cfg, TokenTracker()), None)
        http = _seq_http({
            "groq": [_openai_body("", completion_tokens=100),
                     _openai_body("", completion_tokens=150)],  # primary empty x2
            "9999": [_openai_body("CONFIRMED: SQLi on /login")],  # partner confirms
        })
        r._http = http

        resp = run_async(r.route("vuln_confirm", "does /login reflect the input unsanitized?"))

        assert resp.text.strip() == ""
        assert resp.raw["empty_content"] is True
        c = resp.raw["consensus"]
        assert c["primary_confirms"] is False
        assert c["agree_confirms"] is True
        assert c["agreement"] is False
