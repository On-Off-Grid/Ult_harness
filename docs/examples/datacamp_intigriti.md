# Worked example — DataCamp (Intigriti): setup for any future hunt

The concrete, copy-paste version of `docs/hunt_cheatsheet.md` for one real
program: **DataCamp** on Intigriti
(`app.intigriti.com/researcher/programs/datacamp/datacamp/detail`).
Every command below was run against the live program on 2026-10-18 and
verified (scope fetched, dry-run walked, report landed). This file is
*what to type*; the cheat sheet is *why*; `docs/hunt_workflow.md` is the
mental model (how the component repos fit together and who orchestrates whom).

**Program facts (from the Researcher API, 2026-10-18):**

- handle `datacamp` — status **Open**, type **Bug Bounty**
- **26 in-scope assets** (exact hosts + 2 wildcards), **0 out-of-scope**,
  **2 mobile apps** (manual-only — not egress-able through mitmproxy)
- RoE mandates **no** special User-Agent or request headers, so the default
  attribution headers from `init` are all you need

## The one-command path (S8.4 — start here)

Preflight (Step 0) first, then the whole hunt is one command:

```bash
cd Ult_harness
.venv/bin/python main.py hunt --platform intigriti --program datacamp \
    --tools jsleak,cbb \
    [--targets app.datacamp.com,www.datacamp.com]   # optional
```

That one line does Steps 1–5 automatically, in order:
**preflight** (mitmdump/keys/workspace — one-line `✗` on failure) →
**scope** (auto-fetches from the Intigriti Researcher API into
`scope_files/datacamp.json`; re-verify the 26 against the program page on the
first fetch of the day) → **init** → **dry-run** (must end **$0** or the
command stops) → **boots the control plane** (`:8001` war room + `:8080`
egress gate) → **launches your tools** (each egressing only through the
scope gate). Ctrl-C tears everything down in order (tools first) and saves
`workspace/datacamp/hunt_state.json`.

- `--tools` — which components to launch (the operator's choice per program
  scope): `jsleak` (JS secrets/links — one process over the whole scope
  list), `cbb` (claude-bug-bounty agent — one per `--targets` host, default
  the first 3 exact-match hosts), plus the optional aux `adhd`,
  `agent-reach` (see "What is a component?" in Step 5). Omit `--tools` to
  boot the control plane only.
- `--targets host1,host2` — override the auto-derived per-target hosts.
  The 26 rules include the wildcards `*.datacamp.com` /
  `*.it.datacamp.com` which are **not** expanded (no subdomain enumeration
  in-repo) — pass explicit subdomains you care about here.
- **Pausing for a logout:** Ctrl-C at any time = graceful pause (ordered
  teardown + state saved). Come back any time with:

      .venv/bin/python main.py resume --program datacamp \
          --workspace ./workspace

  `resume` re-runs preflight → scope → init → dry-run → boot → the same
  tools/targets. What survives the stop and what doesn't is stated honestly
  in `workspace/datacamp/hunt_state.json` (`durable` = reports/evidence/
  egress log on disk; `volatilized_on_stop` = in-memory tasks/triage/budget/
  OOB session). If the old control plane somehow survived your logout,
  `resume` detects it and tells you exactly how to tear it down instead of
  double-booting.

Below, the manual step-by-step (Steps 0–7) is kept as the **fallback and
understanding layer** — the `hunt` command runs exactly these steps, and if
anything automated looks wrong, drop into the manual path.

## Step 0 — Preflight (5 min, once per hunt day)

```bash
cd Ult_harness

which mitmdump                                # must resolve — else egress is UNGUARDED, don't hunt
curl -sf http://127.0.0.1:11434/api/tags >/dev/null && echo "ollama up"   # $0 floor
grep -E "^(GROQ_API_KEY|OPENROUTER_API_KEY|INTIGRITI_API_KEY)=" .env \
    | sed 's/=.*/=<set>/'                     # expect all 3 lines
```

Keys live in gitignored `.env` (see `.env.example`): `GROQ_API_KEY` ($0
workhorse), `OPENROUTER_API_KEY` (failover), `INTIGRITI_API_KEY` (used **only**
by the fetch script — the control plane never calls platform APIs), and
`INTERACTSH_MODE=public`.

