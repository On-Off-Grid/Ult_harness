# ULT_HARNESS — Surgical Restart Plan v3.0

**Date:** 2026-10-15
**Status:** APPROVED — executing. S0 (salvage), S1 (component restoration), S2 (control-plane trust audit), S3 (the brain), **S4 (end-to-end integration)** complete 2026-10-15/16 (commits `394bc29`, `c95b967`, S2 in `198004c`+ / `cc48240`, S3 in the following commit, S4 in the subsequent commit). S4 delivered: component-side wiring 4.6–4.12 (all env-gated + fail-open, recorded in `patches/local-tweaks.md` §7) + the S4.1–S4.3 E2E gates (`tests/test_s4_e2e.py`, 5 tests incl. a live-Ollama round-trip). **S6 (documentation & handoff)** complete 2026-10-16: `OPERATIONS.md` (canonical entry point — a fresh session runs the S4.1 dry-run from it alone), `pyproject.toml` → 3.0.0, `CREDITS.md` pin commits, STORM-HUNT archived to `docs/reference/storm-hunt/`, umbrella `Vibe_coded/README.md` row synced; `model_routing_guide.md` + the v2.1.2 Qwen-spec routing section carry supersession banners (the full guide rewrite is the S5 deliverable). **S5 (model-router redesign) is DONE** — S5a (build, keyless, mock-tested) + **S5b (live per-provider verification, PASS 2026-10-17, post the operator's $10 OpenRouter top-up)**: 5/6 enabled providers returned a live 200 (logged per provider/tier/lane) + paid overflow resolved; `github_models` reported UNVERIFIABLE (upstream retired 2026-07-30, not a code defect). Key rotation was *closed*: the 4 free-tier keys live only in gitignored `.env`. S7 (war-room dashboard) is DONE (the S7.4 browser-visual smoke is the one remaining manual step). S2 verdict: all 9 areas GREEN after 6 in-place bug fixes (F1–F6) — see `docs/trust_audit.md`. Test suite: **239 tests** in `tests/` (154 S2–S4 baseline + 25 S5 gates + 20 S7 + 5 S5b regression + 23 S8.1 OOB + 12 S8.2 empty-content guard). **Phase S8** — "from verified to operational" (real OOB correlation + the reasoning-model empty-content guard + housekeeping, then the first live hunt) — is added at the end of this plan as the next phase; **S8.1 (OOB correlation), S8.2 (empty-content guard), and S8.3 (housekeeping) are DONE; S8.4 (first live hunt) + S8.5 (visual smoke) remain**. The control plane is proven to *run* but not yet to *hunt*.
**Workspace (canonical):** `/home/souhail/Desktop/Desktop/PORTFOLIO/Vibe_coded/Ult_harness`
**Supersedes:** `specs/assembly_plan.md` (v2.1.1, mojibaked), `specs/implementation_guide.md` (v2.1.1 snapshot, mojibaked)
**Predecessor (still valid):** `bug_bounty_harness_design_v2_1.md`, v2.1.2 specs, `harness_gap_bridging_specification_v2_1_2.md`, `progress_report.md`

---

## 0. Decision record

**Chosen strategy: surgical restart — keep verified-worthkeeping code, replace the plan, verify before trusting.**
Rejected: (a) full fresh start (destroys unreproducible assets: tuned prompts, compliance layer, spec corpus, divergent fork commits), (b) blind continuation of v2.1.1 plan (its "DONE" checkboxes are fiction — components weren't even on disk).

**Standing rule for all phases:** *no module is considered done until a test or command proves it runs.* Old-doc claims are inputs to doubt, not to trust.

---

## Phase S0 — Safe salvage (do FIRST, before anything else)

At-risk work that is not in any git repo today:

| # | Action | Why |
|---|---|---|
| S0.1 | Tag current `main`: `git tag v2.1.2-baseline` in Ult_harness | Frozen checkpoint; nothing after S0 is irreversible |
| S0.2 | For each divergent fork (`On-Off-Grid/Agent-Reach`, `claude-bug-bounty`, `jsleak`): clone into `/tmp`, `git diff <upstream-main>...<fork-main>` → save to `patches/forks/<name>.patch` + record commit SHAs in `patches/README.md` | Fork commits are the only copy of pushed modifications |
| S0.3 | In `~/Desktop/Desktop/adhd`: create branch `local-rename`, commit the uncommitted `package.json`/`package-lock.json` rename (`connect-dots` → `adhd-agent`), push to `On-Off-Grid/adhd` | Uncommitted = one `rm -rf` from gone |
| S0.4 | Quarantine mojibake docs: move `specs/assembly_plan.md` + `specs/implementation_guide.md` → `specs/archive/` (keep as record of the incident); the committed top-level `implementation_guide.md` (clean encoding) remains the historical guide of record | Corrupted files must not be mistaken for canonical |
| S0.5 | Revert the stray edit in `Vibe_coded/harness/docs/operator/03-current-state-and-roadmap.md` (wrong project, made 2026-10-15) | Hygiene |
| S0.6 | Fix version: `pyproject.toml` 2.1.1 → 2.1.2 | Drift vs. design line |
| S0.7 | **Inventory the AMD Developer free pack** (what it grants: cloud GPU hours? which instances?) → record in `docs/provisioning.md`; if it yields free GPU, it becomes the $0 LOCAL_HEAVY host (see S5.5/D3) | $0 heavy tier, if available |
| S0.8 | **Free-provider setup pass:** create/confirm API keys for Groq, OpenRouter (+ apply the $10 top-up), GitHub Models (auth via GitHub PAT — Student Pack entitlement), Mistral (**opt OUT of data training in the console**), Google AI Studio (confirm free-tier region eligibility) → all keys into `.env` (gitignored), never in git | Prerequisite for S5 |
| S0.9 | **Verify local models loaded:** `ollama list` shows `dr-ry/Foundation-Sec-8B-Instruct:Q4_K_M` and `qwen2.5:7b`; one smoke call to each | LOCAL_LIGHT readiness |
| S0.10 | **Commit this v3 plan into the repo** as `specs/assembly_plan_v3.md` (clean UTF-8) + update `Vibe_coded/README.md` pointer + stage umbrella submodule bump for the operator to commit | Per decision 6 |

**Gate S0:** `git tag -l` shows `v2.1.2-baseline`; `patches/forks/` has 3 non-empty patch files; adhd fork main contains the rename commit; `docs/provisioning.md` records AMD pack contents + all 5 free-provider keys present in `.env`; both local models answer a smoke call; `specs/assembly_plan_v3.md` committed.

---

## Phase S1 — Component restoration

The 8 third-party components are gitignored by design (`fetch_components.sh`); 7 of 8 are absent from disk.

| # | Action |
|---|---|
| S1.1 | Run `./scripts/fetch_components.sh` from repo root |
| S1.2 | For `Agent-Reach`, `claude-bug-bounty`, `jsleak`: apply the S0.2 fork patches (fork version takes precedence over stock upstream — it may contain the harness wiring) |
| S1.3 | Re-apply Phase-4.5 adhd tweak: add the 6 security frames (`recon_diverge`, `payload_mutate`, `chain_explore`, `auth_bypass`, `waf_evasion`, `business_logic_abuse`) to `adhd/src/frames.ts` per `specs/adhd_spec.md` + `specs/adhd_SOURCE-SPEC.md`; re-apply the `package.json` rename from S0.3 |
| S1.4 | Re-apply remaining v2.1.2 component tweaks listed in `progress_report.md` §Phase 4 (4.6–4.12: mempalace backends, T3MP3ST, CL4R1T4S, Agent-Reach egress hooks) per their respective `specs/*_spec.md` |
| S1.5 | Record every applied modification in a new `patches/local-tweaks.md` (file, line range, purpose) so the next restart is a script, not archaeology |

**Gate S1:** all 8 component dirs present; `git status` in each component shows only the modifications listed in `patches/local-tweaks.md`; each component's own entry point runs (e.g. `adhd` CLI `--help`, jsleak `--help`, Agent-Reach importable).

**Note:** `T3MP3ST` and `CL4R1T4S` (elder-plinius) and `mempalace` (MemPalace) have no On-Off-Grid forks — stock upstream + re-applied tweaks is all that's recoverable. If upstream repos have changed since Sep 2026, pin to the commit recorded in `CREDITS.md`/specs.

---

## Phase S2 — Control-plane verification (trust audit)

Existing ~3,500 lines are **unverified**. Classify, don't assume.

| # | Package | Smoke test to write | Verdict options |
|---|---|---|---|
| S2.1 | `core/` (types, config, event_bus) | import + instantiate + publish/subscribe round-trip | GREEN / RED |
| S2.2 | `compliance/scope_gate.py` | in-scope URL passes, out-of-scope rejected, scope-import from a sample program JSON | GREEN / RED |
| S2.3 | `compliance/egress_proxy.py` | replay the 20-line `workspace/default-wing/logs/egress_proxy.jsonl` as fixture; assert block/allow decisions | GREEN / RED |
| S2.4 | `compliance/header_injector.py` + `oob_engine.py` | header injection on sample request; OOB callback recorded to log | GREEN / RED |
| S2.5 | `budget/model_router.py` + `token_tracker.py` | tier routing table correct (LOCAL_LIGHT → LOCAL_HEAVY → PAID_FREE → PAID_PREMIUM); ledger math | GREEN / RED |
| S2.6 | `triage/noise_filter.py` + `state_machine.py` | known-FP sample filtered; finding state transitions legal-path only | GREEN / RED |
| S2.7 | `sessions/session_manager.py` | create/resume/expire lifecycle | GREEN / RED |
| S2.8 | `agents/` (16 specialists + base + dual-session) | all prompts parse (frontmatter valid, model field resolves, no dangling tool refs) | GREEN / RED |
| S2.9 | `scripts/ingest_*.py` | dry-run against a sample corpus with mempalace present (S1 done) | GREEN / RED |

RED modules: rewrite in place (same interface) or mark for S3 rebuild. Log every verdict in `docs/trust_audit.md`.

**Gate S2:** `pytest -q` green on everything marked GREEN; every RED has a disposition (rewritten or scheduled in S3); `docs/trust_audit.md` complete.

---

## Phase S3 — Build the missing core (the actual "brain")

Everything downstream of the control plane that doesn't exist yet:

| # | Deliverable | Spec source |
|---|---|---|
| S3.1 | `orchestrator/admiral.py` (OpAdmiral) — task dispatch to specialists, budget-aware model selection via `budget/model_router`, dual-session validation hook, kill-switch on scope violations (via `compliance/scope_gate` callbacks) | design v2.1 §orchestration, `workflow_overview.md` |
| S3.2 | `reporting/` — platform-specific report writers (hackerone, intigriti, yeswehack) fed only by CONFIRMED/chained findings from `triage/state_machine` | design v2.1 §reporting |
| S3.3 | `main.py` — CLI entry: `--target <scope-file> --dry-run` / live mode; wires config → compliance → admiral → reporting → mempalace write-back | implementation guide Phase 5 |
| S3.4 | Rewrite any S2-RED modules here | trust audit |

**Status: ✅ COMPLETE 2026-10-15.**
- **S3.1** `orchestrator/admiral.py` — `OpAdmiral` core (pure-Python, fastapi-free) + lazy `create_app()` REST/WS surface (12 routes at S3, 16 after S7 added the war-room routes, verified against `.venv` fastapi 0.141). Gap-spec blueprint constructor mismatches corrected against S2-verified signatures (`TokenTracker(event_bus, default_budget)`, `ScopeGate(target_scope)`, `SessionManager(auth_config, …)`). Harness side of 4.6/4.7 shipped: `record_tokens()` → `/api/tokens/record`, `route_llm_request()` → `/api/v1/llm/route`. Kill switch: 3 scope violations → hunt halted.
- **S3.2** `reporting/taxonomy.py` (all 16 `VulnCategory` → VRT/CWE/CVSS 3.1) + `reporting/writers.py` (CONFIRMED/CHAINED-only gate via `ReportGateError`; H1/Intigriti/YWH tailored, BC/Immunefi generic; `workspace/<wing>/reports/`).
- **S3.3** `main.py` — `init` / `run [--dry-run]` / `stop`. Operator `--platform` is authoritative over importer-stamped platform. Live mode: mitmdump spawn + uvicorn + optional session bootstrap. Optional `.env` loader (python-dotenv, non-fatal).
- **S3.4** N/A — no S2-RED modules remained.
- **Gate S3: PASS** — `python main.py --help` OK; `init` + `run --dry-run` on a sample Bugcrowd-JSON scope walks config→gate→admiral→report→memory end-to-end (locked by `tests/test_s3_main.py` subprocess tests). 45 new S3 tests, 149 total green.

**Gate S3:** `python main.py --help` works; `--dry-run` on a sample scope file walks the full graph (config→gate→admiral→report→memory) with mocked component calls.

---

## Phase S4 — End-to-end integration loop

| # | Test | Status |
|---|---|---|
| S4.0 | **Component-side wiring (carry-over from S3 per `patches/local-tweaks.md` §6):** 4.6 adhd `engine.ts` token-callback POST `:8001/api/tokens/record` + FP query `:8000/search`; 4.7 cbb `agent.py` LLM via POST `:8001/api/v1/llm/route`; 4.8 cbb `engine.py` `HTTP(S)_PROXY` injection; 4.9 cbb `brain.py` mempalace `cl4r1tas_prompts` query; 4.10 cbb `memory/*` → MemPalace REST; 4.11 cbb `scope_checker` deprecation → ScopeGate; 4.12 jsleak `HTTP_PROXY` + `-json` | ✅ 2026-10-16 — all 7 applied, env-gated + fail-open, verified (tsc/py_compile/go build + live fake-harness); recorded in `patches/local-tweaks.md` §7 |
| S4.1 | Scope import → gate enforcement → recon dispatch (mocked specialist, local model) → triage → noise filter → state machine → report draft → write-back to mempalace | ✅ 2026-10-16 — `tests/test_s4_e2e.py::TestS41FullDryRun`; recon dispatched via `_MockSpecialist` (a real Agent-Reach live run is operator-side, needs a live target) |
| S4.2 | Negative test: out-of-scope request MUST be blocked by egress proxy and logged | ✅ 2026-10-16 — `tests/test_s4_e2e.py::TestS42EgressBlocksAndLogs` (403 + JSONL drop record) |
| S4.3 | Budget test: run with Ollama-only → zero paid-tier calls recorded by `token_tracker` | ✅ 2026-10-16 — `tests/test_s4_e2e.py::TestS43OllamaOnlyBudget`; invariant = **no task ever resolves to a PAID tier** (LOCAL-preferred → LOCAL; PAID-preferred → fail-fast `NoBudgetError`), zero-cost, reconciled ledger + live Ollama round-trip |

**Gate S4 — PASS (2026-10-16):** one full dry-run on a legitimate sample target with local models walks the entire graph (scope gate → model route → dispatch → triage → noise filter → report → mempalace write-back) with the report landing on disk, platform-tailored; the out-of-scope egress negative test blocks + logs; the Ollama-only budget test proves no task can reach a PAID tier and the ledger reconciles at zero cost. S4.0 component tweaks recorded in `patches/local-tweaks.md` §7. Test suite: **154 tests** (149 baseline + 5 S4 gates). Open shim gap documented (mempalace `:8000` REST surface is best-effort/fail-open; the on-disk mempalace has no confirmed REST API).

---

## Phase S5 — Model routing & gateway redesign (2026-10-15 reassessment)

> Supersedes the old Phase 7 and the v2.1.2 Qwen spec's routing section. Sources: OpenRouter free-API comparison (verified 2026-09-24) + mnfst/awesome-free-llm-apis (Oct 2026). Free tiers drift (Groq rotated its catalog 2026-09-14/21) — the router must discover models at runtime, not trust hardcoded names.

### S5.1 — New tier structure

| Tier | Backend | Cost | Role |
|---|---|---|---|
| **LOCAL_LIGHT** | Ollama laptop, RTX 4050 6GB: **`dr-ry/Foundation-Sec-8B-Instruct:Q4_K_M` (primary resident — security-tuned)** + `qwen2.5:7b` fallback + optional `qwen2.5-coder:3b` for bulk classification | $0 | High-volume classify/regex/payloads/FP filtering; privacy-safe; security domain pretraining |
| **LOCAL_HEAVY** | **Qwen3.8-27B on cloud GPU** — **RunPod EU (Paris/NL), 4090 24GB community/spot**, `llama-server` OpenAI-compatible **with `--api-key`** over Tailscale; first check AMD Developer pack free GPU hours for a $0 host | Pay-per-hour only while up (~$0.34–0.45/hr) | Uncensored deep reasoning, 262K context, zero third-party visibility |
| **FREE** | Multi-provider pool (S5.2) | $0 | Bulk workhorse with per-provider rate limits + failover |
| **PREMIUM** | OpenAI/Anthropic | Capped ($0.50/session) | `report_polish`, `dispute_prep`, `chain_narrative` only |

**Key 2026 finding:** Groq serves `qwen/qwen3.8-27b` **free** (30 RPM / 1,000 RPD, 131K ctx, 16K max output). The cloud GPU is therefore **elastic overflow**, not a permanent backbone. Justification for spinning it up: uncensored HauhauCS profile (Groq = stock), >131K context, RPD exhaustion on heavy hunts, or privacy.

### S5.2 — Free provider pool (permanent tiers, no credit card)

Provider pool for **this operator** (confirmed accounts; 2026-10 quotas — re-verify live at S5 gate):

| Provider | Free quota (2026-10) | Role in v1 | Models to use | Lane |
|---|---|---|---|---|
| **Groq** | 30 RPM / 1,000 RPD | **Primary FREE** (fastest; EU endpoints ≈ 30–60 ms from Morocco) | `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` (the free 27B!), `openai/gpt-oss-20b` | SAFE (no training) |
| **OpenRouter** (free + $10/mo) | 20 RPM; **1,000 RPD on `:free` models once top-up applied** | **Resilience/failover layer** (routes to many providers; best EU/latency failover) | `qwen/qwen3.8-27b:free` (262K ctx), `nvidia/nemotron-3-ultra:free` (1M), `poolside/laguna-s-2.1:free` (code) | SAFE (no training); top-up paid failover = provider cost + 5.5% |
| **GitHub Models** (Student Pack) | 15 RPM / 150–1,000 RPD | **FREE frontier** for polish/narrative + paid-tier fallback | `gpt-4o`, `claude-3-5-sonnet`, `gpt-4o-mini` | RESTRICTED (logged; no secrets) |
| **Mistral** (free) | ~$10/mo credits, 256K ctx | **Code lane** (Codestral) after data opt-out | `codestral`, `mistral-small-4`, `ministral-3-14b` | SAFE after console opt-out (opt out at S0) |
| **Google AI Studio** (free) | Flash 15 RPM / 1,500 RPD; Pro 5 RPM / 50 RPD | **Long-context lane** (1M ctx) | `gemini-2.5-flash`, `gemini-2.5-flash-lite` (30 RPM) | RESTRICTED (trains on prompts — operator is likely EEA-exempt; confirm region at S0, else keep RESTRICTED) |
| **AMD Developer pack** | **Unknown — inventory at S0** | If it grants cloud GPU hours (ROCm/MI-series or partner credits) → **$0 LOCAL_HEAVY host**, ahead of RunPod | TBD (27B Q4_K_P or equivalent) | SAFE (self-hosted) |
| Cloudflare Workers AI | 10K neurons/day | Optional edge failover (best latency from Morocco — massive North Africa edge) | `@cf/openai/gpt-oss-120b` | SAFE — **add only if a key is created** (not in confirmed accounts) |

Rejected: Cohere (non-commercial only), ModelScope + SiliconFlow (real-name verification friction), HuggingFace inference (~$0.10/mo credits — negligible; HF is used only for *downloading* the local GGUF, not inference), Kilo gateway ("may route to providers that log"), Cerebras/NVIDIA NIM (not in operator's confirmed accounts — keep as documented options, not v1 config).

> **Latency note (Morocco):** all chosen providers have EU endpoints or global CDN (Groq, OpenRouter, GitHub/Azure West-EU, Mistral EU, Cloudflare). Groq + OpenRouter + Cloudflare give the lowest RTT from Morocco. Free-tier availability is region-gated for some providers (Google) — S0 confirms the operator's quota page shows the free tier is active in their region.

### S5.3 — Data-lane enforcement (new compliance requirement)

- **SAFE lane** (may carry scope/endpoints/findings): LOCAL_LIGHT, LOCAL_HEAVY, Groq, Cerebras, Cloudflare, OpenRouter, Mistral-after-opt-out.
- **RESTRICTED lane** (scrubbed, non-sensitive content only): Gemini, NIM, GitHub Models.
- **Hard rule, all lanes:** no credentials/secrets/tokens in any LLM prompt. Router runs a pre-call scrub hook (reuse jsleak/secret patterns); on detection → refuse + re-route to LOCAL/LOCAL_HEAVY.
- Every routing entry declares its lane; the router refuses tier→lane violations.

### S5.4 — Router reimplementation (replaces single-Groq `model_router.py`)

1. **Provider registry** (dataclass): base_url (OpenAI-compatible), key env, model list, RPM/RPD, context, lane, hourly cost (LOCAL_HEAVY only).
2. **One generic OpenAI-compatible adapter** (replaces `_call_groq`/`_call_openai`/`_call_anthropic` triplication) + one **Gemini native adapter**.
3. **Per-provider async token-bucket rate limiters** + 429 → exponential backoff → rotate to next provider in failover chain.
4. **Runtime model discovery** (`GET /models` at startup) reconciled against preference lists — free catalogs rotate (proven: Groq 2026-09-14/21).
5. **Revised routing table** (delta vs. current):
   - `vuln_confirm`, `idor_matrix_analyze`: **two-model agreement** — Groq `gpt-oss-120b` AND 27B (GPU if up, else Groq `qwen/qwen3.8-27b`); finding is "confirmed" only on agreement.
   - **LOCAL_LIGHT default = `Foundation-Sec-8B:Q4_K_M`** (security-tuned) for all classify/FP/error/pattern tasks; `qwen2.5:7b` fallback; `qwen2.5-coder:3b` (pull if needed) for max-throughput bulk `noise_filter`/`error_classify`.
   - `dataflow_analysis`, `deobfuscation` (long context): LOCAL_HEAVY → Gemini Flash 1M (RESTRICTED, scrubbed) → OpenRouter `nemotron-3-ultra:free` 1M.
   - `secret_detection`, `dom_xss_confirm`: **LOCAL-only** (source contains secrets; never leaves the machine).
   - `payload_craft`: LOCAL_LIGHT → `codestral` (Mistral, opt-out done) → `poolside/laguna-s-2.1:free` (OpenRouter).
   - `report_polish`, `chain_narrative`: **GitHub Models free GPT-4o/Claude Sonnet → OpenRouter paid (post-$10-top-up) fallback** — PREMIUM direct OpenAI/Anthropic keys are no longer required at all.
   - All other entries keep their v2.1 task assignments with model names updated to the live 2026 catalog (discovered at startup, never hardcoded as sole source of truth).
6. **TokenTracker**: per-provider usage buckets + GPU-hour bucket for LOCAL_HEAVY + cost projection + `budget_warning` events.

### S5.5 — Cloud GPU deployment (Profile F, on-demand)

- Provider: **RunPod, EU region (Paris/Netherlands) — 4090 24GB community/spot** (~$0.34–0.45/hr; best Morocco latency + price). L40S 48GB (~$0.80–1.20/hr) only if a hunt needs >32K resident context or FastMTP headroom. **If the AMD Developer pack (D3) grants GPU hours, use that host first at $0.**
- Serve: `llama-server` + Qwen3.8-27B **Q4_K_P** (17.9 GB) (+ optional HauhauCS FastMTP sidecar); `--api-key <key>`; `--ctx-size 32768` (4090) / 65536 (L40S).
- **Security:** key-auth required; reach it over VPN/private endpoint (Tailscale/WireGuard or cloud private networking), **never** a public unauthenticated port; egress proxy treats it as internal (no scope enforcement on the call itself, per v2.1.2 spec §Security).
- Lifecycle: start at hunt begin, stop at hunt end (cost = hours × rate); OpAdmiral may gate activation on wing expected value vs. `local_heavy_hourly_cost`.

### S5.6 — Config additions (`core/config.py` / `HarnessConfig`)

`local_heavy_url`, `local_heavy_api_key`, `local_heavy_hourly_cost`, `gemini_api_key`, `mistral_api_key`, `openrouter_api_key`, `nvidia_api_key`, `cerebras_api_key`, `cloudflare_account_id`, `cloudflare_api_token`, `github_token`, per-provider `enabled` flags. Keys from env (`.env`, gitignored) — **never in git**.

> **Status (2026-10-17):** split into **S5a (build, mock-tested, keyless)** and **S5b (live verification, needs the OpenRouter $10 top-up).** **S5a is DONE** — commits `9d6101e` (S5a.1 config), `0c395a4` (S5a.2 registry+adapters+scrub+tracker), `1456711` (S5a.3 router + S5 gate tests). **S5b is DONE (PASS, 2026-10-17, post top-up)** — live 200s from all five verifiable providers + paid overflow resolved; `github_models` reported UNVERIFIABLE (upstream retired 2026-07-30). Suite at **204 passed** (199 baseline + 5 S5b regression gates). Live run: `scripts/s5b_live_verify.py` (re-runnable; free-provider $0 + one ~$0.003 paid probe).

### S5.8 — Gate S5 status

**Gate S5:** (1) router resolves every routing-table entry to a live provider (dry-run with mocked calls); (2) one real call per enabled provider returns 200 and is logged with provider/tier/lane; (3) 429 simulation rotates to the next provider; (4) scrub hook blocks a prompt containing a fake API key on RESTRICTED providers and re-routes it to LOCAL; (5) token tracker shows per-provider buckets; (6) cost projection for a standard session ≤ $0.50 excluding optional GPU hours.

- **S5a (mocked, keyless) — PASS.** Items (1) `test_gate1_table_integrity_full_config`; (3) `test_gate3_groq_429_rotates_to_openrouter` + `test_all_stops_429_raises_no_budget`; (4) `test_gate4_*` (incl. RESTRICTED gemini + scrub-refusal); (5) `test_gate5_per_provider_buckets`; (6) `test_gate6_standard_session_projection_within_budget`. Plus LOCAL_HEAVY toggle, two-model consensus, discovery fail-open, Ollama-only never-paid. All in `tests/test_s5_router.py` (HTTP injected via `ModelRouter._http`, registry from `HarnessConfig`).
- **S5b (live, post top-up) — PASS (2026-10-17).** Item (2) one real 200 per enabled provider logged with provider/tier/lane + a live `GET /models` re-check of every enabled catalog — run via `scripts/s5b_live_verify.py` against the operator's real `.env` keys (the $10 OpenRouter top-up landed first). Result: **5/6 enabled providers returned a live 200** — `ollama` (LOCAL/SAFE), `groq` `openai/gpt-oss-120b` (PAID_FREE/SAFE), `openrouter` `nvidia/nemotron-3-ultra-550b-a55b:free` (PAID_FREE/SAFE), `mistral` `codestral-latest` (PAID_FREE/SAFE; the primary `mistral-small-latest` was per-model 429-throttled and rotated within the provider), `gemini` `gemini-3.1-flash-lite` (PAID_FREE/RESTRICTED). The **paid overflow `anthropic/claude-sonnet-5.5` resolved** (live-catalog membership + a real paid 200 post top-up). End-to-end `router.route("triage_decision")` → groq/PAID_FREE/SAFE `'CONFIRMED'` with the per-provider tracker bucket logged. `github_models` is **UNVERIFIABLE, not a code defect**: the GitHub Models inference service (the `ghp_` PAT endpoint) was **retired upstream 2026-07-30** (docs.github.com); the surviving Copilot OpenAI-compat surface `api.githubcopilot.com` requires an IDE OAuth token, not a classic PAT. It stays registered so the PAID_PREMIUM tier + `chain_narrative`/`report_polish` keep resolving; the chain's OpenRouter paid stop serves whenever it 401s.

  **S5b live findings (all fixed + locked by the 5 new regression tests in `tests/test_s5_router.py`):**
  1. **2026 free-tier ID drift** — `qwen/qwen3.8-27b:free` + `nvidia/nemotron-3-ultra:free` rotated out of the OpenRouter `:free` pool (16 remain); `codestral` + `ministral-3-14b-latest` rotated out of Mistral; `gemini-2.5-flash(-lite)` is account-deprecated (404 "no longer available to new users"). Router constants + registry + `MODEL_COSTS` re-pointed to the live IDs (verified via live `GET /models` + real 200s).
  2. **`discover_models` parser bug** — Gemini's native `GET /models` returns `{"models":[{"name":"models/<id>"}]}`; the old code `str(dict)`'d the entries, so `live_models` became dict-strings and `resolved_models()` "called" a model named `"{'name': ...}"` → 404. Parser now handles OpenAI-compat `data`/`id`, Gemini-native `models`/`name` (prefix stripped), and bare name lists.
  3. **`default_http` sent a JSON body on GET** — `json={}` adds a `Content-Type: application/json` body that Groq/Gemini reject with 400, so discovery silently failed open and drift went unseen. GETs now go bodyless.
  4. **Placeholder keys advertised fake-enabled providers** — `core/config.py` `_clean_key()` normalizes `ghp_REPLACE_ME`-style values to unset, so a half-filled `.env` can no longer enable a provider.
  5. **Reasoning-model `max_tokens` note (production, not a gate failure)** — `openai/gpt-oss-120b` (Groq primary) and the nemotron `:free` models spend ~100 tokens on reasoning before emitting `content`; small budgets (8/32) return 200 with **empty content**. The live probes use `max_tokens=160`; the `nemotron-550b:free` free pool additionally flaked to empty bodies on 200s (the verified dependable `:free` workhorse is `poolside/laguna-s-2.1:free`). Sizing per-task `max_tokens` past the reasoning budget for reasoning primaries is an open follow-up.

### S5.7 — Expected cost model (replaces `model_routing_guide.md` §5)

| Scenario | Cost |
|---|---|
| Standard 8-h session, GPU off, free pool + local | **$0.00** |
| Heavy hunt, GPU on 8 h (4090, RunPod EU) | ~$2.80–$3.60 |
| Polish/narrative (GitHub Models free) → OpenRouter paid overflow | ~$0.05–$0.30 |
| Fixed: OpenRouter $10/month top-up (1,000 RPD free quota + paid failover headroom) | $10 |
| **Fixed monthly** | **$10** |
| **Projected monthly (20 sessions, GPU ~4 h)** | **~$11–15** (vs. ~$3.00/mo old model, but with 27B-class deep reasoning, 2-model confirm, and free frontier polish) |

Subscription comparison (why no $20/mo Claude/ChatGPT/Kimi): consumer subscriptions grant **app access, not API quota** — the router needs key-authenticated API endpoints. GitHub Models (Student Pack) already gives free GPT-4o + Claude Sonnet API calls; OpenRouter covers the rest. A $20 subscription would be pure overlap. Revisit only if free frontier quota (GitHub Models RPD) proves insufficient for report volume.

---

## Phase S6 — Documentation & handoff

- ✅ Single canonical `OPERATIONS.md`: what exists, what's verified (per trust audit), how to run, known gaps. (Delivered 2026-10-16; the S4.1 dry-run command it documents was verified end-to-end from a clean temp dir.)
- ⏳ **Rewrite `model_routing_guide.md`** from S5.2–S5.7 — **deferred to S5** (the rewrite needs the final router). The current version is stale (single-Groq, retired model names, old cost model) and now carries a **supersession banner** pointing to S5.1–S5.7 + `OPERATIONS.md`.
- ✅ Retire/annotate the v2.1.2 Qwen spec's routing section as superseded. (Banner added at the top of the Qwen spec + a note on the `### Routing Adjustments` heading, both pointing to S5.)
- ✅ Bump `pyproject.toml` → 3.0.0 (S4 gate passed).
- ✅ Update `CREDITS.md` with pin commits for all 8 components (incl. the note that `adhd` + `claude-bug-bounty` are pulled from the On-Off-Grid forks).
- ✅ **Umbrella sync (decision 6):** commit all doc/code changes in `Ult_harness` → sync the umbrella. **Correction to the original wording:** `Ult_harness` is *not* a git submodule of `PORTFOLIO` — `Vibe_coded/*` is gitignored by the umbrella (`.gitignore:20`), so there is no submodule pointer to commit. The only umbrella-tracked file is `Vibe_coded/README.md`; its Ult_harness row is updated to v3.0.0 + current phase status. Nothing sensitive (keys, components, findings) crosses into the umbrella.
- ✅ Archive STORM-HUNT: copy `~/.gemini/antigravity-cli/brain/756a3d23-*/storm_hunt_*.md` into `docs/reference/storm-hunt/` (7 files) + a `README.md` marking it read-only; **separate project — do not merge code**.

**Gate S6:** a new agent session, given only `OPERATIONS.md`, can run the S4.1 command successfully. → **PASS** (verified 2026-10-16: `init` + `run --dry-run` from a fresh temp dir walked the full graph, report on disk with `**Platform:** hackerone` + CWE-89, zero-cost budget). The guide-rewrite item above is the only open S6 sub-task and is owned by S5.

---

## Phase S7 — Operator war-room dashboard (own UI, same-origin on :8001)

> Added 2026-10-16. The operator wants a single screen to **visualize and tweak** the hunt live: state, findings, budget, and routing — plus operator controls (confirm/reject a finding, halt/resume). This is **our own** dashboard, not a vendored third-party UI: **T3MP3ST is a design reference only (AGPL) — never vendor its code.** It is served **same-origin on the admiral port (:8001)** by `orchestrator.admiral.create_app()`, so it shares the control plane and the egress/egress-proxy trust boundary. No new port, no CORS.

> **Status (2026-10-17): DONE.** All four sub-phases shipped and green — `ui/war_room/` (vanilla, offline), static mount in `create_app()`, the full `status()` feed (per-provider budget buckets + GPU meter + $0.50 projection + routing snapshot + RESTRICTED scrub counter), `POST /api/v1/halt`|`resume` (idempotent, event-emitting), `POST /api/v1/finding/{id}/confirm`|`reject` (v1 namespace, delegating to the shared core), and `GET /api/v1/providers`. **20 gate tests** in `tests/test_s7_warroom.py`; suite at **199 passed** (179 baseline + 20 S7). S7.4 browser-visual smoke is the one remaining manual step. **Bonus fix (S7 uncovered a latent S3 bug):** the Pydantic request models were defined *locally inside* `create_app()`, so under `from __future__ import annotations` their body params degraded to **query** params and every `POST` 422'd. Moved to module level (pydantic is a hard dep, fastapi stays lazy) + added `404` guards on unknown ids.

### S7.1 — Read-only shell (phase 1)

- New dir `ui/war_room/` (`index.html` + `app.js` + `style.css`), static, no build step, no framework dependency (vanilla JS so it runs offline and needs no npm).
- `admiral.create_app()` mounts it: `GET /` (and `/war_room`) → `index.html`; `/static/...` → `app.js`/`style.css`. The existing `/api/v1/...` JSON endpoints stay the data source.
- Reads (poll or SSE from the admiral): **hunt state** (phases ①–⑫, current stage, running/halted), **findings** (live list with category/CWE/severity/status), **budget** (per-agent tokens + cost, per-provider buckets from `TokenTracker.get_wing_summary()`, GPU-hour meter, `$0.50` projection from `project_standard_session()`), **routing** (per-provider enabled/available/lane/catalog + live models from `ModelRouter.provider_status()`).
- **Gate S7.1:** a fresh browser tab at `http://127.0.0.1:8001/` renders the four panels; a `pytest` TestClient hits `/` (200, HTML) and the data endpoints; no network/npm needed.

### S7.2 — Operator controls (phase 2)

- `POST /api/v1/halt` → `admiral.halted = True` (stop dispatching new findings / new LLM calls in flight keep finishing).
- `POST /api/v1/resume` → `admiral.halted = False`.
- `POST /api/v1/finding/{id}/confirm` and `POST /api/v1/finding/{id}/reject` → operator adjudication written to the finding record + a war-room event.
- All controls are **idempotent + guarded** (halt when already halted is a no-op 200; a bad id is 404). Controls emit `OrchestrationEvent`s so they appear in the same event log the panels read.
- **Gate S7.2:** TestClient exercises halt→(state flips)→resume; confirm/reject mutate the finding; a halted admiral rejects a new dispatch with a clear signal.

### S7.3 — Per-provider / per-lane routing views (phase 3)

- A **Providers** panel: one row per registry provider — name, tier, lane (SAFE/RESTRICTED badge), enabled/available, RPM/RPD headroom, context, hourly cost (LOCAL_HEAVY), configured catalog vs. live catalog (delta highlighted), and last-used.
- A **Lanes** panel: SAFE vs. RESTRICTED split with the scrub-refusal counter (how many prompts were re-routed to local, from `response.raw["scrub_rerouted"]`), so the operator can see the data-lane guard firing in real time.
- **Gate S7.3:** the Providers panel reflects a mocked multi-provider config (full-keyed) and a degraded config (one provider 429-limited / unavailable) with the right badges; a scrubbed call increments the RESTRICTED re-route counter.

### S7.4 — Polish + kill-switch UX (phase 4)

- Auto-refresh cadence + a manual "refresh now"; halt is a prominent red toggle (the kill switch) with a confirm dialog; cost meters turn amber at 50% of the `$0.50` line and red past it.
- **Gate S7.4:** a visual smoke (manual) + a regression that the halt toggle's backend state and the UI's displayed state agree after a `halt` → `resume` cycle.

**Gate S7 (overall):** `tests/test_s7_warroom.py` green — static serving, all read endpoints, halt/resume/confirm/reject, and the per-provider + lane views — with the same `TestClient` + mocked-registry pattern as S5 (no live keys, no network). The dashboard adds no new secrets and never renders a raw provider key (the `provider_status` feed exposes `has_key` bools only).

---

## Phase S8 — From verified to operational (added 2026-10-17, post S5b)

> **Why this phase exists:** S0–S7 *verified* the machine (offline tests, mocked
> live checks, a zero-cost dry-run). It has not yet *hunted* — no real target, no
> real findings, no real evidence trail/report. Before a live hunt, three
> findings from S2/S5b must be closed or a real hunt will silently under-report:
> OOB confirmation is a skeleton (blind SSRF/XSS never confirms), a 200 with
> empty `content` is a silent no-answer, and a few deprecated calls linger.
>
> **Sequencing (operator decisions, 2026-10-17):** build the code fixes first
> (no target needed); OOB integrates **Interactsh**; `LOCAL_HEAVY`/GPU stays
> **off** (Groq's free `qwen3.8-27b` covers heavy reasoning at $0; RunPod/Tailscale
> deploy scripts are prepped but not spun up). The live hunt (S8.4) is held until
> the operator has an authorized, in-scope target.

**Status (2026-10-17): S8.1, S8.2, S8.3 all DONE.** Order:
S8.1 → S8.2 → S8.3 (all code + offline tests, no live dependency) → S8.4
(live, needs a target) → S8.5 (manual smoke during S8.4). Suite at **239
passed** (204 baseline + 23 S8.1 OOB gate tests in `tests/test_s8_oob.py` +
12 S8.2 empty-content guard tests in `tests/test_s5_router.py`; the five S2 OOB
tests were updated in place to drive the real Interactsh lifecycle through a
mocked `http` seam). S8.3 added no tests — it is a deprecation sweep + a
`pyproject.toml` dep trim; the suite drops from 183 to 1 warning and stays
239-green.

### S8.1 — OOB correlation (Interactsh) — the highest-value fix

> **Status (2026-10-17): DONE — Gate S8.1 green offline.** `compliance/oob_engine.py`
> now speaks real Interactsh (`POST /register` → `POST /polling` → `DELETE
> /deregister`, public API on `oast.pro`, self-hosted via `INTERACTSH_URL`,
> optional `INTERACTSH_API_TOKEN` Bearer, `INTERACTSH_MODE=off` = fail-open no-op
> with zero network). Every embedded payload is registered with context
> (endpoint/category/correlation_id); `OpAdmiral.poll_oob()` is the receive side —
> a callback claims its payload at most once, then either enriches an existing
> finding's evidence + VALIDATING→CONFIRMED, or synthesizes a blind
> SSRF/RCE/XXE finding through `ingest_finding()`, and publishes
> `oob_correlate` events on `triage`. The live path (`main.py::_run_live`)
> opens the session at startup, runs a background poll loop
> (`OOB_POLL_INTERVAL_SECONDS`, default 15s), and deregisters in teardown —
> fail-open at every step (S4.3 invariant). 23 gate tests in
> `tests/test_s8_oob.py`; a live (non-mocked) Interactsh session is exercised for
> the first time during the S8.4 hunt.

The send side already works (specialists embed `OOBEngine.generate_payload()` URLs,
`agents/specialist_base.py:81`), but `compliance/oob_engine.py::poll_callbacks`
returns `[]` and **nothing in the hunt calls it** — so blind SSRF / blind XSS /
RCE never confirm out-of-band (S2 finding N3).

- Implement the real Interactsh lifecycle in `compliance/oob_engine.py`:
  - `init()` → `POST /register` (obtain the collab token + a unique subdomain, e.g.
    `*.oast.lol` / self-hosted), replacing the random-id stand-in.
  - `poll_callbacks()` → `POST /polling` (short-poll, per Interactsh's HTTP API) →
    map DNS/HTTP/SMTP interactions onto `OOBCallback` (shape already defined).
  - `close()` → `DELETE /deregister`.
  - Public vs self-hosted via the existing `interactsh_mode` / `interactsh_url`
    config; add `INTERACTSH_API_TOKEN` support only if the deployment requires it.
- **Injectable HTTP** (the same `http=` seam the whole router uses) so the engine
  is mock-testable with **no network**; **fail-open** when OOB is disabled
  (no token / mode off) → `poll_callbacks()` returns `[]` + an `oob_enabled` flag,
  never breaks a hunt.
- **Wire the receive side** (currently missing): a poll the orchestration loop
  invokes so `oob_correlate` (and the blind-SSRF / blind-XSS validation tasks)
  read back callbacks and confirm. Preserves the fail-open invariant — a dead OOB
  never breaks a hunt (S4.3).
- **Gate S8.1:** a mocked Interactsh returns a callback → `oob_correlate`
  confirms the finding; with OOB disabled → clean no-op, zero network calls,
  suite green. Re-runnable offline.

### S8.2 — Reasoning-model empty-content guard + per-task `max_tokens`

> **Status (2026-10-17): DONE — Gate S8.2 green offline + live probe PASS.**
> `budget/model_router.py`: `DEFAULT_TASK_MAX_TOKENS = 160` + a
> `TASK_MAX_TOKENS` floor map (`triage_decision` 160 — clears the ~100-token
> reasoning budget; `dom_xss_confirm` / `error_classify` 128; the long
> narrative/report tasks 1024–2048). `route()` resolves every stop's budget
> from `explicit kwarg > map > default` (a `None` budget no longer reaches the
> wire — it was the root cause). `_serve_stop`'s cloud path: a 200 whose text is
> empty with `output_tokens > 0` (the reasoning ate the allotment) is retried
> **once at 3× the budget** on the same stop; a hard-failed retry keeps the
> original empty result; a successful or still-empty retry folds the original
> call's tokens into its usage so the per-provider ledger (S5.4.6) sees every
> token actually spent. A still-empty stop is returned flagged
> (`raw["empty_content"]=True`) as a **rotation signal**; `route()` remembers the
> last empty stop and keeps rotating, and only when *every* stop served
> 200-empty does it surface the last flagged empty response to the agent —
> **not** a `NoBudgetError` (which is reserved, unchanged, for "all stops
> hard-failed"). LOCAL stops get the same task-sized budget (`num_predict`) and
> the same empty flag (no retry — no reasoning budget locally). Consensus is
> fail-closed against empty text (documented in `_apply_consensus`, unchanged).
> 12 gate tests in `tests/test_s5_router.py::TestS82EmptyContentGuard`; live
> probe `scripts/s82_live_probe.py` PASS — a real Groq `openai/gpt-oss-120b`
> `triage_decision` with **no explicit `max_tokens`** returned `'CONFIRMED'`
> (non-empty, unflagged, 106 in / 105 out, $0) — the S5b failure class is
> closed end-to-end.

S5b finding: `openai/gpt-oss-120b` (Groq primary) and the nemotron `:free` models
spend ~100 tokens reasoning before emitting `content`; a small `max_tokens`
(8/32) returns **200 with empty `text`**, which `route()` treats as a normal
success → a silent no-answer that the agent cannot distinguish from a real result.

- In `ModelRouter._serve_stop` (`budget/model_router.py`): after a 200, if
  `text` is empty/whitespace (heuristic: `output_tokens > 0` = the reasoning
  budget consumed the whole allotment), **retry that stop once at a larger
  `max_tokens`**; if still empty, treat it as a rotation signal (next stop).
- Distinguish **"all stops hard-failed"** (→ `NoBudgetError`, behavior unchanged)
  from **"served 200 but empty"** (→ return the last empty response with
  `raw["empty_content"]=True` so the *agent* decides, not a crash).
- Add a **`TASK_MAX_TOKENS`** sizing map (or per-entry `max_tokens` in
  `MODEL_ROUTING_TABLE`) so reasoning primaries clear their ~100-token budget
  (default ≈160) and short-verdict tasks (`triage_decision`, `dom_xss_confirm`,
  `error_classify`) have an explicit floor. This kills the failure class at the
  source rather than only retrying it.
- The two-model consensus is already safe (empty partner text → "not confirmed" =
  fail-closed) — document it; do not change it.
- **Gate S8.2:** a mocked empty-content stop retries once at a larger budget, then
  rotates to the next provider; a real Groq `triage_decision` returns a non-empty
  verdict (`'CONFIRMED'`). Offline tests + one live probe.

### S8.3 — Housekeeping sweep (cheap, optional, bundled)

> **Status (2026-10-17): DONE.** (a) `datetime.utcnow()` swept across the
> control plane → timezone-aware `datetime.now(timezone.utc)` at 4 sites
> (`core/types.py` ×2, `budget/token_tracker.py`, `compliance/egress_proxy.py`)
> — the `default_factory` sites wrapped as `lambda:` (a bare
> `datetime.now(timezone.utc)` reference would freeze one shared timestamp at
> class-definition time). Suite warnings 183 → 1 (the survivor is the unrelated
> httpx2/Starlette note); no consumer depended on the naive isoformat.
> (b) `pyproject.toml` trimmed (S2 finding N2): base = what the control plane
> actually imports (`pydantic`, `aiohttp`, `mitmproxy`, and `fastapi` — kept in
> BASE, not moved: the S7 war-room tests import it at test-run time, so the
> S2 note that listed it as aspirational predates S7); `uvicorn` → `live`
> extra, `chromadb` → `memory` extra (touched only via mempalace's deferred
> `ChromaBackend` import), `pyyaml` + `cvss` → `reporting` extra, `requests`
> dropped (zero imports anywhere in the tree). (c) The mempalace `:8000` note
> in `OPERATIONS.md` re-confirmed — still NOT confirmed, now precise: the
> control plane *defaults* `mempalace_url` to `:8000` and specialists
> `POST /search` there, while mempalace's shipped HTTP surfaces are the daemon
> (`/health`, `/jobs`, `/shutdown`, ephemeral port) and the MCP JSON-RPC
> server (`/healthz`, `/statusz`).

- `datetime.utcnow()` → `datetime.now(timezone.utc)` across the control plane
  (S2 finding N4; Python 3.13 deprecation warnings).
- Trim the aspirational `pyproject.toml` deps (`fastapi`, `chromadb`, `cvss`) to
  what the control plane actually imports at test/dry-run time (S2 finding N2) —
  live/ingest-only deps move to an `extras` group.
- Re-confirm the mempalace `:8000` surface note (S2 finding N3-adjacent) stays
  accurate in `OPERATIONS.md`.

### S8.4 — First live hunt *(held — needs an authorized, in-scope target)*

- Run the full graph ①–⑫ against an operator-authorized target: real router,
  real OOB, real report. This is the **actual** end-to-end proof and supersedes
  the S4.1 dry-run.
- **Gate S8.4:** a live authorized hunt completes with (a) a real report on disk,
  (b) an intact evidence trail (raw responses + OOB callbacks), (c) per-provider
  budget buckets ≤ the $0.50 session line, (d) the operator confirming the
  findings in the war room (S7.2 confirm/reject).

### S8.5 — S7.4 visual smoke *(manual, during S8.4)*

- Operator opens the war room at `http://127.0.0.1:8001/` *during* the live hunt
  and confirms the four panels (state / findings / budget / routing) render, the
  RESTRICTED re-route counter moves when the scrub fires, and the red **halt**
  kill-switch actually stops dispatch. Closes the last S7 manual gate.

**Gate S8 (overall):** S8.1 + S8.2 green offline (mocked Interactsh callback
confirms a finding; empty-content stop rotates/retries; no network needed) —
met 2026-10-17 (S8.2 additionally live-probed PASS at $0); S8.3 housekeeping
done, suite green (239 passed, 1 warning); S8.4 a live authorized hunt produces
a real report + intact evidence trail within budget; S8.5 the operator confirms
the war room live. `LOCAL_HEAVY` remains off throughout — heavy reasoning is
Groq `qwen3.8-27b` ($0) until the operator confirms GPU hours (S5.5/S0.7).

**Side items (not in the S8 core, operator-gated):** rotate the `ghp_` PAT that
was once printed in session logs; pre-write the RunPod/Tailscale `llama-server`
deploy scripts so `LOCAL_HEAVY` is a config-flip away once GPU hours are
confirmed.

---

## Explicitly discarded (record of decisions)

1. `specs/assembly_plan.md` v2.1.1 + `specs/implementation_guide.md` (mojibaked recovered copies) — quarantined to `specs/archive/`, superseded by this plan.
2. All hardcoded `/home/souhail/Desktop/Desktop/Ult_harness/` paths — replaced by canonical path / relative paths in all new docs.
3. Old "Phase 2 DONE" claim (mempalace tweaks) — false; mempalace was never present when claimed done; re-verified in S2.9.
4. STORM-HUNT as a code target — separate experiment (workspace `~/Desktop/Desktop/SH` is gone; blueprint preserved as reference only).
5. `BugTraceAI` — removed from scope per design v2.1 F-3 (note: the user's operating brief still mentions it — brief is stale, not the plan).

## At-risk / not recoverable (recorded honestly)

- Phase-4.5 adhd frames.ts security frames: **lost**, re-applied from spec in S1.3.
- Any other uncommitted component tweaks not captured in fork patches: **lost**, re-applied from `specs/*_spec.md` in S1.4.

## Resolved decisions (2026-10-15, from operator)

1. **Available accounts (all enabled in v1):** GitHub Student Pack (→ **GitHub Models**: free GPT-4o + Claude 3.5 Sonnet via API), **AMD Developer free pack** (contents to be inventoried at S0 — if it grants cloud GPU hours, it becomes the $0 LOCAL_HEAVY host, see D3), **Google AI Studio** free API, **Mistral** free (opt out of data training in console at S0), **OpenRouter** free + **$10/month top-up** (50 → 1,000 RPD on free models), **Groq** free API.
2. **Local models (already pulled, RTX 4050 6GB, one resident at a time):**
   - `dr-ry/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M` — **security-domain-tuned 8B → primary LOCAL_LIGHT resident** (replaces the qwen2.5-coder:7b assumption in all old docs).
   - `qwen2.5:7b` — general/code LOCAL fallback.
   - Optional pull: `qwen2.5-coder:3b` (~2 GB) for max-throughput bulk classification if volume demands it (the old 3B noise-filter role).
3. **GPU gateway (D3):** **RunPod, EU region (Paris/Netherlands), 4090 24GB, community/spot instances** (~$0.34–0.45/hr) — best Morocco fit: EU region = low latency from Morocco, cheapest 4090 per hour, mature diskless boot scripts. Transport: **Tailscale private mesh + `llama-server --api-key`** (never public port-forward). L40S (48GB) only if a hunt needs >32K resident context or FastMTP headroom — otherwise 4090 covers it. **First check the AMD Developer pack:** if it includes free cloud GPU hours (ROCm/MI-series or partner credits), run the 27B there at $0 before paying RunPod — RunPod stays as the paid fallback.
4. **$20/month subscription (Claude/ChatGPT/Kimi): DECLINED in favor of $10 OpenRouter.** Reason: consumer subscriptions do **not** grant API quota — the harness router calls APIs with keys, and a Claude/ChatGPT subscription can't feed that. Meanwhile GitHub Models (Student Pack) already provides free GPT-4o + Claude Sonnet API access, and OpenRouter at $10 gives 1,000 RPD free-model quota + cheap paid failover (provider cost + 5.5%). If paid polish ever exceeds ~$5/month, the OpenRouter paid route (not a subscription) is still the right mechanism.
5. **Fork precedence:** fork-derived versions **override** stock upstream (confirmed by default — operator chose "up to you"); S1.2 applies fork patches, `patches/local-tweaks.md` records every delta for audit.
6. **Where docs live:** **commit everything into `Ult_harness`** (this plan as `specs/assembly_plan_v3.md`, rewritten `model_routing_guide.md`, updated `progress_report.md`) **and sync the `PORTFOLIO` umbrella** (bump the `Ult_harness` submodule pointer in the parent repo + add a pointer in `Vibe_coded/README.md`). Do NOT commit the 8 component checkouts or `.env` (gitignored; keys stay in `.env` / env only).
