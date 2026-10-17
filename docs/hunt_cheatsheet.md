# Hunt Cheat Sheet — Ult_harness (v3.0, S8)

The on-hunt-day guide: how to run the harness to full potential and how to
read the failure modes. Canonical state lives in `OPERATIONS.md`; the plan in
`specs/assembly_plan_v3.md`; this file is the field manual.

Read order on hunt day: §1 preflight → §2 scope intake → §3 live run →
§5 levers (while it runs) → §4 only when something is wrong.

## 0. What the harness actually is (60-second model)

The control plane (`:8001`) does NOT scan. It is the guardrail brain:
egress/scope enforcement, model routing, budget ledger, OOB correlation,
triage state machine, reports, memory filing. The 8 fetched components do
the recon/exploit work and **call back** into the harness:

    component (via egress proxy :8080)
      └─> POST /api/triage/callback   (finding in)
      └─> POST /api/v1/llm/route      (LLM task out → 4-tier router)
      └─> POST /api/tokens/record     (token mirroring)
    Interactsh (OOB)  ──15s poll──>  admiral.poll_oob()   (blind confirmation)
    you (browser)     ── :8001/ ──  war room (state / findings / budget / routing)

So a "live hunt" = `main.py run` (spawns mitmdump `:8080` + uvicorn `:8001` +
OOB poll loop) + the operator working the components + watching the war room.
There is no autonomous one-click runner; the operator drives.

## 1. Preflight (15 min, before every hunt)

1. Suite green (no network, no keys needed):

       cd Ult_harness
       PYTHONPATH=.venv/lib/python3.13/site-packages python3 -m pytest tests/ -q

   → expect `239 passed, 1 warning` (the warning is an unrelated
   httpx2/Starlette note).
2. `.env` at repo root (gitignored; copy from `.env.example`). Minimum viable:
   - `GROQ_API_KEY` — the $0 workhorse (`gpt-oss-120b` primary,
     `qwen/qwen3.8-27b` heavy reasoning).
   - `OPENROUTER_API_KEY` — the $10-top-up `:free` failover pool.
   - `INTERACTSH_MODE=public` (default) — or `selfhosted` + `INTERACTSH_URL`
     (+ optional `INTERACTSH_API_TOKEN`), or `off` (blind findings will then
     **never** auto-confirm — a deliberate choice, not a failure).
   - Leave `LOCAL_HEAVY_URL` blank (GPU stays off; Groq 27B covers heavy at $0).
