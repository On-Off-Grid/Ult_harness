# OPERATIONS — Ult_harness

The single canonical operating document. If you are a new agent session (or a
new operator) and you have nothing else, this file is enough to verify the
harness end-to-end. It tells you **what exists, what is verified, how to run
it, and what is still open.**

> **One-sentence status (2026-10-17):** Phases S0–S4, **S5 (a+b)**, **S7**
> (the operator war-room dashboard on `:8001`), and **S8.1–S8.3** are complete
> and committed — the control plane is built, audited (S2), integrated
> end-to-end (S4), has real OOB correlation (Interactsh, S8.1), the
> reasoning-model empty-content guard (S8.2, live-probe PASS), and the S8.3
> housekeeping sweep (timezone-aware timestamps, trimmed `pyproject` deps),
> has a **239-test suite all green (1 warning, unrelated httpx2/Starlette note)**,
> and its **S5b live provider verification PASSED post top-up** (5/6 enabled
> providers returned a live 200 logged per provider/tier/lane + paid overflow
> resolved; `github_models` reported UNVERIFIABLE because the upstream service
> was retired 2026-07-30). Next: **S8.4** first live hunt (held — needs an
> operator-authorized, in-scope target), **S8.5** war-room visual smoke
> (during S8.4).

---

## 1. What this is

`Ult_harness` is the **control plane** of an autonomous bug-bounty harness. It
is a Python package (FastAPI core + a 16-specialist agent layer) that sits
around — and enforces guardrails over — 8 third-party recon/exploit components
it fetches at build time.

- **Tracked in git (the control plane):** `core/`, `compliance/`, `budget/`,
  `triage/`, `reporting/`, `sessions/`, `agents/`, `orchestrator/`, `main.py`,
  `tests/`, `scripts/`, `specs/`, `docs/`, and the guides/credits at the root.
- **Fetched at build time (NOT vendored, gitignored):** the 8 components in the
  repo root — `adhd`, `Agent-Reach`, `Awesome-Redteam`, `CL4R1T4S`, `T3MP3ST`,
  `claude-bug-bounty`, `jsleak`, `mempalace`. Fetch them with
  `./scripts/fetch_components.sh`. Provenance + licenses + pin commits:
  `CREDITS.md`. Local, env-gated wiring of the components to the harness is
  recorded in `patches/local-tweaks.md` §7 (re-apply after a fresh fetch).

The control plane never imports a component directly; the components call back
into the harness over HTTP (the `harness_client` bridge) or are driven by the
admiral. A dead harness can never break a standalone component (every
component-side tweak is env-gated and fail-open).

---

## 2. Requirements

| Need | Value | Notes |
|---|---|---|
| Python | **3.13** (tested on 3.13.12) | `requires-python >= 3.10` |
| Control-plane deps | `aiohttp`, `mitmproxy` | **Both are system-installed; the test suite needs no venv.** |
| Live-mode deps | `fastapi`, `uvicorn` | Only for a **real** (non-dry-run) `run`. Available in the repo `.venv` (3.13.12, fastapi 0.141.1, uvicorn 0.52.1). System `python3` is PEP-668 externally-managed, so live mode uses `.venv/bin/python`. |
| Ollama (LOCAL tier) | local, `http://127.0.0.1:11434` | Primary model `hf.co/dr-ry/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M`, fallback `qwen2.5:7b`. Both smoke-tested. |
| `.env` (gitignored) | API keys for FREE/RESTRICTED lanes | See §6. Keys **never** in git. |

Everything in the **test suite** and the **dry-run** works with system
`python3` + Ollama only — no API keys required.

---

## 3. How to run

All commands assume you are in the `Ult_harness/` repo root.

### 3.1 Verify the control plane (no network, no keys, no real workspace)

