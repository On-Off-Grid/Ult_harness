# Hunt Cheat Sheet — Ult_harness (v3.0, S8)

The on-hunt-day guide: how to run the harness to full potential and how to
read the failure modes. Canonical state lives in `OPERATIONS.md`; the plan in
`specs/assembly_plan_v3.md`; this file is the field manual.

Want the concrete copy-paste version for one real program?
`docs/examples/datacamp_intigriti.md` — a verified step-by-step setup for
DataCamp (Intigriti), from scope fetch to teardown.

Read order on hunt day: §1 preflight → §2 scope intake → §3.0 one-command
launch (+ pause/resume) or §3 manual live run → §5 levers (while it runs) →
§4 only when something is wrong.

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

A **"component"** = one of the 8 external tools `scripts/fetch_components.sh`
clones into the repo root as sibling dirs (`jsleak/`, `claude-bug-bounty/`,
`adhd/`, `Agent-Reach/`, `Awesome-Redteam/`, `CL4R1T4S/`, `T3MP3ST/`,
`mempalace/` — canonical list in `CREDITS.md`). The recon/exploit ones are
what you point at in-scope targets; they egress through the proxy and call
back with findings.

So a "live hunt" = `main.py run` (spawns mitmdump `:8080` + uvicorn `:8001` +
OOB poll loop) + the operator working the components + watching the war room.
Since S8.4 there is a one-command supervisor (`main.py hunt`, §3.0) that
boots all of that and launches the components you select — the operator
still drives (tool choice, targets, confirm/reject), the typing is gone.

## 1. Preflight (15 min, before every hunt)

1. Suite green (no network, no keys needed):

       cd Ult_harness
       PYTHONPATH=.venv/lib/python3.13/site-packages python3 -m pytest tests/ -q

   → expect `260 passed, 1 warning` (the warning is an unrelated
   httpx2/Starlette note; the 21 extra tests cover the S8.4 hunt launcher).
2. `.env` at repo root (gitignored; copy from `.env.example`). Minimum viable:
   - `GROQ_API_KEY` — the $0 workhorse (`gpt-oss-120b` primary,
     `qwen/qwen3.8-27b` heavy reasoning).
   - `OPENROUTER_API_KEY` — the $10-top-up `:free` failover pool.
   - `INTIGRITI_API_KEY` (optional) — used **only** by
     `scripts/fetch_intigriti_scope.py` (Intigriti scope export via the
     beta Researcher API). The control plane itself never calls platform
     APIs — this key serves your manual scope fetch, not `main.py`.
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

## 2. Scope intake (per platform — templates in `docs/scope_templates/`)

`init` needs a scope file in one of four shapes. Templates (with a
field-mapping README) live in `docs/scope_templates/`:

| Platform | Scope source | Feed `--format` |
|---|---|---|
| HackerOne | Program-scope CSV export (`asset_identifier,asset_type,eligible_for_bounty`) | `hackerone_csv` (`.csv` auto) |
| Bugcrowd | Program-scope JSON `{"targets":[…]}` | `bugcrowd_json` (`.json` auto) |
| Intigriti | **Researcher API** — `scripts/fetch_intigriti_scope.py` (or manual fallback, §2b) | `bugcrowd_json` |
| YesWeHack | **Manual browser** (no API) | `bugcrowd_json` |

**Creating a scope file from scratch** (any platform):

1. Copy the right template:
   `cp docs/scope_templates/bugcrowd_scope.template.json scope.json`
2. Replace the example `targets` with the program's real scope — and
   **transcribe the out-of-scope list too** (`"in_scope": false`): the
   egress gate blocks on those rules and logs every block with a reason to
   `workspace/<p>/logs/egress_proxy.jsonl` (your proof of discipline).
