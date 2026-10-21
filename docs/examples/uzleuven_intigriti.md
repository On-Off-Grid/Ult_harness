# Worked example — UZ Leuven (Intigriti): setup for any future hunt

The concrete, copy-paste version of `docs/hunt_cheatsheet.md` for one real
program: **UZ Leuven** (Universitair Ziekenhuis — the university hospital)
on Intigriti
(`app.intigriti.com/researcher/programs/uz%20leuven/uzleuven/detail`).
Every command below was run against the live program on 2026-10-19 and
verified (scope fetched, dry-run walked, report landed, gate behavior
asserted by `tests/test_uzleuven_scope.py`). This file is *what to type*;
the cheat sheet is *why*; `docs/hunt_workflow.md` is the mental model.
(A previous version of this example covered DataCamp — same shape, simpler
scope — and is still in the git history if you want to compare.)

**Program facts (from the Researcher API, 2026-10-19):**

- handle `uzleuven` — status **Open**, type **Bug Bounty**
  (id `2cf03670-6a2d-4ac7-8b1e-2e0d84338204`)
- **22 in-scope assets** — Tier 1: 11 hosts, Tier 2: 7 (incl. a 7-IP
  reverse-proxy list), Tier 3: 4 (incl. the `*.uzleuven.*` catch-all);
  **20 out-of-scope** (12 "No Bounty" + 8 "Out Of Scope" tier);
  **0 mobile apps**
- The scope file holds **28 in-scope / 20 out-of-scope rules** — the
  7-IP list is expanded to one `/32` rule per IP (see Step 1)
- RoE **bans automatic scanners** in its free text ("We cannot accept any
  submissions found by using automatic scanners") — read the ⚠ note below
  before launching any `--tools`
- RoE asks for a `X-Intigriti-Username: {Username}` request header and
  mandates **no** special User-Agent — `init` merges this header into
  `headers.txt` automatically from the fetched scope (see Step 3)
- Safe harbour: yes

## The one-command path (S8.4 — start here)

Preflight (Step 0) first, then the whole hunt is one command — the program
handle is the **only required argument**:

```bash
cd Ult_harness
.venv/bin/python main.py hunt uzleuven
```

Bare `hunt <program>` is fully automated by these defaults:

- **platform** → `intigriti` (the only platform the harness can
  auto-fetch scope from — any other platform needs `--platform <p>`
  together with a `--scope-file`)
- **tools** → the enabled registry tools (`jsleak,cbb` today), so the hunt
  produces traffic from the first boot instead of idling; override with
  `--tools jsleak`, or `--tools none` for control-plane-only
- **targets** → the first 3 in-scope exact-match hosts (see below)

Because *this program's* free-text RoE bans automated-scanner findings (⚠
below), the line you will usually actually type is:

```bash
.venv/bin/python main.py hunt uzleuven --tools jsleak \
    [--targets www.uzleuven.be,extranet.uzleuven.be,sts.uzleuven.be]   # optional
```