```bash
cd Ult_harness
python3 -m pytest tests/ -q
# → 239 passed   (154 baseline: 104 S2 audit + 45 S3 core + 5 S4 E2E,
#                 + 25 S5 router gates, + 20 S7 war-room gates,
#                 + 5 S5b regression, + 23 S8.1 OOB, + 12 S8.2 empty-content)
```

- No venv, no network (the one health-check test targets a closed localhost
  port), no writes to the real `./workspace`.
- The S4.3 live-Ollama round-trip test **auto-skips** if Ollama is down; the
  other 153 pass regardless.

### 3.2 Run the end-to-end dry-run (Gate S4.1 / Gate S6)

This is the command a fresh session must be able to run from nothing but this
file. It boots the whole control-plane graph with a mocked specialist — **no
packets, no LLM calls, no mempalace writes** — and writes a real report to disk.

```bash
cd Ult_harness

# 1) make a scratch scope file (a legitimate sample target)
WORK=$(mktemp -d /tmp/s6_verify.XXXXXX)
cat > "$WORK/scope.json" <<'JSON'
{"targets": [
  {"name": "*.acme-corp.com",   "category": "URL", "in_scope": true},
  {"name": "api.acme-corp.com", "category": "URL", "in_scope": true},
  {"name": "legacy.acme-corp.com","category":"URL","in_scope": false}
]}
JSON

# 2) init + dry-run
python3 main.py init --platform hackerone --program acme-corp \
    --scope-file "$WORK/scope.json" --researcher operator --workspace "$WORK/ws"
python3 main.py run  --program acme-corp --dry-run --workspace "$WORK/ws"

# 3) confirm the report landed
ls "$WORK/ws/acme-corp/reports/"     # → 1 markdown report, e.g. task_..._sqli.md
grep -E 'Platform|CWE' "$WORK/ws/acme-corp/reports/"*.md
```

**Expected:** `init` emits 2 in-scope / 1 out-of-scope rules; `run` prints the
full stage walk and a `[dry-run] status` JSON line, then
`[dry-run] ✅ full graph walked: config → gate → admiral → report → memory`.
The stage markers, in order, are:

```
scope gate  : sample endpoint ALLOWED
scope gate  : unrelated host BLOCKED
model route : payload_craft → LOCAL/qwen2.5-coder:7b
dispatch    : 1 finding(s) from mocked specialist
triage      : … → validating
noise filter: missing-header finding DROPPED
report gate : pre-confirmation report correctly refused
report      : …/reports/task_…_sqli.md (High, CWE-89)
mempalace   : 1 drawer(s) would be filed (dry-run, no chromadb write)
status      : {"hunt":"active","dry_run":true,"platform":"hackerone",
               "findings":{"confirmed":1},"reports_written":1,
               "budget":{"total_cost_usd":0,...}}
```

The report on disk contains `**Platform:** hackerone` and `CWE-89` (SQLi).
Budget is **zero** — a dry-run makes no real LLM calls.

### 3.3 Run live (real components, real LLM)

`python main.py run --program <p>` (no `--dry-run`) spawns `mitmdump` +
`uvicorn` and exports the `HARNESS_*` env vars that make the fetched components
talk back into the harness. The model router is now the **S5 4-tier,
multi-provider, lane-aware** version (§5 item 1), so the FREE provider lanes
are wired. The live path runs with whatever keys are present in `.env`:

- **Ollama-only (no paid keys):** the zero-spend floor. No task ever resolves
  to a paid tier (S4.3 invariant); paid-preferred tasks fail fast with
  `NoBudgetError`.
- **Free pool keyed (Groq/OpenRouter/Mistral/Gemini/GitHub/Cloudflare):** each
  enabled provider joins its tier in failover order; `startup_discovery()`
  reconciles every live `GET /models` catalog against the configured
  preferences (fail-open).