3. Field mapping (details in the template README): `name` starting with `*.`
   → WILDCARD, anything else → EXACT; `category` → description; extra keys
   (like the template's `_comment` block) are ignored by the importer.
4. Run `init` with the **platform tag matching the program** — it sets the
   attribution header (`X-YesWeHack-User`, `X-Intigriti-Researcher`, …).
   `--researcher` defaults to `onoffgrid` (the cross-platform handle):

       .venv/bin/python main.py init --platform yeswehack \
           --program <handle> --scope-file scope.json \
           --format bugcrowd_json --workspace ./workspace

5. **Verify the counts against the program page** — `init` prints the
   in/out-of-scope rule counts; if they disagree, stop and fix the file
   before trusting anything downstream. Then check on disk:
   `workspace/<p>/scope.json` (the rules the gate enforces), `headers.txt`
   (attribution export), `platform_profile.json`.
6. **CIDR / IP range / regex in the program's scope?** The importers only
   auto-assign exact/wildcard — hand-edit `workspace/<p>/scope.json` after
   `init` (`"match_type": "cidr"` / `"regex"`, plus the `rate_limit_rps` /
   `max_concurrent` pacing knobs; see
   `docs/scope_templates/scope.template.canonical.json`).

### 2a. YesWeHack — manual browser scope fetch (no API exists)

1. In your live browser (logged in), open the program's scope/rules page.
2. Copy every in-scope asset (URLs, wildcards, IP ranges) **and** the
   out-of-scope list into a Bugcrowd-shaped `scope.json`:

       {"targets": [
         {"name": "*.victim.fr",     "category": "URL", "in_scope": true},
         {"name": "api.victim.fr",   "category": "URL", "in_scope": true},
         {"name": "staging.victim.fr","category": "URL", "in_scope": false}
       ]}

   Also check the program's eligibility flags — anything excluded
   (staging, no-bounty domains, VDP-only assets) goes `"in_scope": false`.
3. `init --platform yeswehack --format bugcrowd_json` as in step 4 above —
   the platform tag (not the format) is what sets the
   `X-YesWeHack-User` header.
4. **Re-verify against the program page after init** — the manual copy is
   the one step where human error enters.

### 2b. Intigriti — API path (key in `.env`)

Intigriti's beta Researcher API covers scope end-to-end via the script
(probe-verified live 2026-10-17; docs at
`intigriti-researcher-api.readme.io/reference`):

    .venv/bin/python scripts/fetch_intigriti_scope.py list     # your programs: handle + id
    .venv/bin/python scripts/fetch_intigriti_scope.py <handle> -o scope.json
    .venv/bin/python main.py init --platform intigriti --program <handle> \
        --scope-file scope.json --format bugcrowd_json --workspace ./workspace

- `list` → `GET /v1/programs` (Bearer `INTIGRITI_API_KEY` from `.env`);
  fetch → `GET /v1/programs/{id}` (domains + rules of engagement). Rate
  limit: 600 GETs / 5 min.
- Tier mapping (the script's **editorial** call — verify against the program
  page): tier `No Bounty` → `"in_scope": false`; URL/Wildcard/API/Web →
  wildcard if `*.` else exact; Subnet/IP → `cidr`; Custom/Regex → `regex`;
  **mobile apps (iOS/Android bundles) are dropped from the scope file** —
  they're not egress-able through mitmproxy — and listed under
  `_mobile_apps_manual_only` for manual testing.
- The export prints whether RoE text is present. The script does not
  enforce RoE — **you** do (read it before the live run).
- The script's only third-party dep is `requests` (already in the repo
  `.venv`; it is *not* a control-plane dep — run it with
  `.venv/bin/python`, not system python).
- **Fallback:** API 403 (terms changed → re-accept in the Intigriti UI, or
  rate-limited → wait) / 404 (beta drift) → do the §2a manual path with
  `--platform intigriti`.
- **Full worked example** (Intigriti end-to-end, verified commands):
  `docs/examples/datacamp_intigriti.md`.

Rehearse first: dry-run the whole graph against a scratch workspace (zero
packets, zero cost; a report must land in `ws/<program>/reports/` with a $0
budget — the exact recipe is OPERATIONS §3.2).

## 2.5 What the report will say about severity (initial classifier)

There is **no severity setting** — and it is **not** critical/exceptional by
default. `reporting/taxonomy.py` applies a static, category-driven *initial*
CVSS; the report's "Severity (initial)" line is a triage aid, and the final
severity call is yours (workflow stage 7 — the war-room confirm/reject is
where it lands).

| Finding category | Initial CVSS 3.1 vector | Band |
|---|---|---|
| SQLi, RCE | `AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H` (9.7) | **Critical** |
| SSRF | `AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N` | **High** |
| All other 12 categories (XSS, IDOR, LFI, XXE, JWT, …) | `AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:L/A:N` | **Medium** |

Practical effect: a plain XSS reports **Medium (initial)** — don't be
surprised, and don't "fix" the classifier to make reports look scarier or
safer. Refine the vector **per finding** at submit time (impact statement in
the report, final severity in the platform UI). The `cvss` lib (the
`reporting` extra) is available if you want real score computation later.

## 3.0 One-command launch (S8.4) — and pausing for a logout

    cd Ult_harness
    .venv/bin/python main.py hunt --platform intigriti --program <handle> \
        --tools jsleak,cbb \
        [--targets host1,host2] [--max-targets 3]

`hunt` runs §3's manual sequence **for you**, in one foreground process:
preflight (one-line `✗` on failure) → scope (Intigriti auto-fetch via the
Researcher API when no `--scope-file` is given; other platforms need
`--scope-file`) → `init` → **dry-run ($0 gate — non-$0 stops the command)**
→ boots `run` as a child (its boot order and ordered teardown are reused
untouched) → spawns your `--tools` with the `HARNESS_*`/proxy env injected.
Ctrl-C tears down in order (tools first, then the control plane) and saves
`workspace/<p>/hunt_state.json`. `--tools` omitted = control plane only.

**The operator picks the tools per program scope** — that is the steering
lever (cheatsheet §0: the control plane never scans). Registry
(`tools/registry.py`):

