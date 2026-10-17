# Bug Bounty Harness — LLM Model Routing & Task Allocation Guide

> **Current — rewritten for Phase S5 (2026-10-17).** This guide describes the
> shipped **4-tier, multi-provider, lane-aware** router:
> `LOCAL` → `LOCAL_HEAVY` → `PAID_FREE` → `PAID_PREMIUM`, the FREE pool
> (Groq primary, OpenRouter / Mistral / Gemini / Cloudflare failover), the
> SAFE/RESTRICTED data lanes with the pre-call scrub hook, per-provider rate
> limiting + 429 rotation, runtime `/models` discovery, two-model consensus for
> validation tasks, and the S5.7 cost model. Authoritative sources are the
> code (`budget/model_router.py`, `budget/providers.py`, `compliance/scrub.py`,
> `core/config.py`) and `specs/assembly_plan_v3.md` §S5.1–S5.8.

**Companion to:** the v2.1 design spec, `OPERATIONS.md` (operating runbook),
and `specs/assembly_plan_v3.md` (the approved plan + gate definitions).

---

## 1. Hunt Workflow — Phase Breakdown

Routing decisions are keyed by `task_type` (the LLM job a specialist requests),
not by specialist. The 12 hunt phases and their LLM tasks:

| Phase | Tasks (task_type) |
|---|---|
| ① Scope | `scope_regex_gen`, `scope_interpret` |
| ③ Planning | `ideation_frame`, `ideation_deep`, `waf_evasion`, `fp_pattern_check` |
| ④ Payloads | `payload_craft`, `payload_polyglot`, `oob_embed` |
| ⑤ Code Analysis | `js_endpoint_extract`, `secret_detection`, `source_vuln_scan`, `dataflow_analysis`, `deobfuscation` |
| ⑥ Fuzzing | `adaptive_payload_select` |
| ⑦ Response Analysis | `error_classify`, `dom_xss_confirm`, `header_anomaly` |
| ⑧ FP Filtering | `noise_filter`, `self_xss_detect`, `confidence_score` |
| ⑨ Validation | `vuln_confirm`, `idor_matrix_analyze`, `oob_correlate`, `biz_logic_validate`, `ai_jailbreak_confirm` |
| ⑩ Chains | `chain_analysis`, `impact_escalation`, `chain_narrative` |
| ⑪ Triage | `vrt_classify`, `cwe_assign`, `cvss_calculate`, `dispute_prep`, `duplicate_detect`, `triage_decision` |
| ⑫ Reports | `report_draft`, `report_polish`, `report_format`, `screenshot_alt_text` |

An unknown `task_type` resolves to the LOCAL tier default (a warning is logged)
rather than failing — new specialists default to the safe, $0 lane.

---

## 2. The Model Pool (4 tiers, 8 providers)

### Tier 1 — `LOCAL` (LOCAL_LIGHT) · $0 · private

Ollama on the operator box. Primary **`hf.co/dr-ry/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M`**
(security-tuned 8B, resident), fallback **`qwen2.5:7b`**. 32K ctx, 60 RPM soft
limit. Serves the high-volume classify / FP / error / pattern / triage-labour
tasks and is the mandatory sink for any secret-bearing prompt.

### Tier 2 — `LOCAL_HEAVY` · $0/token · OFF unless `LOCAL_HEAVY_URL` is set

**`qwen3.8-27b`** on a cloud GPU (RunPod EU 4090, `llama-server`
OpenAI-compatible with `--api-key`, reached over Tailscale — never a public
port). Metered as **GPU-hours** (wall time × `local_heavy_hourly_cost`,
~$0.34–0.45/hr on RunPod). Used for uncensored deep reasoning, >131K context,
and as the second model of the validation consensus. Stays **off/optional
until S0.7 confirms the AMD Developer pack GPU hours** — until then heavy work
falls back per chain (Gemini 1M / OpenRouter Nemotron 1M).

### Tier 3 — `PAID_FREE` (multi-provider free pool) · $0