> **S5b — live verification PASSED (2026-10-17, post top-up).** The router's
> **one-real-200-per-provider** gate item was run live against the operator's
> real `.env` keys (the $10 OpenRouter top-up landed first) via
> `scripts/s5b_live_verify.py`. **5/6 enabled providers returned a live 200**
> (logged per provider/tier/lane): `ollama` (LOCAL/SAFE), `groq`
> `openai/gpt-oss-120b` (PAID_FREE/SAFE), `openrouter`
> `nvidia/nemotron-3-ultra-550b-a55b:free` (PAID_FREE/SAFE), `mistral`
> `codestral-latest` (PAID_FREE/SAFE; the primary `mistral-small-latest` was
> per-model 429-throttled and rotated within the provider), `gemini`
> `gemini-3.1-flash-lite` (PAID_FREE/RESTRICTED). The **paid overflow
> `anthropic/claude-sonnet-5.5` resolved** (live catalog + a real paid 200).
> `github_models` is **UNVERIFIABLE, not a code defect** — the GitHub Models
> inference service was **retired upstream 2026-07-30** (the surviving
> `api.githubcopilot.com` needs an IDE OAuth token, not a `ghp_` PAT); it stays
> registered so PAID_PREMIUM keeps resolving, with the chain's OpenRouter paid
> stop serving whenever it 401s. Re-run any time with `scripts/s5b_live_verify.py`.

### 3.4 Open the operator war-room dashboard (S7)

The control plane serves its own war-room UI **same-origin on `:8001`** (no new
port, no CORS; T3MP3ST is a design reference only — never vendored). In a live
run, open `http://127.0.0.1:8001/` (or `/war_room`) in a browser tab. It
polls `:8001` for the four panels — **Hunt State**, **Findings**, **Budget**
(per-provider buckets + GPU-hour meter + $0.50 session projection), and
**Model Routing** (per-provider tier / lane / state / catalog drift) — plus
operator controls:

- **HALT / RESUME** — the kill switch (`POST /api/v1/halt`, `/api/v1/resume`).
  Idempotent; emits `hunt_halted` / `hunt_resumed` on the triage topic so the
  live `/ws` event stream reflects it. A halted admiral skips new dispatches.
- **Confirm / reject** per finding — `POST /api/v1/finding/{id}/confirm|reject`
  (v1 namespace delegating to the shared triage core; the legacy
  `/api/triage/{id}/…` routes remain).

Everything is read-only-observation plus these operator controls — the UI
renders **no raw provider keys** (the `provider_status` feed exposes `has_key`
booleans only). This is the S7 surface; its gates live in
`tests/test_s7_warroom.py` (20 tests, TestClient + mocked registry, no
network/keys).

---

## 4. What is verified (per the S2 trust audit)

The control plane was treated as *unverified until proven* and audited in S2
(`docs/trust_audit.md`). Verdict, after the S2 fixes: **all 9 areas GREEN**,
6 in-place bug fixes (F1–F6) with no interface change.

| Area | Package | Status |
|---|---|---|
| S2.1 | `core/` (types, config, event_bus) | ✅ |
| S2.2 | `compliance/scope_gate.py` (+ importer) | ✅ |
| S2.3 | `compliance/egress_proxy.py` (20-line fixture replayed 1:1) | ✅ |
| S2.4 | `compliance/header_injector.py` + `oob_engine.py` | ✅ |
| S2.5 | `budget/model_router.py` + `token_tracker.py` | ✅ (router superseded by S5) |
| S2.6 | `triage/noise_filter.py` + `state_machine.py` | ✅ |
| S2.7 | `sessions/` (session_manager, dual_session_tester) | ✅ |
| S2.8 | `agents/` (16 specialists + base + mixins) | ✅ |
| S2.9 | `scripts/ingest_*.py` | ✅ |

**Integration (S4), proven by `tests/test_s4_e2e.py`:**
- **S4.1** — full dry-run walks the whole graph; report lands on disk, platform-tailored, zero-cost.
- **S4.2** — an **out-of-scope** request is blocked (403) **and** logged to `egress_proxy.jsonl` with a reason; an in-scope request passes (200).
- **S4.3** — under an **Ollama-only** config, **no task ever resolves to a paid tier** (LOCAL-preferred → LOCAL; paid-preferred → fail-fast `NoBudgetError`); a recorded LOCAL run is zero-cost with a reconciled ledger. The budget invariant is locked by test: there is no code path that spends money when no paid backend is configured.

