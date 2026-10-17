# Bug Bounty Harness — Progress Report & Remaining Work

**Date:** 2026-09-06  
**Project:** Autonomous Bug Bounty Harness v2.1.2  
**Architecture Spec:** [`bug_bounty_harness_design_v2_1.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/bug_bounty_harness_design_v2_1.md)  
**Implementation Guide:** [`implementation_guide.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/implementation_guide.md)  
**Qwen3.8-27B Integration:** [`v2.1.2 Spec`](file:///home/souhail/Desktop/Desktop/Ult_harness/Bug%20Bounty%20Harness%20Orchestration%20and%20AI%20Gateway%20Specification%20v2.1.2%20%28Qwen3.8-27B%20Integration%29.md)

---

## 1. What's Been Built — By the Numbers

| Metric | Value |
|---|---|
| **Python modules written** | 30 files |
| **Total Python lines** | ~3,500 lines |
| **TypeScript lines modified** | ~70 lines (adhd frames.ts) |
| **Specialist agents** | 16 / 16 complete |
| **Planning documents** | 7 files (added v2.1.2 Qwen3.8-27B & Gap-Bridging specs) |
| **Model tiers defined** | 4 (LOCAL_LIGHT, LOCAL_HEAVY, PAID_FREE, PAID_PREMIUM) |

---

## 2. Phase-by-Phase Status

### ✅ Phase 0: Core Types & Package Foundation — DONE

| File | Lines | Purpose |
|---|---|---|
| [`core/types.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/core/types.py) | 132 | All shared enums (`Platform`, `VulnCategory`, `VulnStatus`, `ScopeMatchType`) and dataclasses (`ScopeRule`, `TargetScope`, `PlatformHeaders`, `MultiSessionContext`, `TokenBudget`, `Task`, `OrchestrationEvent`) |
| [`core/config.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/core/config.py) | 31 | `HarnessConfig` with env-var loader, ports (8001/8000/8080/3333) |
| [`core/event_bus.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/core/event_bus.py) | 46 | `IEventBus` interface + `InMemoryEventBus` with async pub/sub |
| [`pyproject.toml`](file:///home/souhail/Desktop/Desktop/Ult_harness/pyproject.toml) | 27 | Python control-plane package config |

### ✅ Phase 1: Compliance & Scope Enforcement — DONE

| File | Lines | Purpose |
|---|---|---|
| [`compliance/scope_importer.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/compliance/scope_importer.py) | 92 | Parses CSV/JSON scope into `TargetScope` objects |
| [`compliance/scope_gate.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/compliance/scope_gate.py) | 195 | Policy engine: exact/wildcard/CIDR/regex matching, DNS rebinding protection |
| [`compliance/egress_proxy.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/compliance/egress_proxy.py) | 191 | mitmproxy addon: intercepts all outbound HTTP, enforces ScopeGate, strips headers |
| [`compliance/header_injector.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/compliance/header_injector.py) | 113 | Generates `platform_profile.json` + injects platform-specific auth headers |
| [`compliance/oob_engine.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/compliance/oob_engine.py) | 89 | Interactsh OOB callback integration (public/self-hosted) |

### ✅ Phase 2: Memory Storage & Reference Ingestion — DONE

| File | Lines | Purpose |
|---|---|---|
| [`scripts/ingest_awesome_redteam.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/scripts/ingest_awesome_redteam.py) | 72 | Loads Awesome-Redteam cheatsheets/tips into mempalace |
| [`scripts/ingest_cl4r1tas.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/scripts/ingest_cl4r1tas.py) | 70 | Loads CL4R1T4S system prompts into mempalace |
| mempalace tweaks | — | Added 7 new tables (scopes, oob_callbacks, taxonomy_mappings, etc.) |

### ✅ Phase 3: Budget Routing, Triage & Session Management — DONE

| File | Lines | Purpose |
|---|---|---|
| [`budget/token_tracker.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/budget/token_tracker.py) | 201 | Per-agent token metering, cost estimation from model price table, budget_warning/exhausted events |
| [`budget/model_router.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/budget/model_router.py) | 372 | 40-task routing table, Ollama/Groq/OpenAI/Anthropic backends, fallback chain |
| [`triage/noise_filter.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/triage/noise_filter.py) | 177 | 10 non-bountiable patterns (missing headers, SPF, self-XSS, etc.), deterministic pre-LLM filter |
| [`triage/state_machine.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/triage/state_machine.py) | 181 | Valid transition map, mandatory FP reason, EventBus integration |
| [`sessions/session_manager.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/sessions/session_manager.py) | 185 | Multi-persona login (A/B/Admin/Unauth), 25-min token refresh loop |

### 🟡 Phase 4: Specialist Swarm & Engine Adaptation — PARTIALLY DONE

#### ✅ Part A: New Agent Code — DONE

| File | Lines | Purpose |
|---|---|---|
| [`agents/specialist_base.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/agents/specialist_base.py) | 89 | `ISpecialist` ABC + `OOBMixin` + `DualSessionMixin` + mempalace FP check |
| [`agents/dual_session_tester.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/agents/dual_session_tester.py) | 116 | 4-session IDOR/BAC matrix test runner + analyzer |
| 16 specialist files in `agents/specialists/` | ~1,100 | All 16 categories: SQLi, XSS, SSRF, IDOR, LFI, RCE, XXE, JWT, OpenRedirect, PrototypePollution, CSTI, MassAssignment, HeaderInjection, BAC, AIJailbreak, BusinessLogic |

#### 🟡 Part B: Tweak Existing Tools — PARTIALLY DONE

| Step | File | Status | What's Done / What's Left |
|---|---|---|---|
| **4.5** | `adhd/src/frames.ts` | ✅ **DONE** | 6 security frames added (recon_diverge, payload_mutate, chain_explore, auth_bypass, waf_evasion, business_logic_abuse). Token callback NOT added (requires `engine.ts` change). |
| **4.6** | `adhd/src/engine.ts` | ❌ TODO | FP anti-pattern query to mempalace before returning strategy |
| **4.7** | `claude-bug-bounty/agent.py` | ❌ TODO | Route LLM calls through ModelRouter at `:8001` |
| **4.8** | `claude-bug-bounty/engine.py` | ❌ TODO | Set `HTTP_PROXY=http://127.0.0.1:8080` |
| **4.9** | `claude-bug-bounty/brain.py` | ❌ TODO | Integrate CL4R1T4S prompts from mempalace |
| **4.10** | `claude-bug-bounty/memory/*` | ❌ TODO | Redirect audit_log, pattern_db, rotation to mempalace |
| **4.11** | `claude-bug-bounty/tools/scope_checker.py` | ❌ TODO | Add deprecation notice → `compliance.scope_gate` |
| **4.12** | `jsleak/main.go` | ❌ TODO | Add `HTTP_PROXY` env var + `-json` flag |

### 🟢 Phase 5: Reporting, Orchestration & UI — CORE BUILT (S3, 2026-10-15)

> [!NOTE]
> Plan v3 Phase S3 ("build the missing core / the brain") delivered on 2026-10-15. The control plane (S2, all GREEN) is now wired to the missing top layer:

- **`orchestrator/admiral.py`** — `OpAdmiral`: task dispatch with scope kill switch (3 violations → halt), budget-aware model selection via `budget/model_router`, dual-session IDOR/BAC validation hook, noise-filter → state-machine triage pipeline, CONFIRMED/CHAINED-gated reporting, mempalace write-back (deferred chromadb import; dry-run files nothing). REST/WS surface (`:8001`) via lazy `create_app()` — 12 routes, including the never-shipped 4.6/4.7 contract endpoints `/api/tokens/record` and `/api/v1/llm/route`.
- **`reporting/`** — `taxonomy.py` (all 16 `VulnCategory` → VRT/CWE/CVSS 3.1) + `writers.py` (platform-tailored Markdown, `ReportGateError` if not CONFIRMED/CHAINED).
- **`main.py`** — `init` (scope parse → workspace → platform profile/header export) / `run [--dry-run]` (full graph walk or live: mitmdump + uvicorn + session bootstrap) / `stop`. Operator `--platform` wins over importer-stamped platform.
- **Gate S3: PASS** — `python main.py --help` OK; `init` + `run --dry-run` on a sample scope walks config→gate→admiral→report→memory with mocked component calls (subprocess-locked in `tests/test_s3_main.py`).
- `tests/` is now **154 tests** (104 S2 + 45 S3 + 5 S4) — `python3 -m pytest tests/ -q` → 154 passed.
- The never-shipped 4.6/4.7 **component side** (adhd `engine.ts`, cbb `agent.py`/`engine.py`/`brain.py`/`memory/*`, jsleak `main.go`) is now wired under **S4.0** (see below) — env-gated + fail-open, recorded in `patches/local-tweaks.md` §7.
- Remaining for full Phase 5: T3MP3ST War Room UI (separate, gitignored component — UI gauge work is future work, not a control-plane blocker).

### 🟢 Phase 6: Validation & Dry-Run Test Harness — S2 TRUST AUDIT COMPLETE (2026-10-15)

> [!NOTE]
> The control plane was audited under surgical-restart plan v3, Phase S2 ("classify, don't assume"). All 9 areas (S2.1–S2.9) are **GREEN** after 6 in-place bug fixes (F1–F6): egress `ctx.log` import failure, `Optional` NameError, ingest dry-run no longer requires chromadb/mempalace, session `force_refresh` stale-context fix, and a premium-model cost-table gap. Full verdicts + findings: `docs/trust_audit.md`.

- `tests/` now holds a 104-test pytest suite (`tests/test_s2_*.py`) — `python3 -m pytest tests/ -q` → **104 passed**, no network, no real workspace writes.
- The 20-line egress fixture (`workspace/default-wing/logs/egress_proxy.jsonl`) replays 1:1 through the current decision logic (S2.3).
- Remaining for full Phase 6 (under plan v3): the S4 E2E gate — now **delivered** (see "Phase 6b: End-to-end integration loop (S4)" below). The live-mitmdump + real-specialist variant is operator-side (needs a live target); the control-plane loop is gated in `tests/test_s4_e2e.py`.

### 🟢 Phase 6b: End-to-end integration loop — S4 COMPLETE (2026-10-16)

**S4.0 — Component-side harness wiring (4.6–4.12), all applied + individually verified.**
Every tweak is **env-gated and fail-open** (S4.0 constraint): with the harness env vars unset, the components behave byte-for-byte as standalone; a dead harness can never break a hunt.

| # | Component | Change | Verified |
|---|---|---|---|
| 4.6 | `adhd` `src/llm.ts` + `src/engine.ts` | char-based token estimate counters + `_reset/_takeTokenEstimate`; `run()` → `_harnessPostHook()`: advisory FP query (`POST {MEMPALACE}/search` → `warn` event only, result never mutated) + token callback (`POST {API}/api/tokens/record`); `AbortSignal.timeout(5000)`, counters reset in `finally` | `tsc --noEmit` + `tsc -p tsconfig.json --noEmit` clean; counters 2000/80; both POSTs landed vs fake servers; dead service swallowed |
| 4.7 | `claude-bug-bounty` `harness_client.py` (NEW) + `agent.py` | shared stdlib bridge (urllib): `route_llm()`, `record_tokens()`, `mempalace_search()`, `mempalace_record()`, `_est_tokens()`; env read live inside functions, every call fail-open. `race_analysis()` tries `route_llm("triage_decision")` first; native tool-calling loop stays local, token-mirrors via `/api/tokens/record` | routed path returns harness answer; standalone returns local race winner |
| 4.8 | `cbb` `engine.py` | module init: if `HARNESS_API_URL` set → `setdefault` HTTP(S)_PROXY to `HARNESS_EGRESS_PROXY` + `NO_PROXY=localhost,127.0.0.1`; standalone no-op | verified both ways |
| 4.9 | `cbb` `brain.py` | `_mempalace_cl4r1tas()` prepended to system prompt in `LLMClient.chat()` (single choke point) | live fake palace → block prepended; dead palace → `""` |
| 4.10 | `cbb` `memory/{audit_log,pattern_db}.py` | after local JSONL write → `mempalace_record("audit"\|"pattern", entry)`, fire-and-forget (local JSONL stays authoritative) | `rotation.py` untouched (documented §7) |
| 4.11 | `cbb` `tools/scope_checker.py` | one-shot stderr deprecation notice, fires only when `HARNESS_API_URL` set; checker logic untouched | silent standalone, exactly one warning under harness |
| 4.12 | `jsleak` `main.go` | `Proxy: http.ProxyFromEnvironment` + `-json` flag via `emitFinding()` (`{"kind","name","value","source"}`) | `go build` + `-help` + JSON/proxy smoke pass; non-json output byte-identical |

Full per-tweak record + re-apply recipe after a fresh `fetch_components.sh` + the mempalace `:8000` shim gap: **`patches/local-tweaks.md` §7**.

**S4.1–S4.3 gates — `tests/test_s4_e2e.py` (NEW, 5 tests, all passing):**
- **S4.1 full dry-run**: subprocess `init` + `run --dry-run` → all stage markers, report on disk (`**Platform:** hackerone` + CWE-89), zero-cost budget block (`budget.agents` may be 0, `total_cost_usd` must be 0 — mocked specialist bypasses `router.route()`).
- **S4.2 egress blocks & logs**: out-of-scope → 403 + JSONL `DROP` entry with `data.reason`; in-scope → 200 + `ALLOW`.
- **S4.3 Ollama-only budget invariant**: no task ever resolves to a PAID tier (`FALLBACK_CHAIN` is up-only: LOCAL→[PAID_FREE, PAID_PREMIUM]; PAID-preferred tasks raise `NoBudgetError` fail-fast); zero-cost reconciled ledger; **live Ollama round-trip** via `router._call_ollama` (skipped if Ollama down).

**Gate S4: PASS.** Full suite: `python3 -m pytest tests/ -q` → **154 passed** (149 baseline + 5 S4). Plan rows S4.0–S4.3 ✅; status header updated.

**Next — S5 (model-router redesign) is held pending one operator action:** the **$10 OpenRouter top-up**. (Key rotation is **closed** — the 4 free-tier keys are in gitignored `.env` and the working-copy doc is confirmed redacted; the operator verified this 2026-10-16.) Then re-verify live `/models` per provider (free tiers drift — Groq rotated 2026-09) before trusting any catalog table. S5 rework targets: `budget/model_router.py` + `core/config.py` + `.env` load, with proper `task_type`s (e.g. `triage_decision`, now emitted by cbb 4.7). The S5 build itself (provider registry, adapters, rate limiters, scrub hook, tracker buckets) is spec-complete in `specs/assembly_plan_v3.md` S5.4–S5.6 and would be mock-testable immediately — it is held only so the live 200-per-provider gate item verifies in one pass.

### 🟢 Phase 6c: Documentation & handoff — S6 COMPLETE (2026-10-16)

The S6 handoff items that do **not** depend on the S5 router are delivered:

| # | Item | Status |
|---|---|---|
| — | **`OPERATIONS.md`** — single canonical entry point (what exists / what's verified per trust audit / how to run / known gaps). The S4.1 dry-run command it documents was verified end-to-end from a clean temp dir. | ✅ |
| — | **`pyproject.toml` → 3.0.0** (S4 gate passed). | ✅ |
| — | **`CREDITS.md`** pin commits for all 8 components (notes that `adhd` + `claude-bug-bounty` are pulled from the On-Off-Grid forks, not stock upstream). | ✅ |
| — | **STORM-HUNT archived** → `docs/reference/storm-hunt/` (7 files + a read-only `README.md`; separate project, no code merge). | ✅ |
| — | **Umbrella sync (decision 6).** *Correction:* `Ult_harness` is **not** a git submodule of `PORTFOLIO` — `Vibe_coded/*` is gitignored by the umbrella, so there is no submodule pointer. The only umbrella-tracked file is `Vibe_coded/README.md`; its Ult_harness row is updated to v3.0.0 + current phase status. Nothing sensitive crosses into the umbrella. | ✅ |
| — | **`model_routing_guide.md` + v2.1.2 Qwen-spec routing section** — carry **supersession banners** now (pointing to S5.1–S5.7 + `OPERATIONS.md`). The **full guide rewrite is the S5 deliverable** (needs the final router) and is deferred. | ⏳ (banner ✅, rewrite → S5) |

**Gate S6: PASS** — a new agent session given only `OPERATIONS.md` can run the S4.1 command (verified: `init` + `run --dry-run` from a fresh temp dir walked the full graph, report on disk with `**Platform:** hackerone` + CWE-89, zero-cost budget). The sole open S6 sub-task (the routing-guide rewrite) is owned by S5.

### 🟡 Phase 7: Qwen3.8-27B LOCAL_HEAVY Integration — SPEC COMPLETE, IMPLEMENTATION PENDING

> [!IMPORTANT]
> This new phase was added in v2.1.2 to track the integration of Qwen3.8-27B Aggressive FastMTP as a LOCAL_HEAVY backend. The specification is complete; implementation depends on Phases 3 (ModelRouter / TokenTracker updates) and 5 (HarnessConfig / T3MP3ST / OpAdmiral).

| Step | Description | Status | Details |
|---|---|---|---|
| **7.1** | Deploy llama-server with Q4_K_P + FastMTP | ❌ TODO | Deploy on workstation (Profile E) or cloud GPU (Profile F: RTX 4090/L40S on RunPod/Vast/Lambda). Expose OpenAI-compatible HTTP endpoint with `--spec-draft-model`, `--spec-type draft-mtp`, `--spec-draft-n-max 3`, `--reasoning on`, `--jinja`. |
| **7.2** | Extend `HarnessConfig` | ❌ TODO | Add `local_heavy_enabled: bool`, `local_heavy_url: str`, `local_heavy_hourly_cost: float` fields. |
| **7.3** | Extend `ModelRouter` for LOCAL_HEAVY | ❌ TODO | Add `LOCAL_HEAVY` tier flag. Update routing for `ideation_deep`, `payload_polyglot`, `chain_analysis`, `ai_jailbreak_confirm` to primary→LOCAL_HEAVY, fallback→Groq 70B. Add health check for `local_heavy_url`. |
| **7.4** | Update `TokenTracker` | ❌ TODO | Add LOCAL_HEAVY bucket, `local_heavy_usage` events, GPU-hour cost tracking. |
| **7.5** | Update T3MP3ST UI | ❌ TODO | Display LOCAL_HEAVY usage gauge, GPU-hour estimates, and budget impact. |
| **7.6** | Verify compliance invariants | ❌ TODO | Ensure LOCAL_HEAVY requests pass through egress proxy and ScopeGate. Egress proxy must treat calls to `local_heavy_url` as internal (no scope enforcement). |
| **7.7** | Document deployment cost models | ❌ TODO | Profile E (workstation): upfront HW ~1,200–3,000 USD, no per-token. Profile F (cloud): ~0.35–0.79 USD/hr, ~2.8–6.3 USD per 8hr hunt. |

---

## 3. Planning Documents Created

| File | Purpose |
|---|---|
| [`bug_bounty_harness_design_v2_1.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/bug_bounty_harness_design_v2_1.md) | Architecture blueprint |
| [`implementation_guide.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/implementation_guide.md) | Phase-by-phase build roadmap with checklists |
| [`model_routing_guide.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/model_routing_guide.md) | 40-task model allocation + token budgets |
| [`workflow_overview.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/workflow_overview.md) | High-level repo map + port allocation + hunt flow |
| [`infrastructure_specs.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/infrastructure_specs.md) | Hardware requirements + deployment profiles |
| [`v2.1.2 Spec (Qwen3.8-27B Integration)`](file:///home/souhail/Desktop/Desktop/Ult_harness/Bug%20Bounty%20Harness%20Orchestration%20and%20AI%20Gateway%20Specification%20v2.1.2%20%28Qwen3.8-27B%20Integration%29.md) | Qwen3.8-27B Aggressive FastMTP integration specification, LOCAL_HEAVY tier, Profiles E/F |
| [`harness_gap_bridging_specification_v2_1_2.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/harness_gap_bridging_specification_v2_1_2.md) | Comprehensive gap-bridging technical blueprint for Phase 4B, 5, 6 & 7 |

---

## 4. What Remains — Detailed Sub-Steps

### Phase 4B: Remaining Tweaks (7 steps, ~2 hours)

> [!IMPORTANT]
> These tweaks modify **existing third-party code**. Each step requires reading the current file, understanding its structure, and injecting harness integration points without breaking existing functionality.

#### Step 4.6 — Tweak `adhd/src/engine.ts`
- [ ] After the `run()` function produces a `RunResult`, add an HTTP POST to `http://127.0.0.1:8001/api/tokens/record` with approximate token count
- [ ] Before returning the final shortlist, query `http://127.0.0.1:8000/search` for FP anti-patterns matching the attack ideas
- **Key file:** [`adhd/src/engine.ts`](file:///home/souhail/Desktop/Desktop/Ult_harness/adhd/src/engine.ts) (431 lines)

#### Step 4.7 — Tweak `claude-bug-bounty/agent.py`
- [ ] Add `HARNESS_API_URL` env var (default `http://127.0.0.1:8001`)
- [ ] Wrap LLM dispatch to POST to `/api/v1/llm/route` instead of direct provider
- **Key file:** `claude-bug-bounty/agent.py`

#### Step 4.8 — Tweak `claude-bug-bounty/engine.py`
- [ ] Set `HTTP_PROXY=http://127.0.0.1:8080` in `os.environ` at module init
- [ ] Ensure all `requests`/`aiohttp` calls honor the proxy
- **Key file:** `claude-bug-bounty/engine.py`

#### Step 4.9 — Tweak `claude-bug-bounty/brain.py`
- [ ] On prompt construction, query mempalace for CL4R1T4S system prompts matching the target domain
- [ ] Prepend CL4R1T4S context to the system prompt if available
- **Key file:** `claude-bug-bounty/brain.py`

#### Step 4.10 — Tweak `claude-bug-bounty/memory/*`
- [ ] In `audit_log.py`: redirect log writes to `POST http://127.0.0.1:8000/record_token_usage`
- [ ] In `pattern_db.py`: redirect FP pattern reads to `POST http://127.0.0.1:8000/search_fp_patterns`
- [ ] In `rotation.py`: redirect storage to mempalace tables
- **Key files:** `claude-bug-bounty/memory/audit_log.py`, `pattern_db.py`, `rotation.py`

#### Step 4.11 — Deprecate `claude-bug-bounty/tools/scope_checker.py`
- [ ] Add `import warnings; warnings.warn("Deprecated: use compliance.scope_gate", DeprecationWarning)` at module top
- [ ] Rewire internal calls to delegate to `compliance.scope_gate.ScopeGate`
- **Key file:** `claude-bug-bounty/tools/scope_checker.py`

#### Step 4.12 — Tweak `jsleak/main.go`
- [ ] Read `HTTP_PROXY` env var and configure `http.Client` transport
- [ ] Add `-json` output flag for structured JSON output
- [ ] Run `go mod init` if `go.mod` doesn't exist
- **Key file:** [`jsleak/main.go`](file:///home/souhail/Desktop/Desktop/Ult_harness/jsleak/main.go)

#### Gate Check
```bash
python3 -c "
from agents.specialist_base import ISpecialist, OOBMixin
from agents.specialists.sqli_specialist import SQLiSpecialist
from agents.specialists.ssrf_specialist import SSRFSpecialist
print('Phase 4 PASSED')
"
```

---

### Phase 5: Reporting, Orchestration & UI (8 steps, ~3-4 hours)

> [!IMPORTANT]
> This is the phase where the entire harness comes alive. `admiral.py` is the central brain that ties every component together.

#### Step 5.1 — Create `reporting/__init__.py`
- [ ] Empty package init

#### Step 5.2 — Write `reporting/taxonomy.py`
- [ ] `TaxonomyMapper` class with:
  - `get_vrt(vuln_category: VulnCategory) -> str` — Bugcrowd VRT classification
  - `get_cwe(vuln_category: VulnCategory) -> int` — CWE ID mapping
  - `get_cvss_vector(finding) -> str` — CVSS 3.1 vector string generation
  - `generate_report(finding, platform: Platform) -> str` — Full Markdown report with PoC
- [ ] Platform-specific report templates for HackerOne, Bugcrowd, YesWeHack

#### Step 5.3 — Create `orchestrator/__init__.py`
- [ ] Empty package init

#### Step 5.4 — Write `orchestrator/admiral.py` — **THE BRAIN**
- [ ] FastAPI app on port `8001`
- [ ] REST endpoints:
  - `POST /api/tokens/record` — token usage ingestion from adhd/agents
  - `POST /api/triage/callback` — scanner hits from claude-bug-bounty
  - `GET /api/v1/status` — wing status, active specialists, budget gauge
  - `GET /api/v1/findings` — all findings with triage status
  - `POST /api/v1/findings/{id}/confirm` — operator confirms finding
  - `POST /api/v1/findings/{id}/reject` — operator rejects (FP + reason)
- [ ] WebSocket endpoint: `ws://localhost:8001/ws` — bidirectional event stream
- [ ] On startup: initialize EventBus, TokenTracker, ModelRouter, SessionManager, ScopeGate
- [ ] Task dispatch loop: create Tasks, assign to specialists, enforce budget

#### Step 5.5 — Write `orchestrator/cli_tunnel.py`
- [ ] Keyless local CLI session interceptor for operator commands

#### Step 5.6 — Write `main.py` — Entry Point
- [ ] `python main.py init --platform hackerone --program acme-corp`
  - Parse scope → generate `workspace/acme-corp/platform_profile.json`
- [ ] `python main.py run --program acme-corp [--dry-run]`
  - Boot sequence: egress proxy → mempalace → admiral → sessions → model router → scope gate
- [ ] `python main.py stop`
  - Graceful shutdown of all services

#### Step 5.7 — Tweak `T3MP3ST/src/server.ts`
- [ ] REST client: fetch from `http://127.0.0.1:8001/api/v1/*`
- [ ] WS client: connect to `ws://127.0.0.1:8001/ws`
- [ ] Wire confirm/reject buttons to admiral endpoints

#### Step 5.8 — Tweak `T3MP3ST/docs/index.html`
- [ ] Token budget gauge (progress bar: used/cap per tier, including LOCAL_HEAVY GPU-hour gauge)
- [ ] LOCAL_HEAVY usage indicator (invocation count, GPU-hours, cost estimate)
- [ ] OOB callback badges (green=received, yellow=pending)
- [ ] Confirm/reject modal with FP reason textarea

#### Gate Check
```bash
python3 -m uvicorn orchestrator.admiral:app --port 8001 &
sleep 2
curl -s http://127.0.0.1:8001/api/v1/status | python3 -m json.tool
kill %1
echo "Phase 5 PASSED"
```

---

### Phase 6: Validation & Dry-Run Test Harness (5 steps, ~1.5-2 hours)

> [!TIP]
> These tests verify the compliance story end-to-end. Run them before every engagement.

#### Step 6.1 — Create `tests/__init__.py`

#### Step 6.2 — Write `tests/test_scope_gate.py`
- [ ] Test cases:
  - Exact domain match (allow)
  - Wildcard `*.example.com` match (allow)
  - Out-of-scope domain (deny)
  - DNS rebinding protection: `127.0.0.1`, `169.254.169.254`, `::1`, `localhost` (deny)
  - CIDR range match (allow/deny)
  - Regex pattern match (allow)
  - WebSocket `ws://` scheme handling
  - Third-party exclusion list

#### Step 6.3 — Write `tests/test_osint_exemption.py`
- [ ] Test cases:
  - OSINT domains (twitter.com, github.com) allowed through proxy
  - Non-OSINT domain with OSINT header → dropped
  - OSINT header stripped from proxied request
  - In-scope target with OSINT header → header stripped, request allowed

#### Step 6.4 — Write `tests/test_taxonomy.py`
- [ ] Test cases:
  - `VulnCategory.SQLI` → CWE-89
  - `VulnCategory.XSS` → CWE-79
  - VRT classification correctness
  - CVSS 3.1 vector string format
  - HackerOne / Bugcrowd / YWH report format validation

#### Step 6.5 — Write `tests/test_mock_e2e.py`
- [ ] Test cases:
  - Dry-run mode: egress proxy logs `WOULD_SEND` but doesn't transmit
  - No external traffic leaves the machine in dry-run
  - Full mock pipeline: finding → noise filter → state machine → report

#### Gate Check
```bash
python3 -m pytest tests/ -v
echo "Phase 6 PASSED — HARNESS ASSEMBLY COMPLETE"
```

---

### Phase 7: Qwen3.8-27B LOCAL_HEAVY Integration (~3-4 hours)

> [!IMPORTANT]
> This phase integrates Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP as a LOCAL_HEAVY backend. It depends on Phase 3 (ModelRouter/TokenTracker) and Phase 5 (HarnessConfig/OpAdmiral/T3MP3ST). See the [v2.1.2 spec](file:///home/souhail/Desktop/Desktop/Ult_harness/Bug%20Bounty%20Harness%20Orchestration%20and%20AI%20Gateway%20Specification%20v2.1.2%20%28Qwen3.8-27B%20Integration%29.md) for full details.

#### Step 7.1 — Deploy llama-server with Q4_K_P + FastMTP
- [ ] Select deployment target: workstation (Profile E: RTX 4090/A6000, 24–48 GB VRAM) or cloud (Profile F: RTX 4090/L40S on RunPod/Vast/Lambda)
- [ ] Download Qwen3.8-27B Q4_K_P GGUF (17.92 GB) + FastMTP-32K sidecar (903 MB)
- [ ] Launch `llama-server` with flags:
  - `--model <Q4_K_P.gguf>`
  - `--spec-draft-model <FastMTP-32K.gguf>`
  - `--spec-type draft-mtp --spec-draft-n-max 3`
  - `--ctx-size <8192–204800 depending on VRAM>`
  - `--reasoning on --reasoning-effort xhigh --jinja`
- [ ] Verify OpenAI-compatible endpoint responds at configured URL

#### Step 7.2 — Extend `HarnessConfig`
- [ ] Add `local_heavy_enabled: bool` (default `False`)
- [ ] Add `local_heavy_url: str` (llama-server endpoint URL)
- [ ] Add `local_heavy_hourly_cost: float` (for cloud GPU cost-aware routing, e.g. `0.35` for 4090)
- **Key file:** [`core/config.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/core/config.py)

#### Step 7.3 — Extend `ModelRouter` for LOCAL_HEAVY tier
- [ ] Add `LOCAL_HEAVY` internal tier flag to distinguish from laptop-scale LOCAL_LIGHT
- [ ] Add `qwen3.8-27b-aggressive-q4-local` model identifier
- [ ] Update routing table entries:
  - `ideation_deep`: primary → LOCAL_HEAVY, fallback → Groq 70B
  - `payload_polyglot`: primary → LOCAL_HEAVY, fallback → Groq 70B
  - `chain_analysis`: primary → Groq 70B, optional → LOCAL_HEAVY for exploit-centric chains
  - `impact_escalation`: primary → Groq 70B, optional → LOCAL_HEAVY
  - `ai_jailbreak_confirm`: primary → LOCAL_HEAVY, fallback → Groq 70B + GPT-4o-mini
- [ ] Add health check probe for `local_heavy_url` at startup (alongside Ollama and Groq)
- [ ] Implement transparent fallback to Groq 70B when LOCAL_HEAVY is offline
- **Key file:** [`budget/model_router.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/budget/model_router.py)

#### Step 7.4 — Update `TokenTracker` for LOCAL_HEAVY bucket
- [ ] Add LOCAL_HEAVY usage tracking as separate bucket
- [ ] Emit `local_heavy_usage` events to EventBus
- [ ] Track GPU-hour cost estimates using `local_heavy_hourly_cost` from HarnessConfig
- **Key file:** [`budget/token_tracker.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/budget/token_tracker.py)

#### Step 7.5 — Update T3MP3ST for LOCAL_HEAVY visibility
- [ ] Add LOCAL_HEAVY usage gauge in token budget display
- [ ] Show GPU-hour estimates and cost for cloud deployments
- [ ] Show invocation count: how many tasks routed to LOCAL_HEAVY vs Groq vs LOCAL_LIGHT
- **Key files:** `T3MP3ST/src/server.ts`, `T3MP3ST/docs/index.html`

#### Step 7.6 — Verify compliance invariants
- [ ] Confirm all HTTP requests produced by LOCAL_HEAVY planning pass through `compliance/egress_proxy.py` and ScopeGate
- [ ] Configure egress proxy to treat `local_heavy_url` as internal (no scope enforcement on model API calls)
- [ ] Verify AI jailbreak and offensive specialists using LOCAL_HEAVY are constrained to in-scope targets
- **Key files:** [`compliance/egress_proxy.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/compliance/egress_proxy.py), [`compliance/scope_gate.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/compliance/scope_gate.py)

#### Step 7.7 — Document deployment cost models
- [ ] Profile E (workstation): upfront HW ~1,200–3,000 USD, no per-token charges, electricity only
- [ ] Profile F (cloud): ~0.35 USD/hr (4090), ~0.79 USD/hr (L40S), ~2.8–6.3 USD per 8hr hunt
- [ ] Decision matrix: when to enable/disable LOCAL_HEAVY per engagement based on expected bounty value vs compute spend
- **Key file:** [`infrastructure_specs.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/infrastructure_specs.md)

#### Gate Check
```bash
# Verify LOCAL_HEAVY health check and routing
python3 -c "
from budget.model_router import ModelRouter
from core.config import HarnessConfig
cfg = HarnessConfig()
cfg.local_heavy_enabled = True
cfg.local_heavy_url = 'http://127.0.0.1:8090'
router = ModelRouter(cfg)
print('LOCAL_HEAVY tier:', router.check_local_heavy_health())
print('Phase 7 PASSED')
"
```

---

## 5. Overall Progress

```
Phase 0  ████████████████████ 100%  Core types, config, event bus
Phase 1  ████████████████████ 100%  Compliance & scope enforcement
Phase 2  ████████████████████ 100%  Memory storage & ingestion
Phase 3  ████████████████████ 100%  Budget, triage, sessions
Phase 4  ████████████████░░░░  80%  Agents done, tool tweaks pending
Phase 5  ░░░░░░░░░░░░░░░░░░░░   0%  Orchestration & UI
Phase 6  ███████████████░░░░░  85%  S2 trust audit: 104 tests green, 6 bugs fixed (E2E gate = S4)
Phase 7  ██░░░░░░░░░░░░░░░░░░  10%  Qwen3.8-27B integration (spec done)
─────────────────────────────────────
Overall  ██████████████░░░░░░  61%
```

> [!NOTE]
> Overall progress decreased from 68% → 61% because Phase 7 (Qwen3.8-27B integration) was added as a new phase, expanding total scope. Actual completed work has not regressed.

**Remaining effort:** ~10-16 hours across Phases 4B + 5 + 6 + 7

| Phase | Estimated Effort |
|---|---|
| Phase 4B (tool tweaks) | ~2 hours |
| Phase 5 (orchestration & UI) | ~3-4 hours |
| Phase 6 (tests & validation) | ~1.5-2 hours |
| Phase 7 (Qwen3.8-27B integration) | ~3-4 hours |