| key | what it is | how it launches |
|---|---|---|
| `jsleak` | JS secrets/links scanner (Go) | 1 process, in-scope URL list on stdin, `-json` (auto `go build` once) |
| `cbb` | claude-bug-bounty ReAct agent (Python) | 1 agent **per `--targets` host** (default: first 3 exact-match hosts) |
| `adhd` | ideation (aux) | disabled by default — needs a per-hunt prompt, not safe to auto-run |
| `agent-reach` | OSINT daemon (aux) | disabled by default — not a target scanner in v1 |

Corpora (`Awesome-Redteam/`, `CL4R1T4S/`) are reference material, not
processes — they are not launchable by design. A tool that fails its own
pre-check is **skipped with a note, the hunt continues** (fail-open).

**Pausing (operator logout):** Ctrl-C at any time. It is an *honest* pause,
not a suspended animation — a live hunt's state splits in two (verified
against the code; there is no other persistence):

* **Durable on disk** (survives): `reports/`, `evidence/`,
  `logs/egress_proxy.jsonl`, `scope.json`, `platform_profile.json`.
* **Volatile** (dies with the `run` process): the admiral's task/finding
  maps, triage state, the token/budget ledger, the Interactsh session,
  launched tool processes.

`hunt_state.json` records both halves (`durable` snapshot +
`volatilized_on_stop` list). To continue:

    .venv/bin/python main.py resume --program <handle> --workspace ./workspace

`resume` re-runs preflight → (re-)scope → init → dry-run → boot → the same
tools/targets (CLI `--tools`/`--targets` override the saved selection).
Guard rails: it **refuses to double-boot** if a control plane survived the
logout and still serves `:8001` (prints the exact teardown), and it works
after a hard logout too — the state file is written at boot and on every
exit, with the control-plane pid, so there is always a resumable marker.

The manual path below is the fallback / understanding layer: `hunt` runs
exactly these steps.

## 3. The live run (step by step)

    cd Ult_harness
    .venv/bin/python main.py init  --platform <p> --program <handle> \
        --scope-file <file> --workspace ./workspace     # --researcher defaults to onoffgrid
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
mitmdump. `main.py stop` (takes no arguments) prints the manual teardown
order if you need it.

**While it runs:**

- Open `http://127.0.0.1:8001/` (or `/war_room`). Four panels: **Hunt
  State**, **Findings**, **Budget** (per-provider buckets + GPU-hour meter +
  $0.50 session projection), **Model Routing** (per-provider tier / lane /
  state / catalog drift). The UI renders **no keys** (`has_key` booleans only).
- Operator controls: **HALT / RESUME** (idempotent kill switch — a halted
  admiral skips new dispatches) and **confirm / reject** per finding.
- Work the components — they egress through `:8080`; every request is
  scope-gated and logged to `workspace/<program>/logs/egress_proxy.jsonl`.
  (`hunt` launches the ones you select from the registry — §3.0; manually
  started components need the `HARNESS_*` exports, §2.5 of the DataCamp
  example.)
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
| Intigriti API 403 from the fetch script | Terms of engagement changed (re-accept in the Intigriti UI) **or** the 600-GETs/5-min rate limit | Re-accept ToE in the UI and retry; if rate-limited, wait ~5 min. Persistent 403/404 (beta API drift) → use the §2a manual browser path instead. |
| `INTIGRITI_API_KEY` set but "not used" | By design — the control plane never calls platform APIs | The key only serves `scripts/fetch_intigriti_scope.py` (your scope export). If you don't hunt Intigriti, ignore it. It is never sent anywhere except `api.intigriti.com`. |
| Component works fine standalone but ignores the harness | `HARNESS_*` env vars not exported (component-side wiring is env-gated + fail-open by design) | Run the component **under** `main.py run` (it exports them), or export `HARNESS_*` yourself for a manually-started component (see `patches/local-tweaks.md` §7). |
| `hunt` exits 1 at preflight with a `✗` line | By design: the one-line reason is the whole problem | `mitmdump not found` → install mitmproxy in the venv. `already serving :8001` → a previous hunt/run is still up: tear it down (`main.py stop` order) or `resume` it. `no LLM backend` → check `.env` keys / Ollama. |
| `resume` refuses: "no saved state" | The hunt never reached boot (state is written at boot + on every stop) | Re-run `hunt` — nothing to resume yet. |
| `resume` refuses: "a control plane is already up on :8001" | Hard logout (SIGKILL) killed `hunt` but the child `run` survived, still holding `:8001`/`:8080` | Do the printed teardown (`kill <saved pid>` or `pgrep -f 'main.py run --program <p>'`), then re-run the same `resume`. |
| `[hunt] note : <tool>: skipped — …` during boot | That tool failed its own pre-check (missing binary/deps) — fail-open by design | The hunt runs without it. Fix the tool (e.g. `go build` for jsleak, deps for cbb) and re-`hunt`/`resume` when you want it in. |
| After `resume`, a blind finding can't confirm | Pause deregistered the Interactsh session — callbacks fired mid-gap never correlate | Stated honestly in `hunt_state.json` (`volatilized_on_stop`). Re-register the payload and re-send if the blind test still matters. |

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