**Component-side wiring (S4.0, 4.6–4.12):** the 8 components are wired to the
harness (egress proxy, mempalace memory, LLM routing, token mirroring). Every
tweak is **env-gated and fail-open** — with the `HARNESS_*` env vars unset the
components are byte-for-byte standalone. Full record + re-apply recipe:
`patches/local-tweaks.md` §7.

---

## 5. Known gaps / what is still open

Be explicit about these — do not paper over them.

1. **S5b — live provider verification: DONE (PASS, 2026-10-17, post top-up).**
   The S5 router rework is **built, mock-tested (S5a), and now live-verified
   (S5b)** — 4-tier structure (`LOCAL / LOCAL_HEAVY / PAID_FREE /
   PAID_PREMIUM`), the multi-provider FREE pool (Groq primary,
   OpenRouter/Mistral/Gemini/Cloudflare failover, GitHub Models free frontier —
   now upstream-retired, see item 2 below), per-provider rate limiters + 429
   rotation, runtime `/models` discovery, SAFE/RESTRICTED data-lane scrub hook,
   per-provider tracker buckets, two-model validation consensus. **All six
   Gate S5 items are green:** 1, 3–6 in `tests/test_s5_router.py` (offline),
   and **item 2 (one real 200 per enabled provider, logged per
   provider/tier/lane, + a live `GET /models` re-check) passed live** on
   2026-10-17 after the operator's $10 OpenRouter top-up — 5/6 enabled
   providers (ollama, groq, openrouter, mistral, gemini) + the paid-overflow
   model resolved. The live re-check also caught and fixed **2026 free-tier ID
   drift** (OpenRouter `:free`, Mistral, Gemini re-pointed to live IDs) plus
   two real bugs (Gemini-native discovery parsing, bodyless GET). The
   re-runnable live check is `scripts/s5b_live_verify.py`; the dry-run and all
   204 tests are unaffected and the S4.3 "no paid spend" invariant still holds.
   - `model_routing_guide.md` has been **rewritten** to the shipped S5 router
     (2026-10-17) and is now current (incl. the GitHub Models retirement).
2. **S0.7 — AMD Developer pack cloud-GPU hours: UNVERIFIED.** No local
   artifacts found; needs a manual login to the AMD developer portal. Until
   then `LOCAL_HEAVY` is **off/optional** and heavy reasoning leans on the free
   `qwen/qwen3.8-27b` (Groq). Record the result in `docs/provisioning.md`.
3. **Mempalace `:8000` REST surface — NOT confirmed.** The control plane
   *defaults* `mempalace_url` to `http://127.0.0.1:8000` and the specialists
   `POST {mempalace_url}/search` there (`core/config.py`, `agents/
   specialist_base.py`), but mempalace's shipped HTTP surfaces are the
   **daemon** (`/health`, `/jobs`, `/shutdown`, ephemeral port) and the **MCP
   JSON-RPC server** (`/healthz`, `/statusz`) — neither confirms a `:8000`
   REST `/search` endpoint. Every mempalace call is therefore **best-effort
   fail-open** (a dead palace never breaks a hunt); local JSONL stays
   authoritative. Re-confirm during S8.4 if the operator runs mempalace. Gap
   documented in `patches/local-tweaks.md` §7.
