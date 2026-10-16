# OPERATIONS — Ult_harness

The single canonical operating document. If you are a new agent session (or a
new operator) and you have nothing else, this file is enough to verify the
harness end-to-end. It tells you **what exists, what is verified, how to run
it, and what is still open.**

> **One-sentence status (2026-10-16):** Phases S0–S4 of the surgical restart
> (`specs/assembly_plan_v3.md`) are complete and committed — the Python
> control plane is built, audited (S2), and integrated end-to-end (S4) with a
> **154-test suite all green**. Phase S5 (model-router redesign) is **held**
> pending a small operator top-up; everything below that does not depend on S5
> is live and runnable today.

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
# → 154 passed   (104 S2 audit + 45 S3 core + 5 S4 E2E)
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

### 3.3 Run live (real components, real LLM) — S5-dependent

`python main.py run --program <p>` (no `--dry-run`) spawns `mitmdump` +
`uvicorn` and exports the `HARNESS_*` env vars that make the fetched components
talk back into the harness. **Hold until S5 is done** (see §5) — the model
router is still the pre-S5 3-tier version and the FREE provider lanes are not
yet wired. When S5 lands this section is updated.

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

1. **S5 — model-router redesign: HELD.** The current router is the pre-S5
   3-tier (`LOCAL / PAID_FREE / PAID_PREMIUM`, single Groq free tier). The S5
   rework — 4-tier structure (adds `LOCAL_HEAVY`), the multi-provider FREE pool
   (Groq primary, OpenRouter failover, GitHub Models, Mistral, Gemini),
   per-provider rate limiters + 429 rotation, runtime `/models` discovery,
   data-lane (SAFE/RESTRICTED) scrub hook, per-provider tracker buckets — is
   fully specified in `specs/assembly_plan_v3.md` S5.1–S5.7 but **not
   implemented**. It is held pending a **$10 OpenRouter top-up** (operator
   action) so the live 200-per-provider gate item can be verified. Until S5:
   treat the LIVE run path (3.3) as not-ready; the dry-run and all tests are
   unaffected and the S4.3 "no paid spend" invariant still holds.
   - `model_routing_guide.md` is therefore **stale** — see its supersession
     banner. It will be rewritten from S5.2–S5.7 when S5 lands.
2. **S0.7 — AMD Developer pack cloud-GPU hours: UNVERIFIED.** No local
   artifacts found; needs a manual login to the AMD developer portal. Until
   then `LOCAL_HEAVY` is **off/optional** and heavy reasoning leans on the free
   `qwen/qwen3.8-27b` (Groq). Record the result in `docs/provisioning.md`.
3. **Mempalace `:8000` REST surface — NOT confirmed.** Mempalace ships as the
   ChromaDB/MCP/daemon package; there is no confirmed `:8000` REST endpoint.
   Every mempalace call from the components is **best-effort fail-open** (a
   dead palace never breaks a hunt). Local JSONL stays authoritative. Gap
   documented in `patches/local-tweaks.md` §7.
4. **OOB interaction correlation is a skeleton.** `OOBEngine.poll_callbacks`
   returns `[]`; no Interactsh API integration (S2 finding N3). Shape/contract
   verified; the real OOB correlate is post-S4 work.
5. **Minor housekeeping.** `datetime.utcnow()` deprecation warnings on Python
   3.13 (S2 finding N4) — cosmetic, sweep is deferred. `pyproject.toml` still
   lists aspirational deps (`fastapi`, `chromadb`, `cvss`) the control plane
   does not import at test/dry-run time (S2 finding N2); they are only pulled
   in live/ingest paths.

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
OPENROUTER_API_KEY=      # failover lane (S5) — apply $10 top-up before S5
MISTRAL_API_KEY=         # code lane (Codestral) (S5)
GEMINI_API_KEY=          # long-context RESTRICTED lane (S5)
GITHUB_TOKEN=            # GitHub Models free frontier (S5)
OLLAMA_URL=              # default http://127.0.0.1:11434
LOCAL_HEAVY_URL=         # set when a 27B GPU endpoint is spun up (off by default)
LOCAL_HEAVY_API_KEY=
LOCAL_HEAVY_HOURLY_COST=
```

The **dry-run and the whole test suite need none of these.** Only the live FREE
lanes (S5) and a live `LOCAL_HEAVY` GPU need keys.

---

## 7. Map of the docs

| File | Purpose |
|---|---|
| `OPERATIONS.md` | **This file.** The entry point. |
| `specs/assembly_plan_v3.md` | The approved plan (S0–S6) + gate definitions + current status. |
| `progress_report.md` | Phase-by-phase narrative of what was built and why. |
| `docs/trust_audit.md` | S2 verification verdicts + the F1–F6 fixes + findings. |
| `docs/provisioning.md` | Accounts, keys, hardware, and the S0.7 AMD check. |
| `patches/local-tweaks.md` | All local component modifications + the §7 re-apply recipe. |
| `CREDITS.md` | Provenance, licenses, and **pin commits** for the 8 components. |
| `model_routing_guide.md` | LLM routing — **STALE, superseded by S5** (see its banner). |
| `docs/reference/storm-hunt/` | Archived STORM-HUNT orchestrator reference (read-only, separate project). |