> ⚠ **Read the RoE before you launch tools.** The program's free-text RoE
> says automated-scanner findings are *not acceptable*, while its structured
> field is `automatedTooling: 5` (Intigriti's scale). These disagree —
> treat the **stricter** reading as the rule: open the program page's
> "Rules of Engagement" panel and confirm the automated-tooling setting.
> If automation is disallowed, run with **`--tools none`** (control plane +
> egress gate + manual testing only) and use the war room to watch your
> manual requests. `hunt` prints the program's structured RoE facts at boot
> (an `[hunt] RoE : …` line, plus a ⚠ line when `automatedTooling` is at or
> below 1) — but it never enforces the RoE text. You do.

That one line does Steps 1–5 automatically, in order:
**preflight** (mitmdump/keys/workspace — one-line `✗` on failure) →
**scope** (auto-fetches from the Intigriti Researcher API into
`scope_files/uzleuven.json`; a cached fetch from an older script version is
refreshed automatically so the RoE metadata is never silently stale;
re-verify the 22 in-scope / 20 out-of-scope assets against the program
page on the first fetch of the day) →
**init** (merges the program's RoE attribution header into
`headers.txt` — see Step 3) →
**dry-run** (must end **$0** or the command stops) →
**boots the control plane** (`:8001` war room + `:8080` egress gate) →
**launches the tools** (default: the enabled ones; each egressing only
through the scope gate).
Ctrl-C tears everything down in order (tools first) and saves
`workspace/uzleuven/hunt_state.json`.

- `--tools` — which components to launch (the operator's choice per program
  RoE, see ⚠ above): `jsleak` (JS secrets/links — one process over the whole
  scope list), `cbb` (claude-bug-bounty agent — one per `--targets` host,
  default the first 3 in-scope exact-match hosts), plus the optional aux
  `adhd`, `agent-reach` (see "What is a component?" in Step 5). Omit to
  launch the default enabled tools; `--tools none` boots the control plane
  only.
- `--targets host1,host2` — override the auto-derived per-target hosts.
  With no override the default is the first 3 in-scope exact hosts
  (`autodiscover.uzleuven.be`, `ecrf.uzleuven.be`,
  `extranet-asa.uzleuven.be`) — internal-facing Tier 1 machines; you will
  usually want the public-facing ones (`www.`, `extranet.`, `sts.`).
  The 3 in-scope wildcards (`*.kwsdose.be`, `*.playuzleuven.be`,
  `*.uzleuven.*`) are **not** expanded (no subdomain enumeration in-repo) —
  pass explicit subdomains you care about here.

- **Pausing for a logout:** Ctrl-C at any time = graceful pause (ordered
  teardown + state saved). Come back any time with:

      .venv/bin/python main.py resume --program uzleuven \
          --workspace ./workspace

  `resume` re-runs preflight → scope → init → dry-run → boot → the same
  tools/targets. What survives the stop and what doesn't is stated honestly
  in `workspace/uzleuven/hunt_state.json` (`durable` = reports/evidence/
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
workhorse), `OPENROUTER_API_KEY` (failover), `INTIGRITI_API_KEY` (used
**only** by the fetch script — the control plane never calls platform
APIs), and `INTERACTSH_MODE=public`.

## Step 1 — Fetch UZ Leuven's scope from Intigriti (read-only API calls)

```bash
.venv/bin/python scripts/fetch_intigriti_scope.py list --search "uz leuven"
#   uzleuven   Open   Bug Bounty   UZ Leuven  (id=2cf03670-6a2d-4ac7-8b1e-2e0d84338204)

.venv/bin/python scripts/fetch_intigriti_scope.py uzleuven -o scope_files/uzleuven.json
```

Expect: `in-scope rules : 28`, `out-of-scope : 20`, `mobile (skip) : 0`,
`RoE present : yes`. **Verify against the program page — the page lists 22
in-scope / 20 out-of-scope ASSETS; the file has 28 in-scope RULES because
the 7-IP reverse-proxy entry is expanded to 7 `/32` rules** (22 − 1 + 7).
If anything else disagrees, stop (the page changed; re-fetch or re-read).

Scope shapes this program throws at the pipeline (all handled, all covered
by `tests/test_uzleuven_scope.py`):

- `193.58.149.121,…,193.58.149.111` — comma-listed `IpRange` → 7 CIDR rules
- `*.contactallerg(y|ie).uzleuven.be` — regex-alternation wildcard →
  rewritten to a real regex rule (fnmatch can't express `(y|ie)`)
- `*dev.uzleuven.be`, `*idp*.uzleuven.be`, `*stag*.uzleuven.be` —
  leading-`*` globs → wildcard denials (must still deny even though the
  Tier-3 `*.uzleuven.*` catch-all would match them)
- `random.uzleuven.be/random/` — path-qualified rule (the host is in scope,
  only the `/random/` path)
- Tier values `No Bounty` **and** `Out Of Scope` → both map to
  `in_scope: false`

## Step 2 — Rehearse the graph (dry-run in a scratch workspace: zero packets, zero cost)

```bash
W=$(mktemp -d /tmp/uzl.XXXXXX)         # if $W is empty when you type this, init
                                        # now fails fast with a clear [init] error
.venv/bin/python main.py init --platform intigriti --program uzleuven \
    --scope-file scope_files/uzleuven.json --format bugcrowd_json \
    --workspace "$W/ws"                 # --researcher defaults to onoffgrid
.venv/bin/python main.py run --program uzleuven --dry-run --workspace "$W/ws"
ls "$W/ws/uzleuven/reports/"     # → 1 mock report
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
.venv/bin/python main.py init --platform intigriti --program uzleuven \
    --scope-file scope_files/uzleuven.json --format bugcrowd_json \
    --workspace ./workspace             # --researcher defaults to onoffgrid
```

Expect `in-scope: 28 rule(s) / out-of-scope: 20 rule(s)`. Creates
`workspace/uzleuven/` with: `scope.json` (the rules the egress gate
enforces), `headers.txt` (attribution — the platform default
`X-Intigriti-Researcher: onoffgrid` **+ the program's RoE header
`X-Intigriti-Username: onoffgrid`** + `User-Agent: Mozilla/5.0 (BugBounty;
intigriti/onoffgrid)`; use `--researcher <other>` to override — it is
substituted into the RoE header's `{Username}` placeholder too),
`platform_profile.json`, and `logs/ reports/ evidence/`.

> **This program's RoE header is applied automatically (2026-10-21):** the
> fetch script carries the program's structured RoE testing-requirements
> (`requestHeader: "X-Intigriti-Username: {Username}"`, `userAgent: null`)
> into the scope file under `_testing_requirements`, and `init` merges it
> into the profile + `headers.txt` (printing `[init] RoE header : …`). No
> manual `headers.txt` edit is needed for ANY program — a program whose RoE
> mandates a User-Agent override gets that too (`userAgent` non-null).
> Verify it with `cat workspace/uzleuven/headers.txt` and make sure your
> components send the `headers.txt` set (each component has its own header
> config). Sending both the platform default and the requested one is
> harmless.

## Step 4 — Live run (terminal 1)

```bash
.venv/bin/python main.py run --program uzleuven --workspace ./workspace
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
> **For this program**: the RoE's no-automated-scanner clause (⚠ at the top)
> may make "the component" you run be *you*, with the browser/curl pointed
> at the in-scope assets below. The gate + war room work identically.

Then point your recon/exploit components (or your manual requests) at the
in-scope assets (28 rules; the wildcards `*.kwsdose.be`,
`*.playuzleuven.be` and the Tier-3 `*.uzleuven.*` catch-all cover most of
`*.uzleuven.be`). Examples:

```bash
<your-component> --target https://www.uzleuven.be/
<your-component> --target https://extranet.uzleuven.be/
<your-component> --target https://sts.uzleuven.be/
```

Every request is scope-gated: in-scope → forwarded; anything else →
**blocked and logged with a reason** to
`workspace/uzleuven/logs/egress_proxy.jsonl` (that log is your proof of
discipline if a report is ever disputed). For the 7 reverse-proxy IPs: the
gate allows `https://193.58.149.121/` etc., but the program says **the Host
header determines the bounty tier** (missing Host → default Tier 2) — craft
those requests by hand with an explicit `Host: <in-scope host>`.

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

## UZ Leuven-specific notes (the scope map)

**Tier 1 (11 hosts — the crown jewels; IDOR/BAC/authz are the high-value
classes on the intranet-facing ones):**
`autodiscover.uzleuven.be`, `ecrf.uzleuven.be`, `extranet-asa.uzleuven.be`,
`extranet.uzleuven.be`, `liquidfiles.uzleuven.be`, `mx1.uzleuven.be`,
`mx2.uzleuven.be`, `pcrstudioruzb.uzleuven.be`, `prddsplunkhf.uzleuven.be`,
`sts.uzleuven.be`, `www.uzleuven.be`

**Tier 2 (7):** the 7 reverse-proxy IPs (Host-header rule above),
`wp5-truststroke.uzleuven.be` (its `/api/` should only answer BE/NL IPs —
test the geo-fence from outside), `cardsonline.azdiest.be` (should 403 via
IP whitelisting — test the whitelist), `liquidfilestest.uzleuven.be`,
`random.uzleuven.be` (**only the `/random/` path**), `teststs.uzleuven.be`,
`w1.uzleuven.be` (host in scope; `/random` explicitly **not**).

**Tier 3 (4):** `cardsonlinetst.azdiest.be`, `*.kwsdose.be`,
`*.playuzleuven.be`, and `*.uzleuven.*` — the catch-all: **anything else
under `uzleuven.be` that isn't listed is in scope at Tier 3** (so the
out-of-scope list below is the only thing keeping excluded subdomains out —
the gate enforces it; re-verify it after every scope fetch).

**Out of scope (20) — never send packets at these:**

- "Out Of Scope" tier (8): `boekentoy.uzleuven.be`,
  `uz-laboboeken.web.app`, `laboboeken.uzleuven.be`,
  `boekentoy.firebaseio.com`, `uz-laboboeken.firebaseio.com`,
  `jobs.uzleuven.be`, `uzleuven.atlassian.net`, `vacatures.uzleuven.be`
  (note: the Jira/Atlassian is **out** of scope here — the opposite of
  DataCamp, where `jira.datacamp.com` is in scope)
- "No Bounty" tier (12): `*.contactallerg(y|ie).uzleuven.be`,
  `*.mir.uzleuven.be`, `*dev.uzleuven.be`, `*idp*.uzleuven.be`,
  `*stag*.uzleuven.be`, `files.uzleuven.be`, `kumulus.uzleuven.be`,
  `mijnacc.uzleuven.be`, `mirc.uzleuven.be`, `prddnighting01.uzleuven.be`,
  `w1.uzleuven.be/random`, `ziekenhuisschool.be`

- No mobile apps (0) — nothing to test by hand.
- Re-check the program page before each hunt — the API's domains block is
  versioned (fetched version on 2026-10-19:
  `8c42af1f-ebc7-466c-a470-4119acdc3385`); if the page changes, re-fetch
  (the script re-reads the live scope) or add rules to
  `workspace/uzleuven/scope.json` (the gate blocks + logs them).
- RoE: detailed but to-the-point repro steps, clear attack scenario,
  "quality over quantity", no public PoC/discussion without consent, safe
  harbour applies, **no automatic-scanner findings** (see ⚠ at the top),
  requested header `X-Intigriti-Username: {Username}`. The harness does not
  enforce RoE — you do.

## Debug log — what this program broke, and what was fixed (2026-10-19)

Bringing this program in exposed real defects the DataCamp example never
hit. All are fixed in-repo and pinned by `tests/test_uzleuven_scope.py`
(11 assertions, run against the live API or a frozen fixture):

| Defect (pre-fix behavior) | Fix |
|---|---|
| `fetch_intigriti_scope.py cmd_fetch` crashed with `NameError: name 'mobile' is not defined` (stale local from a refactor) after printing half the summary | Count taken from the payload's `_mobile_apps_manual_only` block |
| Tier **`Out Of Scope`** (used by 8 UZ Leuven assets) was mapped **in-scope** — only `No Bounty` was treated as exclusion | Both tier values now map to `in_scope: false` |
| `IpRange` type not recognized (`"iprange"` ∉ the tuple) → the comma-list of 7 IPs became **one inert EXACT rule** the gate could never match | Any type containing `ip` → `cidr`; comma-lists expand to one `/32` rule per IP; the gate accepts bare IPs as `/32` too |
| `*dev.`, `*idp*`, `*stag*` denials imported as EXACT (only `*.`-prefixed names were recognized as wildcards) → **inert**, and the Tier-3 `*.uzleuven.*` catch-all let No-Bounty dev/stag/idp hosts through | Importer heuristic: leading `*` (any position) → WILDCARD; plus regex/IP shape detection |
| `*.contactallerg(y|ie).uzleuven.be` — fnmatch can't express `(y|ie)` → inert denial, catch-all allowed it again | Fetch script rewrites regex-syntax wildcards to a real regex pattern (`.*\.contactallerg(y|ie)\.uzleuven\.be$`); the importer detects regex shape |
| Path-qualified rules (`random.uzleuven.be/random/`, `w1.uzleuven.be/random`) never matched — EXACT compared hostname only | EXACT now matches `host/path` as a path prefix; `derive_targets` contributes the host for tooling |
| A malformed regex rule could **crash the egress gate** (`re.error` unhandled) | REGEX branch catches `re.error` → no-match + one warning line (never fail-open) |
| `hunt`'s `derive_targets` would have handed `193.58.149.121/32` to `cbb` as a "target host" | CIDR/IP rules excluded from per-target hosts and the stdin URL list (gate-enforced, not launchable) |

## Debug log 2 — live hunt on this program (2026-10-21)

A live hunt against this program exposed three more defects — all fixed
in-repo generically (no program-specific code) and pinned by the test
suite (294 passed):

| Defect (observed on the live hunt) | Fix |
|---|---|
| OOB never registered: Interactsh `POST /register` answered **400 "correlation-id provided already exists"**, so blind classes (SSRF/RCE/XXE) could not confirm | The engine sent one fixed UA (`ult-harness/3.0`); the public Interactsh keys sessions by UA, so a stale same-day session under that UA rejected every new register. Per-instance UA (`ult-harness/3.0/<12-hex>`) + exactly one retry with a rotated UA on that specific 400 (fail-open preserved) — `tests/test_s2_header_oob.py` |
| The program's RoE attribution header (`X-Intigriti-Username: {Username}`) was **missing from `headers.txt`** — every program that mandates one needed a manual edit per hunt | The fetch script now embeds the structured RoE testing-requirements under `_testing_requirements` in the scope file; `init` parses `requestHeader` ("Name: {Username}" form) and substitutes `--researcher` for `{Username}`, merges the result (and any non-null `userAgent` override) into `platform_profile.json` + `headers.txt`, and prints it. No manual edit, any program — `tests/test_s3_main.py`, `tests/test_uzleuven_scope.py` |
| "No progress" in the war room: the live hunt booted as plain `main.py run` (control plane only, by design — S0) with no tools, so `tasks_total: 0` and the egress log stayed empty; and `hunt` itself still demanded `--platform` + `--program` and launched no tools by default | Bare `main.py hunt <handle>` is now the whole story: platform defaults to `intigriti` (the only auto-fetchable platform), tools default to the enabled registry tools (`jsleak,cbb`; `--tools none` opts out), stale generated scope caches re-fetch automatically (v2 generator marker), and the structured RoE facts print at boot as an advisory (`[hunt] RoE : …`, ⚠ when `automatedTooling` ≤ 1 while tools launch) — `tests/test_s8_hunt_launcher.py` |

## If something goes wrong (the ones that matter for this run)

| Symptom | Fix |
|---|---|
| Fetch script 403 | ToE changed (re-accept in the Intigriti UI) **or** rate limit (600 GETs/5 min → wait ~5 min). Persistent 403/404 → copy the scope by hand into `scope_files/uzleuven.json` (Bugcrowd shape) and re-init. |
| `init` count ≠ program page | Scope drift — re-fetch, don't init. (Expected: 28/20 rules for 22/20 assets.) |
| Dry-run budget > $0 | Stop — regression. Fix before live. (`hunt` refuses to go live on its own.) |
| `mitmdump not found` warning at boot | Egress unguarded — Ctrl-C, `pip install mitmproxy` in the venv, re-run. |
| Blind finding stuck in VALIDATING | Check the Interactsh console for the callback; `INTERACTSH_MODE=off` means they *never* confirm (a deliberate choice). |
| `[scope-gate] ✗ invalid regex rule …` at boot/traffic | A scope pattern is not a valid regex (e.g. a raw `*dev.…` hand-typed as `match_type: regex`). It is treated as no-match (never fail-open) — fix the pattern in `workspace/uzleuven/scope.json`. |
| `hunt` stops at `[hunt] ✗` (preflight) | One-line reason is printed: mitmdump missing (install), `:8001` already serving (a previous hunt is still up — tear it down per `main.py stop`, or `resume` it), no LLM backend configured (check `.env`). |
| `resume` says "no saved state" | The hunt never reached boot (state is written at boot and on every stop). Just re-run `hunt` — there is nothing to resume yet. |
| `resume` says "a control plane is already up on :8001" | Your logout killed `hunt` but the child survived. It prints the exact teardown (`kill <pid>` / `pgrep -f 'main.py run --program uzleuven'`); do that, then re-run the same `resume`. |
| `[hunt] note : cbb: skipped — …` | That one tool failed its own pre-check (e.g. `agent.py --help` doesn't exit 0 — missing deps) — the hunt continues without it; fix the tool separately if you want it in. |
| `[hunt] note : wildcards … NOT expanded` | Expected (no subdomain enumeration in-repo). Pass `--targets sub.uzleuven.be,…` for the subdomains you want covered. |
| `oob: register HTTP 400 (… already exists …)` at boot | A stale Interactsh session under the engine's old shared User-Agent is still alive server-side (the public service keys sessions by UA). Fixed 2026-10-21: the engine now uses a unique per-instance UA and rotates + retries once on exactly this error, so a fresh `hunt` self-heals. Only an OLD running hunt can still show the one-line warning — restart it. |
| War room idle: `active_specialists: 0`, `tasks_total: 0`, egress log empty | Expected — `main.py run` alone is control plane only (by design, S0: the harness never scans). You booted without tools. Restart via `hunt <program>` (defaults launch the enabled tools), or relaunch a component through the Step 5 env block. |

Everything else is in `docs/hunt_cheatsheet.md` §4 (full symptom table).