4. ~~**OOB interaction correlation is a skeleton.**~~ **CLOSED (S8.1, 2026-10-17).**
   `OOBEngine` now speaks real Interactsh (register / poll / deregister) with an
   injectable `http` seam and fail-open degradation; the send side registers
   each embedded payload with context (endpoint/category) and the admiral's
   `poll_oob()` receive side (a live-path poll loop in `main.py`) matches
   callbacks back to findings — enriching an existing finding or synthesizing a
   blind SSRF/RCE/XXE finding, then VALIDATING → CONFIRMED with no LLM in the
   loop. Config: `INTERACTSH_MODE` (`public` | `selfhosted` | `off`),
   `INTERACTSH_URL`, optional `INTERACTSH_API_TOKEN`. Verified offline in
   `tests/test_s8_oob.py`. A live (non-mocked) Interactsh session is
   exercised for the first time during the S8.4 hunt.
5. ~~**Minor housekeeping.**~~ **CLOSED (S8.3, 2026-10-17).** (a) `datetime.
   utcnow()` deprecations (S2 finding N4) swept across the control plane —
   `core/types.py`, `budget/token_tracker.py`, `compliance/egress_proxy.py`
   now use timezone-aware `datetime.now(timezone.utc)` (timestamps become
   `+00:00`-aware; no naive-format consumer depended on the old string shape).
   (b) `pyproject.toml` dep trim (S2 finding N2): base is now only what the
   control plane actually imports at test/dry-run/brain time (`fastapi` — a
   real S7 *test-time* dep, kept in base — `pydantic`, `aiohttp`, `mitmproxy`);
   live/ingest-only deps moved to extras (`uvicorn` → `live`, `chromadb` →
   `memory`, `pyyaml`+`cvss` → `reporting`); the never-imported `requests` was
   dropped. (c) the mempalace `:8000` note above re-confirmed.

**S8 is in progress — S8.1 + S8.2 + S8.3 done, S8.4 (first live hunt) next
(2026-10-17).** S0–S7 are done and the control plane is proven to *run*; it is
not yet proven to *hunt*.
S8 closes the three findings a real hunt would trip over, then runs the first
live hunt. Detail in `specs/assembly_plan_v3.md` §S8.1–S8.5. **S8.1 (OOB
correlation via Interactsh) is DONE**: real register/poll/deregister lifecycle
in `compliance/oob_engine.py` (injectable `http` seam, fail-open,
`INTERACTSH_MODE=off` for a clean no-op), the send side now registers each
embedded payload with context, and the missing receive side exists —
`OpAdmiral.poll_oob()` attributes callbacks to findings (enrich + confirm, or
synthesize a blind finding) and a background poll loop drives it in the live
path; 23 new offline tests. **S8.2 (reasoning-model empty-content guard +
per-task `max_tokens`) is DONE**: every stop now asks for a concrete
task-sized budget (`TASK_MAX_TOKENS`, default 160 — clears the ~100-token
reasoning budget), a 200 with empty `text` + `output_tokens>0` is retried
once at 3× the budget, and a still-empty stop rotates; "all stops 200-empty"
is surfaced to the agent flagged (`raw["empty_content"]=True`), **not** a
`NoBudgetError` (that stays reserved for all-stops-hard-failed). 12 new
offline tests (`tests/test_s5_router.py::TestS82EmptyContentGuard`) + a live
probe (`scripts/s82_live_probe.py`, PASS — a real Groq `gpt-oss-120b`
`triage_decision` returned `'CONFIRMED'` non-empty/unflagged at $0), suite at
239. **S8.3 (housekeeping sweep) is DONE**: (a) `datetime.utcnow()` →
timezone-aware `datetime.now(timezone.utc)` at all 4 control-plane sites
(`core/types.py` ×2, `budget/token_tracker.py`, `compliance/egress_proxy.py`)
— suite warnings 183 → 1; (b) `pyproject.toml` trimmed to what the control
plane actually imports (base keeps `fastapi` — a real S7 test-time dep —
`pydantic`, `aiohttp`, `mitmproxy`; `uvicorn`/`chromadb`/`pyyaml`+`cvss` →
`live`/`memory`/`reporting` extras; never-imported `requests` dropped);
(c) the mempalace `:8000` note above re-confirmed (still unconfirmed — now
precise). Remaining in order: **S8.4** first live hunt on an
operator-authorized target (held until a target is ready); **S8.5** the S7.4
war-room visual smoke (during S8.4). `LOCAL_HEAVY` stays off throughout (Groq
`qwen3.8-27b` covers heavy reasoning at $0).