## Step 1 — Fetch DataCamp's scope from Intigriti (read-only API calls)

```bash
.venv/bin/python scripts/fetch_intigriti_scope.py list --search datacamp
#   datacamp   Open   Bug Bounty   DataCamp  (id=bd22f48d-633e-4b26-bf71-e4778d41b247)

.venv/bin/python scripts/fetch_intigriti_scope.py datacamp -o scope_files/datacamp.json
```

Expect: `in-scope rules : 26`, `out-of-scope : 0`, `mobile (skip) : 2`,
`RoE present : yes`. **Verify the 26 against the program page's asset list —
if the counts disagree, stop** (the page changed; re-fetch or re-read).
The 2 mobile apps (`com.datacamp`, the iOS app) are *excluded* from the scope
file on purpose (not egress-able) and are listed under
`_mobile_apps_manual_only` in the JSON if you want to test them by hand.

## Step 2 — Rehearse the graph (dry-run in a scratch workspace: zero packets, zero cost)

```bash
W=$(mktemp -d /tmp/dc.XXXXXX)          # if $W is empty when you type this, init
                                        # now fails fast with a clear [init] error
.venv/bin/python main.py init --platform intigriti --program datacamp \
    --scope-file scope_files/datacamp.json --format bugcrowd_json \
    --workspace "$W/ws"                 # --researcher defaults to onoffgrid
.venv/bin/python main.py run --program datacamp --dry-run --workspace "$W/ws"
ls "$W/ws/datacamp/reports/"     # → 1 mock report
rm -rf "$W"
```

Expect the walk to end with:

```
[dry-run] ✅ full graph walked: config → gate → admiral → report → memory
[dry-run] status      : {… "budget": {"total_cost_usd": 0 …}}
```

**If the dry-run budget is not $0, do not go live** (cheatsheet §4).

## Step 3 — Init the real workspace

```bash
.venv/bin/python main.py init --platform intigriti --program datacamp \
    --scope-file scope_files/datacamp.json --format bugcrowd_json \
    --workspace ./workspace             # --researcher defaults to onoffgrid
```

Expect `in-scope: 26 rule(s) / out-of-scope: 0 rule(s)`. Creates
`workspace/datacamp/` with: `scope.json` (the rules the egress gate enforces),
`headers.txt` (attribution — `X-Intigriti-Researcher: onoffgrid` +
`User-Agent: Mozilla/5.0 (BugBounty; intigriti/onoffgrid)`; use
`--researcher <other>` to override),
`platform_profile.json`, and `logs/ reports/ evidence/`.

## Step 4 — Live run (terminal 1)

```bash
.venv/bin/python main.py run --program datacamp --workspace ./workspace
```

Boot order: router health check → Interactsh OOB session → `mitmdump :8080`
(egress gate) → uvicorn `:8001` (API + war room) → OOB poll loop (15 s).
At boot, confirm there is **no** `mitmdump not found on PATH` warning — if
there is, Ctrl-C and fix it: with no proxy the egress gate has no
enforcement point and you are hunting unguarded.

## Step 5 — Work the components (terminal 2)

All component traffic must route through the egress proxy:

```bash
export HARNESS_API_URL=http://127.0.0.1:8001
export HARNESS_EGRESS_PROXY=http://127.0.0.1:8080
export HTTP_PROXY=http://127.0.0.1:8080
export HTTPS_PROXY=http://127.0.0.1:8080
export NO_PROXY=localhost,127.0.0.1
```

> **What's a "component"?** One of the 8 external recon/exploit tools
> fetched into the repo root — `jsleak/`, `claude-bug-bounty/`, `adhd/`,
> `Agent-Reach/`, plus the support tools `Awesome-Redteam/`, `CL4R1T4S/`,
> `mempalace/`, `T3MP3ST/` (canonical list in `CREDITS.md`). The harness
> itself **never scans**: the component does the probing, and the
> `HARNESS_*` exports above + the `:8080` proxy wire it back in, so every
> request is scope-gated and every finding is reported automatically.
> `<your-component>` = whichever of these you're running now (each has its
> own CLI — e.g. `jsleak` for JS secrets, `claude-bug-bounty` for general
> recon). The `hunt` command (top of this file) does this export + launch
> for you; the manual block is the fallback.