| Provider | Role | Models (configured preference list) | Quota | Lane |
|---|---|---|---|---|
| **Groq** | **Primary** — fastest, EU ≈ 30–60 ms from Morocco | `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` (the free 27B!), `openai/gpt-oss-20b` | 30 RPM / 1,000 RPD, 131K ctx | SAFE |
| **OpenRouter** | Failover/resilience layer (routes to many backends) | `qwen/qwen3.8-27b:free` (262K), `nvidia/nemotron-3-ultra:free` (1M), `poolside/laguna-s-2.1:free` (code), + `anthropic/claude-sonnet-4` (paid overflow — only reachable via a PREMIUM chain stop, post top-up) | 20 RPM / 1,000 RPD, 262K ctx | SAFE |
| **Mistral** | Code lane (after console data opt-out) | `codestral`, `mistral-small-latest`, `ministral-3-14b-latest` | 500 RPM / 1,000 RPD, 256K ctx | SAFE |
| **Gemini** (AI Studio) | Long-context lane, 1M ctx | `gemini-2.5-flash`, `gemini-2.5-flash-lite` | 15 RPM / 1,500 RPD, 1M ctx | **RESTRICTED** (scrubbed content only) |
| **Cloudflare** Workers AI | Optional edge failover (best Morocco RTT) — only if a key exists | `@cf/openai/gpt-oss-120b` | 30 RPM / 1,000 RPD, 131K ctx | SAFE |

Free-tier quotas drift (Groq rotated its catalog 2026-09-14/21) — so **model
names are reconciled against each provider's live `GET /models` at startup**
(`startup_discovery`, live mode only; never in dry-run/tests). A rotated-out
model is never called: the router swaps to the first live model and logs a
warning.

### Tier 4 — `PAID_PREMIUM` (frontier, free-first) · capped

| Provider | Role | Models | Quota | Lane |
|---|---|---|---|---|
| **GitHub Models** (Student Pack) | **Free frontier** — polish & narrative, $0 | `gpt-4o`, `claude-3-5-sonnet`, `gpt-4o-mini` | 15 RPM / 150 RPD, 128K ctx | **RESTRICTED** (logged; no secrets) |
| OpenRouter paid overflow | After the $10 top-up, `anthropic/claude-sonnet-4` as last resort | (last entry in the openrouter preference list) | metered | SAFE |

**Direct OpenAI/Anthropic API keys are no longer required.** The legacy
`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` env vars survive only as a *compatibility
availability signal* for the pre-S5 tests — S5 routing never calls them.

### Registry construction

`build_registry(config)` (`budget/providers.py`) builds the ordered registry
**from `HarnessConfig` fields, never `os.environ` directly** (deterministic
tests). Order = failover preference: local first (free + private), then the
FREE pool, then the PREMIUM frontier. A provider is `enabled` iff its key (or
URL, for local_heavy) is present **and** it has not been opted out via
`HARNESS_DISABLE_<NAME>=1` (`ollama`, `local_heavy`, `groq`, `openrouter`,
`github`, `mistral`, `gemini`, `cloudflare`).

---

## 3. Task-to-Model Routing Matrix (as shipped)

Each entry is a **preferred stop** plus an optional ordered **chain** of
fallback stops. `chain` runs in `route()` after the preferred stop fails.

