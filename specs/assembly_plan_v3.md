# ULT_HARNESS — Surgical Restart Plan v3.0

**Date:** 2026-10-15
**Status:** APPROVED — executing. S0 (salvage), S1 (component restoration), **S2 (control-plane trust audit)** complete 2026-10-15 (commits `394bc29`, `c95b967`, S2 in `198004c`+). S1.4 correction recorded in `patches/local-tweaks.md` §6: Phase 4B tweaks 4.6–4.12 were never applied in the original build, so S3/S4 carry that integration work. S2 verdict: all 9 areas GREEN after 6 in-place bug fixes (F1–F6) — see `docs/trust_audit.md`; 104-test suite in `tests/`.
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

**Gate S3:** `python main.py --help` works; `--dry-run` on a sample scope file walks the full graph (config→gate→admiral→report→memory) with mocked component calls.

---

## Phase S4 — End-to-end integration loop

| # | Test |
|---|---|
| S4.1 | Scope import → gate enforcement → recon dispatch (real Agent-Reach, local model) → findings persisted to mempalace → noise filter → state machine → evidence validation (OOB callback via `compliance/oob_engine`) → report draft → write-back to mempalace |
| S4.2 | Negative test: out-of-scope request MUST be blocked by egress proxy and logged |
| S4.3 | Budget test: run with Ollama-only → zero paid-tier calls recorded by `token_tracker` |

**Gate S4:** one full dry-run on a legitimate target with local models, all log assertions pass, budget ledger consistent.

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

**Gate S5:** (1) router resolves every routing-table entry to a live provider (dry-run with mocked calls); (2) one real call per enabled provider returns 200 and is logged with provider/tier/lane; (3) 429 simulation rotates to the next provider; (4) scrub hook blocks a prompt containing a fake API key on RESTRICTED providers and re-routes it to LOCAL; (5) token tracker shows per-provider buckets; (6) cost projection for a standard session ≤ $0.50 excluding optional GPU hours.

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

- Single canonical `OPERATIONS.md`: what exists, what's verified (per trust audit), how to run, known gaps.
- **Rewrite `model_routing_guide.md`** from S5.2–S5.7 (current version is stale: single-Groq, retired model names, old cost model). Retire/annotate the v2.1.2 Qwen spec's routing section as superseded.
- Bump `pyproject.toml` → 3.0.0 once S4 gate passes.
- Update `CREDITS.md` with pin commits for all 8 components.
- **Umbrella sync (decision 6):** commit all doc/code changes in `Ult_harness` → commit the updated submodule pointer in the `PORTFOLIO` parent repo → verify `Vibe_coded/README.md` lists Ult_harness with current phase status. Nothing sensitive (keys, components, findings) crosses into the umbrella.
- Archive STORM-HUNT: copy `~/.gemini/antigravity-cli/brain/756a3d23-*/storm_hunt_*.md` into `docs/reference/storm-hunt/` (read-only reference for orchestrator design; **separate project — do not merge code**).

**Gate S6:** a new agent session, given only `OPERATIONS.md`, can run the S4.1 command successfully.

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