Then point your recon/exploit components at the in-scope assets (26 rules;
the two wildcards `*.datacamp.com` and `*.it.datacamp.com` cover most of
them). Examples:

```bash
<your-component> --target https://app.datacamp.com/learn
<your-component> --target https://www.datacamp.com/datalab
```

Every request is scope-gated: in-scope → forwarded; anything else →
**blocked and logged with a reason** to
`workspace/datacamp/logs/egress_proxy.jsonl` (that log is your proof of
discipline if a report is ever disputed).

## Step 6 — Watch the war room (browser)

```
http://127.0.0.1:8001/
```

Four panels: **Hunt State**, **Findings**, **Budget**, **Model Routing**.
While it runs:

- Findings walk RECEIVED → VALIDATING → CONFIRMED (or get noise-filtered).
- Blind classes (SSRF / RCE / XXE) confirm **only** via an Interactsh
  callback — the 15 s poll handles it; no manual work.
- **confirm / reject each finding here** — this is your final severity call.
  (The report's *initial* severity is static by category: SQLi/RCE →
  Critical, SSRF → High, everything else → Medium — cheatsheet §2.5.)
- **HALT** = kill switch (idempotent); **RESUME** = continue.

## Step 7 — Teardown + close the loop

Ctrl-C in terminal 1 (ordered teardown: OOB loop → Interactsh deregister →
mitmdump; the API dies with the process). Reprint the teardown order any
time with `.venv/bin/python main.py stop`. Leave Ollama running.

Then close the post-hunt gate (cheatsheet §6): a report on disk for every
confirmed finding, evidence intact in `evidence/`, per-provider budgets under
the $0.50 session line, your confirm/reject decisions recorded.

## DataCamp-specific notes

- `intranet.datacamp.com`, `jira.datacamp.com`, `confluence.datacamp.com`
  are **in scope** (unusual — treat them as the crown jewels; IDOR/BAC/authz
  are the high-value classes there).
- The API reported **0 out-of-scope assets** on 2026-10-18. Re-check the
  program page before each hunt — if DataCamp later adds exclusions,
  re-fetch (the script re-reads the live scope) or add `"in_scope": false`
  rules to `workspace/datacamp/scope.json` (the gate blocks + logs them).
- Mobile apps are manual-only (never egress through the proxy).
- RoE: detailed but to-the-point repro steps, clear attack scenario,
  English, no public PoC without consent, ~2-week response target, safe
  harbour applies. The harness does not enforce RoE — you do.

## If something goes wrong (the ones that matter for this run)

| Symptom | Fix |
|---|---|
| Fetch script 403 | ToE changed (re-accept in the Intigriti UI) **or** rate limit (600 GETs/5 min → wait ~5 min). Persistent 403/404 → copy the scope by hand into `scope_files/datacamp.json` (Bugcrowd shape) and re-init. |
| `init` count ≠ program page | Scope drift — re-fetch, don't init. |
| Dry-run budget > $0 | Stop — regression. Fix before live. (`hunt` refuses to go live on its own.) |
| `mitmdump not found` warning at boot | Egress unguarded — Ctrl-C, `pip install mitmproxy` in the venv, re-run. |
| Blind finding stuck in VALIDATING | Check the Interactsh console for the callback; `INTERACTSH_MODE=off` means they *never* confirm (a deliberate choice). |
| `hunt` stops at `[hunt] ✗` (preflight) | One-line reason is printed: mitmdump missing (install), `:8001` already serving (a previous hunt is still up — tear it down per `main.py stop`, or `resume` it), no LLM backend configured (check `.env`). |
| `resume` says "no saved state" | The hunt never reached boot (state is written at boot and on every stop). Just re-run `hunt` — there is nothing to resume yet. |
| `resume` says "a control plane is already up on :8001" | Your logout killed `hunt` but the child survived. It prints the exact teardown (`kill <pid>` / `pgrep -f 'main.py run --program datacamp'`); do that, then re-run the same `resume`. |
| `[hunt] note : cbb: skipped — …` | That one tool failed its own pre-check (e.g. `agent.py --help` doesn't exit 0 — missing deps) — the hunt continues without it; fix the tool separately if you want it in. |

Everything else is in `docs/hunt_cheatsheet.md` §4 (full symptom table).