**Security:** API keys live only in the gitignored `.env`. (A 2026-10-15
incident placed 4 free-tier keys in a tracked working-copy doc; they were moved
to `.env` and the doc redacted — the operator has confirmed the file is clean.)
Nothing secret is committed; the 8 component clones are gitignored.

---

## 6. Environment (keys)

`main.py` loads `.env` from the repo root at start (real environment variables
always win). `.env` is **gitignored**. Current keys (see `docs/provisioning.md`
for what each lane is used for):

```
GROQ_API_KEY=            # primary FREE lane
OPENROUTER_API_KEY=      # failover lane (S5) — $10 top-up applied (2026-10-17), paid overflow live
MISTRAL_API_KEY=         # code lane (Codestral) (S5)
GEMINI_API_KEY=          # long-context RESTRICTED lane (S5)
GITHUB_TOKEN=            # GitHub Models PAID_PREMIUM frontier (S5) — upstream RETIRED 2026-07-30, 401s
OLLAMA_URL=              # default http://127.0.0.1:11434
LOCAL_HEAVY_URL=         # set when a 27B GPU endpoint is spun up (off by default)
LOCAL_HEAVY_API_KEY=
LOCAL_HEAVY_HOURLY_COST=
INTERACTSH_MODE=         # "public" | "selfhosted" | "off" (S8.1) — "off" = fail-open no-op
INTERACTSH_URL=          # self-hosted Interactsh base (public mode uses oast.pro)
INTERACTSH_API_TOKEN=    # optional; sent as Bearer when set
```

The **dry-run and the whole test suite need none of these.** Only the live FREE
lanes (S5) and a live `LOCAL_HEAVY` GPU need keys.

> **`.env` hygiene (S5b finding, 2026-10-17):** placeholder values
> (`ghp_REPLACE_ME`, empty, `sk-or-xxxx…`) are normalized to *unset* by
> `core/config.py::_clean_key()`, so a half-filled `.env` can no longer
> advertise a fake-enabled provider. `GITHUB_TOKEN` is one such placeholder in
> `.env`; a real PAT in the shell environment still overrides it (dotenv
> `override=False`) — if so, rotate it, since it has been printed in session
> logs. The GitHub Models inference service behind it was retired upstream
> 2026-07-30, so even a valid PAT 401s; the PAID_PREMIUM chain falls through to
> the OpenRouter paid stop.

---

## 7. Map of the docs

| File | Purpose |
|---|---|
| `OPERATIONS.md` | **This file.** The entry point. |
| `specs/assembly_plan_v3.md` | The approved plan (S0–S7) + gate definitions + current status. |
| `docs/hunt_cheatsheet.md` | **The hunt-day field manual** — step-by-step live run + pitfall/error table (incl. the manual browser scope path for platforms without APIs, e.g. YesWeHack). Read it on hunt day. |
| `docs/archive/legacy-v2/` | Archived v2.1.x doc corpus (10 files, incl. the phase-by-phase `progress_report.md`) — historical record, superseded; see its `README.md`. |
| `docs/trust_audit.md` | S2 verification verdicts + the F1–F6 fixes + findings. |
| `docs/provisioning.md` | Accounts, keys, hardware, and the S0.7 AMD check. |
| `patches/local-tweaks.md` | All local component modifications + the §7 re-apply recipe. |
| `CREDITS.md` | Provenance, licenses, and **pin commits** for the 8 components. |
| `model_routing_guide.md` | LLM routing & task allocation — **current** (rewritten to the shipped S5 4-tier, multi-provider router, 2026-10-17). |
| `docs/reference/storm-hunt/` | Archived STORM-HUNT orchestrator reference (read-only, separate project). |