| Task | Preferred | Chain / special handling |
|---|---|---|
| `scope_regex_gen` | LOCAL / Foundation-Sec-8B | |
| `scope_interpret` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `ideation_frame` | LOCAL / Foundation-Sec-8B | |
| `ideation_deep` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `waf_evasion` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `fp_pattern_check` | LOCAL / Foundation-Sec-8B | |
| `payload_craft` | LOCAL / Foundation-Sec-8B | → Mistral `codestral` → OpenRouter `laguna-s-2.1:free` |
| `payload_polyglot` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `oob_embed` | LOCAL / Foundation-Sec-8B | |
| `js_endpoint_extract` | LOCAL / Foundation-Sec-8B | |
| `secret_detection` | LOCAL / Foundation-Sec-8B | **`local_only`** — source carries secrets, never leaves the machine |
| `source_vuln_scan` | LOCAL / Foundation-Sec-8B | |
| `dataflow_analysis` | LOCAL_HEAVY / `qwen3.8-27b` | → Gemini `gemini-2.5-flash` (RESTRICTED) → OpenRouter `nemotron-3-ultra:free` |
| `deobfuscation` | LOCAL_HEAVY / `qwen3.8-27b` | → Gemini `gemini-2.5-flash` → OpenRouter `nemotron-3-ultra:free` |
| `adaptive_payload_select` | LOCAL / Foundation-Sec-8B | |
| `error_classify` | LOCAL / Foundation-Sec-8B | |
| `dom_xss_confirm` | LOCAL / Foundation-Sec-8B | **`local_only`** |
| `header_anomaly` | LOCAL / Foundation-Sec-8B | |
| `noise_filter` | LOCAL / Foundation-Sec-8B | |
| `self_xss_detect` | LOCAL / Foundation-Sec-8B | |
| `confidence_score` | LOCAL / Foundation-Sec-8B | |
| `vuln_confirm` | PAID_FREE / Groq `gpt-oss-120b` | **two-model consensus** with `qwen3.8-27b` (GPU 27B if LOCAL_HEAVY up, else Groq's free 27B); confirmed only on agreement |
| `idor_matrix_analyze` | PAID_FREE / Groq `gpt-oss-120b` | **two-model consensus** (same rule) |
| `oob_correlate` | LOCAL / Foundation-Sec-8B | |
| `biz_logic_validate` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `ai_jailbreak_confirm` | LOCAL_HEAVY / `qwen3.8-27b` | → Groq `gpt-oss-120b` → OpenRouter `qwen3.8-27b:free` |
| `chain_analysis` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `impact_escalation` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `chain_narrative` | PAID_PREMIUM / GitHub `claude-3-5-sonnet` | → OpenRouter `claude-sonnet-4` (paid, post top-up) |
| `vrt_classify` | LOCAL / Foundation-Sec-8B | |
| `cwe_assign` | LOCAL / Foundation-Sec-8B | |
| `cvss_calculate` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `dispute_prep` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `duplicate_detect` | LOCAL / Foundation-Sec-8B | |
| `triage_decision` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `report_draft` | PAID_FREE / Groq `gpt-oss-120b` | → OpenRouter `qwen3.8-27b:free` |
| `report_polish` | PAID_PREMIUM / GitHub `gpt-4o` | → OpenRouter `claude-sonnet-4` (paid, post top-up) |
| `report_format` | LOCAL / Foundation-Sec-8B | |
| `screenshot_alt_text` | LOCAL / Foundation-Sec-8B | |

**Design notes**

- **LOCAL-first for cheap labour.** ~15 classify/FP/pattern/format tasks never
  leave the box: $0, private, and fast enough at 8B for short prompts.
- **Groq is the free workhorse** for interpretation, payload polyglots,
  validation primaries, triage decisions and report drafts.
- **LOCAL_HEAVY (27B) is elastic overflow, not a permanent backbone** — the
  free `qwen/qwen3.8-27b` on Groq covers most deep-reasoning needs at $0; the
  GPU earns its hour for uncensored HauhauCS profile, >131K context, RPD
  exhaustion, or privacy.
- **PREMIUM is two tasks only** (`report_polish`, `chain_narrative`) and its
  first stop is *free* (GitHub Models Student Pack). Paid overflow activates
  only after the OpenRouter top-up.
- **The consensus pair has no chain** — `vuln_confirm` / `idor_matrix_analyze`
  use `agree_with` (a second opinion), not failover: a finding is CONFIRMED
  only when both models agree; disagreement is logged and the operator decides
  (the war room surfaces the verdict).

---

## 4. Router Decision Flow (two layers)

The router keeps the S2/S3/S4 contract (`resolve_model` / `route`) and adds
provider-level failover on top:

```
route(task_type, prompt)
│
├─ 1. resolve_model()                      # coarse, TIER-based (locked S2 API)
│     preferred tier available?            # LOCAL? LOCAL_HEAVY? PAID_FREE?
│       ├─ yes → (preferred tier, preferred model)
│       └─ no  → walk FALLBACK_CHAIN up-only → TIER_DEFAULTS[fallback tier]
│     nothing up at all → NoBudgetError    # fail-fast, never silent downgrade
│
├─ 2. Build ordered stops                  # fine-grained, provider-level
│     [resolved stop] + [task's explicit chain stops] (deduped)
│     local_only tasks → stops trimmed to LOCAL/LOCAL_HEAVY only
│
├─ 3. SCRUB HARD RULE (compliance.scrub)   # BEFORE any provider is chosen
│     secret pattern in prompt?
│       ├─ yes → re-route to LOCAL stops only (table-local stops first,
│       │        then forced LOCAL default); counter scrub_reroutes += 1
│       │        NO local backend up → NoBudgetError (refuse to send to cloud)
│       └─ no  → continue with the normal stops
│
├─ 4. Walk the stops in order
│     for each (tier, model):
│       find the enabled+available provider hosting the model
│         (configured catalog or live catalog after discovery)
│       reconcile: model rotated out of the live catalog → first live model
│       soft rate limiter (sliding-window RPM/RPD) — over budget? → rotate
│       call the adapter (Ollama / OpenAI-compat / Gemini-native)
│         429 → RateLimited → rotate to next stop
│         other error → ProviderUnavailable → rotate
│       first stop that serves wins
│     all stops failed → NoBudgetError
│
├─ 5. Consensus (vuln_confirm / idor_matrix_analyze only)
│     second model = first up candidate in agree_with
│       (LOCAL_HEAVY 27B when up, else Groq qwen3.8-27b)
│     verdict text → CONFIRM markers (denial markers checked first)
│     agreement = primary_confirms AND agree_confirms
│     result in response.raw["consensus"]; disagreement logged
│     (fail-open: no second model available → primary verdict stands)
│
└─ 6. Billing — TokenTracker.record_usage per provider bucket
      (provider, lane, tier) + separate bucket for the consensus call
      + LOCAL_HEAVY wall-time → GPU-hour meter
```

`resolve_model` is what the dry-run prints and what the budget gate audits;
`route` is what actually executes. **Up-only fallback:** a PAID-preferred task
never silently degrades to LOCAL — the tiers are a quality ladder, and a
PAID_PREMIUM stop with no registry provider fails open to `NoBudgetError` at
call time.

### 4.1 429 rotation

Each provider owns a soft `RateLimiter` (sliding 60 s / 86 400 s windows over
its configured RPM/RPD). When the limiter or a real HTTP 429 fires, `route()`
rotates to the **next stop in the task's chain** — which is deliberately a
*different provider* (Groq → OpenRouter). There is no per-provider
exponential-backoff sleep: the hunt moves on, the 429 is logged, and the
provider's RPD window naturally drains. This is the path Gate S5 item (3)
exercises (`test_gate3_groq_429_rotates_to_openrouter`).

### 4.2 Model discovery

At live startup, `startup_discovery()` calls `GET /models` for every enabled
provider (Ollama: `GET /api/tags`) and stores `live_models`. Fail-open: any
failure keeps the configured preference list. `resolved_models()` then
prefers configured names that are still live and, if a whole catalog rotated
out, falls back to the first live model — **never a crash, never a dead name**.

### 4.3 Consensus detail

`_verdict_confirms()` is a heuristic marker scan — denial markers
(`NOT CONFIRMED`, `FALSE POSITIVE`, `NO_BUG`, …) are checked **first**
because "NOT CONFIRMED" contains the substring "CONFIRMED". `agreement` is
strict AND: either model not confirming ⇒ not confirmed. The consensus partner
call is billed into its own tracker bucket (`<task_id>_consensus`).

---

## 5. Budget & Cost Model (S5.7)

### 5.1 Per-call accounting

- Every `route()` records **per-provider** usage (input/output tokens, model,
  provider, lane, tier) into `TokenTracker` — the war room's Budget panel
  shows the `per_provider` buckets live.
- `LOCAL_HEAVY` calls additionally meter **GPU-hours** from wall time
  (`elapsed / 3600 × hourly_cost`) — GPU time is excluded from the $0.50
  session projection and shown on its own meter.
- The session budget line is **$0.50** (`budget_line_usd`);
  `project_standard_session()` projects a standard hunt and raises
  `budget_warning` events on approach.

### 5.2 Expected costs

| Scenario | Cost |
|---|---|
| Standard 8-h session, GPU off, free pool + local | **$0.00** |
| Heavy hunt, GPU on 8 h (4090, RunPod EU) | ~$2.80–$3.60 |
| Polish/narrative (GitHub Models free) → OpenRouter paid overflow | ~$0.05–$0.30 |
| Fixed: OpenRouter $10/month top-up (1,000 RPD free quota + paid failover headroom) | $10 |
| **Fixed monthly** | **$10** |
| **Projected monthly (20 sessions, GPU ~4 h)** | **~$11–15** |

(Compare the old single-Groq model at ~$3.00/mo — the delta buys 27B-class
deep reasoning, two-model confirmation, and free frontier polish.)

**No consumer subscriptions** ($20/mo Claude/ChatGPT/Kimi): subscriptions grant
app access, not API quota, and would overlap GitHub Models + OpenRouter.
Revisit only if the free frontier quota proves insufficient for report volume.

---

## 6. Data Lanes & the Scrub Hard Rule (S5.3)

- **SAFE lane** — may carry scope, endpoints, findings: LOCAL, LOCAL_HEAVY,
  Groq, OpenRouter, Mistral (post data-opt-out), Cloudflare.
- **RESTRICTED lane** — scrubbed, non-sensitive content only: **Gemini**
  (free-tier prompts are logged/trained in some regions) and **GitHub Models**
  (logged).
- **Hard rule, all lanes:** no credentials, secrets, or tokens in any LLM
  prompt. `compliance.scrub.scrub()` runs on every prompt *before* routing;
  on a match the prompt is re-routed to the local sink (table-local LOCAL /
  LOCAL_HEAVY stops first, then the forced LOCAL default), the
  `scrub_reroutes` counter increments, and the result carries
  `raw["scrub_rerouted"]`. **If no local backend is up, the call is refused
  outright** — a secret never goes to the cloud.
- **`local_only` tasks** (`secret_detection`, `dom_xss_confirm`) never leave
  the machine regardless of scrub outcome — their source material is
  secret-bearing by definition.

Patterns (high-precision, a conservative superset of truffleHog/gitleaks-style
rules): OpenAI `sk-`/`sk-proj-`, Anthropic `sk-ant-`, HuggingFace `hf_`,
Groq `gsk_`, GitHub `gh*_`/`github_pat_`, npm registry tokens, AWS `AKIA…`,
Google `AIza…`, Slack `xox…`, Telegram bot tokens, Azure connection strings,
Stripe `sk_live_`/`rk_live_`, Twilio `SK…`, SendGrid `SG.…`, private-key
blocks, JWTs, and a generic `api_key|secret|token|… = <high-entropy value>`
rule. Keyword-only hits are deliberately **not** flagged (a SQLi payload that
contains the word "token" must not be blocked).

---

## 7. Configuration

Keys live only in the gitignored `.env` (see `OPERATIONS.md` §6); the registry
is built from `HarnessConfig` fields:

| Config field | Provider | Enables |
|---|---|---|
| `ollama_url` (default `http://127.0.0.1:11434`) | ollama | `LOCAL` tier |
| `local_heavy_url` (+ optional `local_heavy_api_key`, `local_heavy_hourly_cost`) | local_heavy | `LOCAL_HEAVY` tier (OFF unless URL set) |
| `groq_api_key` | groq | FREE primary |
| `openrouter_api_key` | openrouter | FREE failover + paid overflow |
| `mistral_api_key` | mistral | FREE code lane |
| `gemini_api_key` | gemini | FREE long-context (RESTRICTED) |
| `github_token` | github_models | PREMIUM free frontier (RESTRICTED) |
| `cloudflare_account_id` + `cloudflare_api_token` | cloudflare | FREE edge failover |
| `HARNESS_DISABLE_<NAME>=1` | any | explicit per-provider opt-out |

The **Ollama-only** config is the zero-spend floor: with no paid keys set, the
S4.3 invariant still holds — no task can ever resolve to a paid tier (paid-
preferred tasks fail fast with `NoBudgetError`). The dry-run and the whole
test suite run with zero keys.

---

## 8. Observability (war room, S7)

The dashboard at `http://127.0.0.1:8001/` (served same-origin by
`orchestrator.admiral.create_app`) visualizes this routing layer live:

- **Model Routing panel** — `GET /api/v1/providers`
  (`ModelRouter.provider_status()`): per provider — tier, lane badge
  (SAFE/RESTRICTED), state (up / down / disabled, from `enabled` +
  `available`), key presence (bool only — **raw keys never rendered**),
  configured vs live catalog (drift ⚠ when a configured model rotated out),
  RPM/RPD limits, context window, GPU-hour cost.
- **Lanes panel** — the RESTRICTED re-route counter
  (`ModelRouter.scrub_reroutes`, incremented by the scrub hard rule) plus
  lane membership.
- **Budget panel** — per-provider token/cost buckets, the GPU-hour meter, and
  the $0.50 session projection.
- **Operator controls** — `POST /api/v1/halt` / `/api/v1/resume` (idempotent
  kill switch; emits `hunt_halted`/`hunt_resumed` on the triage topic) and
  per-finding confirm/reject.

---

## 9. Pending live verification (S5b)

S5a shipped keyless and mock-tested (Gate S5 items 1, 3–6 in
`tests/test_s5_router.py`). **S5b** — strictly after the operator's **$10
OpenRouter top-up** — verifies the live path: one real 200 per enabled
provider (logged with provider/tier/lane) + a live `GET /models` re-check of
every enabled catalog. Until then the configured quotas above are the 2026-10
figures and must be re-verified live (free tiers drift).