3. Ollama up on `:11434` (the $0 floor; the S4.3 invariant is "no paid spend
   when no paid keys" — an Ollama-only run is the safe rehearsal mode).
4. `which mitmdump` — if missing, **fix it, don't hunt**: a live run without
   mitmproxy logs a warning and runs with egress **unguarded** (the scope gate
   has no enforcement point).
5. Live mode uses the repo venv (system python is PEP-668 locked):

       .venv/bin/python main.py ...

   The test suite runs on system python (aiohttp + mitmproxy are
   system-installed; only fastapi/uvicorn live in the venv).

## 2. Scope intake (the part platforms without APIs make manual)

`init` needs a scope file in one of four shapes:

- **HackerOne** — program-scope CSV (columns `asset_identifier`, `asset_type`,
  `eligible_for_bounty`) → `--format hackerone_csv` (`.csv` auto-inferred).
- **Bugcrowd** — program-scope JSON
  `{"targets":[{"name","category","in_scope"}]}` → `--format bugcrowd_json`
  (`.json` auto-inferred).
- **YesWeHack / Intigriti** — no API key exists and the importers are stubs
  (`NotImplementedError` in `compliance/scope_importer.py`) → do the manual
  browser path:

  **Manual browser scope fetch (YesWeHack et al.):**

  1. In your live browser (logged in), open the program's scope/rules page.
  2. Copy every in-scope asset (URLs, wildcards, CIDRs) into a
     Bugcrowd-shaped JSON file, e.g. `scope_ywh.json`:

         {"targets": [
           {"name": "*.victim.fr",     "category": "URL", "in_scope": true},
           {"name": "api.victim.fr",   "category": "URL", "in_scope": true},
           {"name": "staging.victim.fr","category": "URL", "in_scope": false}
         ]}

     Entries starting `*.` parse as WILDCARD; everything else as EXACT. Keep
     the platform's out-of-scope list too — the egress gate blocks on it.
  3. Feed it in as Bugcrowd-shaped, but tag the **platform** correctly so the
     attribution header is right:

         .venv/bin/python main.py init --platform yeswehack \
             --program victim-fr --scope-file scope_ywh.json \
             --format bugcrowd_json --researcher yourhandle \
             --workspace ./workspace

     (`--platform yeswehack` sets the `X-YesWeHack-User` attribution header;
     the JSON shape stays Bugcrowd-compatible. `--platform intigriti` works
     the same way for Intigriti.)

`init` prints the rule counts — **verify them against the program page before
trusting anything downstream**, then check on disk:

- `workspace/<program>/scope.json` — the rules the egress gate enforces
- `workspace/<program>/headers.txt` — attribution export
- `workspace/<program>/platform_profile.json`

Rehearse first: dry-run the whole graph against a scratch workspace (zero
packets, zero cost; a report must land in `ws/<program>/reports/` with a $0
budget — the exact recipe is OPERATIONS §3.2).

## 3. The live run (step by step)

    cd Ult_harness
    .venv/bin/python main.py init  --platform <p> --program <handle> \
        --scope-file <file> --researcher <you> --workspace ./workspace
    .venv/bin/python main.py run   --program <handle> --workspace ./workspace

`run` (no `--dry-run`) does, in order:

1. Router boot: `startup_health_check()` (raises if **no** backend is
   configured at all) + `startup_discovery()` (reconciles every enabled
   provider's live `/models` catalog — fail-open).
2. Opens the hunt-wide Interactsh session (fail-open — a dead OOB never
   blocks the hunt).
3. Bootstraps auth sessions **only** if `platform_profile.json` carries
   `auth` (else skipped).
4. Spawns `mitmdump --listen-port 8080` with the egress addon.
5. Starts uvicorn on `:8001` (harness API + war room, same origin).
6. Starts the OOB poll loop (every 15 s → `admiral.poll_oob()`).

Teardown on Ctrl-C is ordered: OOB poll loop → Interactsh deregister →
mitmdump. `main.py stop --program <handle>` prints the manual teardown order
if you need it.

**While it runs:**

- Open `http://127.0.0.1:8001/` (or `/war_room`). Four panels: **Hunt
  State**, **Findings**, **Budget** (per-provider buckets + GPU-hour meter +
  $0.50 session projection), **Model Routing** (per-provider tier / lane /
  state / catalog drift). The UI renders **no keys** (`has_key` booleans only).
- Operator controls: **HALT / RESUME** (idempotent kill switch — a halted
  admiral skips new dispatches) and **confirm / reject** per finding.
- Work the components — they egress through `:8080`; every request is
  scope-gated and logged to `workspace/<program>/logs/egress_proxy.jsonl`.
- Findings arrive at `POST /api/triage/callback` and walk
  RECEIVED → VALIDATING → CONFIRMED (or get noise-filtered / rejected).
- Blind classes (SSRF / RCE / XXE) reach CONFIRMED **only** via an Interactsh
  callback: the poll loop attributes it (enrich + confirm, or synthesizes an
  `oob_<hex8>` finding). Callbacks are claimed exactly once.

## 4. Pitfalls & errors (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| `NoBudgetError` at dispatch | Every stop in the task's chain hard-failed — **or** Ollama-only config + a paid-preferred task (by design: the S4.3 invariant) | Check `GET /api/v1/providers` (`has_key`), then the provider's actual error (401/404 = bad key or model ID; 429 = throttled). Ollama-only: that task simply can't run paid — expected, not a bug. |
| Response carries `raw["empty_content"]=true` | S8.2 guard: 200 but blank text even after one 3× retry (160→480) | The router already did everything it will — the **agent** decides what to do with a flagged-empty answer. Consensus can never confirm on empty text (fail-closed). Usually transient reasoning-model behavior: re-dispatch the task; if it persists, the provider is degraded/throttled. |
| Frequent 429s / slow tasks | Free-tier RPD limits (OpenRouter `:free` = 1,000/day; per-provider limiters) | The router rotates within a provider automatically. If the whole pool is exhausted the task fails → wait, or `HARNESS_DISABLE_<PROV>=1` the flapping provider to shorten the chain. |
| Blind findings stuck in VALIDATING | No OOB callback arrived | Check `INTERACTSH_MODE` (`off` = they'll never confirm — by choice), the Interactsh console for the payload, and `INTERACTSH_API_TOKEN` for self-hosted. The hunt is NOT broken — OOB correlation is fail-open. |
| `mitmdump not found on PATH` warning at boot | mitmproxy missing | **Stop.** Egress is unguarded. `pip install mitmproxy` in the venv, re-run. |
| A provider silently absent from routing | Placeholder key in `.env` (`sk-or-xxxx…`, empty, `ghp_REPLACE_ME`) | `core/config.py::_clean_key` normalizes placeholders to *unset*, so the provider drops off the chain quietly. Put in a real key or `HARNESS_DISABLE_<PROV>=1` deliberately; verify with `GET /api/v1/providers`. |
| GitHub Models 401s in the chain | The GitHub Models inference service was **retired upstream 2026-07-30** | Not a bug — PAID_PREMIUM falls through to the OpenRouter paid stop. Optionally drop `GITHUB_TOKEN` from `.env` to stop the 401 noise. |
| Memory lookups return nothing | mempalace's default URL is `:8000`, but its shipped HTTP surfaces are the daemon (ephemeral port) + MCP JSON-RPC — no confirmed `:8000` REST `/search` | Best-effort fail-open by design; the hunt never fails on this. If memory matters, run mempalace explicitly and point `HARNESS_MEMPALACE_URL` at a live surface (see OPERATIONS §5 known-gap 3). |
| `pip install` refused on system python | PEP-668 externally-managed environment | Live mode: always `.venv/bin/python`. Tests: system python + `PYTHONPATH=.venv/lib/python3.13/site-packages`. |
| War room "doesn't exist" on `:3333` | Legacy v2.x docs (T3MP3ST) are archived now | The war room is same-origin on **`:8001`** (S7). Open `http://127.0.0.1:8001/`. |
| Dry-run shows non-zero budget | Regression — a dry-run makes no real LLM calls | Fail the hunt setup and report it. Dry-run budget must be $0. |
| An old `ghp_` PAT in the shell env | Once printed in session logs; shell env overrides `.env` (dotenv `override=False`) | Rotate it at GitHub, then `unset GITHUB_TOKEN` / scrub the shell profile. |
| Scope rule count off after `init` | Copy-paste error in the manual scope file (or a stray space in the wildcard) | Re-check `scope.json` against the program page. Wildcards need the exact `*.` prefix. |
| Component works fine standalone but ignores the harness | `HARNESS_*` env vars not exported (component-side wiring is env-gated + fail-open by design) | Run the component **under** `main.py run` (it exports them), or export `HARNESS_*` yourself for a manually-started component (see `patches/local-tweaks.md` §7). |

## 5. Running it to full potential (the levers)

- **Cost stays $0 by default.** Groq's free tier carries primary
  (`gpt-oss-120b`) + heavy reasoning (`qwen/qwen3.8-27b`); OpenRouter `:free`
  (post-$10-top-up), Mistral, and Gemini join the failover pool. Paid
  overflow (PAID_PREMIUM via an OpenRouter paid stop) exists but only fires
  on paid-preferred tasks. Keep `HARNESS_MAX_SESSION_COST` low (default
  10.00; the war room projects the $0.50 session line) so a bad day can't
  become a bill.
- **Every LLM call is lane-aware.** SAFE vs RESTRICTED data is scrubbed
  pre-call (`compliance/scrub.py`); the war room's RESTRICTED re-route
  counter moving is the scrub firing.
- **Two-model consensus on validation tasks is fail-closed** — a missing,
  failing, or empty partner never confirms a finding. Don't "fix" a stuck
  confirmation by loosening consensus; let the finding stay VALIDATING.
- **OOB is your blind-class weapon.** Payloads register per-context
  (`generate_payload(context=...)`), and the 15 s poll confirms SSRF/RCE/XXE
  with zero manual work — that's the S8.1 payoff.
- **The evidence trail is automatic.** Reports → `workspace/<p>/reports/`,
  raw + OOB evidence → `workspace/<p>/evidence/`, every egress decision
  (allow/block + reason) → `workspace/<p>/logs/egress_proxy.jsonl`. S8.4's
  gate is literally this trail staying intact.
- **GPU is a config flip, not a project.** Once the AMD Developer GPU hours
  are confirmed: set `LOCAL_HEAVY_URL` (+ `LOCAL_HEAVY_API_KEY`, hourly
  cost) in `.env` and the LOCAL_HEAVY tier joins — everything else unchanged.
  Until then Groq's 27B covers heavy reasoning at $0.
- **Rehearse, then hunt.** An Ollama-only live run is a zero-spend full-path
  rehearsal (S4.3: with no paid keys, no task can resolve to a paid tier).
  Do one before every new program.

## 6. Post-hunt (close the S8.4 gate)

1. A real report on disk (`workspace/<p>/reports/`) for every confirmed
   finding.
2. Evidence trail intact: raw responses + OOB callbacks present in
   `evidence/`.
3. Per-provider budget buckets ≤ the $0.50 session line (war room Budget
   panel).
4. Operator confirmations recorded in the war room (confirm/reject per
   finding).
5. **S8.5 visual smoke** — do it *during* the hunt, not after: the four
   panels render; the RESTRICTED re-route counter moves when a scrub fires;
   the red **HALT** actually stops dispatch.
6. Tidy up: teardown in order (`main.py stop`), archive the workspace, note
   anything new in OPERATIONS §5 (known gaps). Never commit `.env`; rotate
   any PAT that leaked into logs.
