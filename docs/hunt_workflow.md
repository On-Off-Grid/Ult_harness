# Hunt workflow — how the repos fit together (and who orchestrates whom)

A mental-model file. If you only remember one thing: **this repository is a
control plane, not a scanner.** The eight component repos do the hunting;
the harness does the *gating, booking, triaging, and reporting*. The
**OpAdmiral** (`orchestrator/admiral.py`) is the brain in the middle — but
"orchestrates" needs a precise definition, because in the live hunt it
orchestrates by *reacting*, not by commanding. Read §4 before anyone asks
"why doesn't the admiral just tell the scanner what to scan?"

**Companion docs:** `docs/hunt_cheatsheet.md` (what to type on hunt day),
`docs/examples/datacamp_intigriti.md` (one verified program, end to end),
`patches/local-tweaks.md` §7 (the exact component-side wiring contract),
`CREDITS.md` (provenance + pin commits of the 8 repos).

## 1. The three kinds of git repo

There are three distinct layers, and confusing them is the #1 way to
misunderstand the system:

| Layer | What it is | Git status | Who runs it |
|---|---|---|---|
| **Harness control plane** | The Python packages in *this* repo: `orchestrator/`, `core/`, `compliance/`, `budget/`, `triage/`, `reporting/`, `sessions/`, `ui/` + `main.py` | **Tracked.** The only code in the repo's own history. | `main.py hunt` / `main.py run` |
| **Component repos** | 8 *separate* upstream (or fork) repos cloned into the repo root as sibling dirs: `jsleak/`, `claude-bug-bounty/`, `adhd/`, `Agent-Reach/`, `Awesome-Redteam/`, `CL4R1T4S/`, `T3MP3ST/`, `mempalace/` | **Gitignored.** Fetched by `scripts/fetch_components.sh`, pinned in `CREDITS.md`. *Not vendored, not imported into the control plane's package graph.* | Either the `hunt` launcher (registry tools) or the operator by hand |
| **Support services** | Ollama (`:11434`), Interactsh (cloud OOB), the mempalace palace (`~/.mempalace`) | Not repos at all — local services / runtime state | Stand up before the hunt (cheatsheet §1) |

Two consequences of that split:

1. **A fresh clone of this repo has no components.** The control plane is
   complete and testable alone (260-test suite, fully offline); the hunt
   capability is bolted on by fetching the 8 repos and re-applying
   `patches/local-tweaks.md`.
2. **No component code lives in this repo's history.** If you find yourself
   editing `claude-bug-bounty/agent.py`, you are editing a gitignored third
   party checkout — the durable record of that change belongs in
   `patches/local-tweaks.md`, not in a commit here.

### The 8 components, by role

| Repo | Language | Role | Hunt-time role | `hunt --tools`? |
|---|---|---|---|---|
| `jsleak/` | Go | JS secrets & links scanner | **Scanner** — reads the in-scope URL list on stdin, one process covers the whole scope | ✅ enabled |
| `claude-bug-bounty/` | Python | ReAct recon agent (the On-Off-Grid fork) | **Agent** — one long-running LLM agent per target host | ✅ enabled |
| `adhd/` | Node/TS | Divergent ideation (tree-of-thought) | **Aux** — advisory brainstorm, no target flag | ⛔ disabled (needs a per-hunt prompt; not safe to auto-run) |
| `Agent-Reach/` | Python | OSINT daemon | **Aux** — not a target scanner in v1 | ⛔ disabled (not pip-installed) |
| `Awesome-Redteam/` | — (markdown) | Playbooks & payload cheatsheets | **Corpus** — reference material, ingested; never a process | n/a |
| `CL4R1T4S/` | — (markdown) | System-prompt / technique corpus | **Corpus** — ingested into mempalace, read back by cbb's brain | n/a |
| `T3MP3ST/` | TS | War-room UI design reference + auditor | **Reference only** — the war-room UI is the harness's own `ui/war_room/`; T3MP3ST was never vendored in | n/a |
| `mempalace/` | Python | Memory engine (ChromaDB) | **Shared memory hub** — the one repo components genuinely share (see §6) | n/a (a service, not a tool) |

The registry that codifies the last two columns is `tools/registry.py` —
pure data, one `ToolSpec` per launchable tool, `enabled: False` until a
tool's CLI has been verified against its pin. A tool whose CLI can't be
safely confirmed *stays* disabled with a `note` saying why (honesty rule:
no fake launches).

## 2. The process & port map

What is actually running during a live hunt, and who owns what:

```
  you (operator)
     │ types one command
     ▼
 main.py hunt                       ← the SUPERVISOR (orchestrator/hunt_launcher.py)
     │  preflight → scope → init → dry-run($0 gate) → boot → launch tools
     │  Ctrl-C: teardown in order (tools first, then control plane)
     │  writes workspace/<p>/hunt_state.json at boot + on every stop
     │
     ├── spawns (its only child):  main.py run        ← the CONTROL PLANE
     │        │
     │        ├── OpAdmiral on :8001 (uvicorn)        ← THE BRAIN
     │        │     • war-room UI (GET /, same-origin)
     │        │     • REST + /ws  (findings in, budget, routing, halt)
     │        │     • triage state machine, kill switch, report writer
     │        │     • OOB poll loop (Interactsh, every 15 s)
     │        │
     │        └── spawns: mitmdump -p 8080 -s compliance/egress_proxy.py
     │                    ← the EGRESS GATE (ScopeGate on every outbound request)
     │
     └── spawns (one per selected tool, own process groups, own env):
           jsleak (Go) ──┐
           cbb agent ×N ─┼── HTTP_PROXY/HTTPS_PROXY = http://127.0.0.1:8080
           …             │   NO_PROXY = localhost,127.0.0.1
                         ▼
                    every byte of target-bound traffic crosses :8080
                    (scope-gated + logged to logs/egress_proxy.jsonl)

  background services (not spawned by hunt): Ollama :11434, Interactsh (cloud),
  the mempalace palace under ~/.mempalace
```

Port ownership, so nothing double-binds:

| Port | Owner | Purpose |
|---|---|---|
| `:8001` | the `run` child (uvicorn) | OpAdmiral REST + WebSocket + war-room UI — the sink for findings, token accounting, and LLM routing |
| `:8080` | mitmdump child | egress gate — the *only* path to target hosts |
| `:11434` | Ollama (pre-existing) | local LLM tier (legal on its own, per S4.3) |

`NO_PROXY=localhost,127.0.0.1` is what makes this work: a component that
POSTs to `:8001` (its harness calls) or calls Ollama does **not** loop back
through the egress gate — only *target-bound* traffic is gated and logged.
The launcher injects all of this via `tools/registry.py:build_env()`.

## 3. The hunt workflow, end to end

The conceptual shape of a hunt, mapped to the code that does each step:

1. **Preflight** (`hunt_launcher.py:preflight`) — cheap hard-fails before any
   state changes: mitmdump present, `:8001` not already serving (a previous
   hunt still up), workspace writable, scope resolvable, at least one LLM
   backend (GROQ/OPENROUTER env, Ollama `:11434`, or `LOCAL_HEAVY_URL`).
2. **Scope intake** — Intigriti programs are auto-fetched from the Researcher
   API (`scripts/fetch_intigriti_scope.py:fetch_program()` → `build_scope_payload()`);
   other platforms need a `--scope-file`. **The control plane never calls
   platform APIs in the live path** — the fetch happens in the launcher,
   up front, into a versioned `scope_files/<p>.json`.
3. **Init** (`main.py cmd_init`, reused in-process) — writes
   `workspace/<p>/scope.json` + `platform_profile.json` + attribution
   `headers.txt` (RoE-driven).
4. **Dry-run** — the full graph walk with `HARNESS_DRY_RUN=true`: the egress
   gate logs WOULD ALLOW / WOULD DROP instead of sending packets, and the
   model router resolves models without paying. **It must end at $0; a
   non-$0 dry-run aborts the command.** This is the regression gate that has
   held since S4.
5. **Boot** (`main.py _run_live`) — router health check + provider
   discovery, Interactsh session (fail-open), auth bootstrap from the
   profile, then uvicorn on `:8001` + the OOB poll loop + the mitmdump child.
6. **Components run** — the launcher spawns each selected tool with the
   harness env (§4). They probe in-scope targets; every outbound request
   crosses the `:8080` gate (deny = synthetic 403, logged) and each allowed
   request is appended to `logs/egress_proxy.jsonl`.
7. **Findings come in** — through `POST /api/triage/callback` (a live, fully
   tested endpoint) or via the Mode-A specialist dispatch (the dry-run walk,
   §5). The admiral ingests each: scope re-check → noise filter →
   (dual-session validation for IDOR/BAC) → state machine
   `IDENTIFIED → VALIDATING`. ⚠ Who actually POSTs a finding *today* is
   spelled out in §4 (the open finding-bridge) — the harness side is done,
   but the pinned external components don't yet emit findings by themselves.
8. **Operator adjudication** — the war room (`:8001/`) lists findings;
   confirm (stage 7 ✅) or reject with a mandatory FP reason (❌), which is
   stored on the finding's record. Filing FP reasons to mempalace is the
   job of `write_back_memory` — dry-run-walk only today, per the §6 note.
9. **Reports** — `generate_report()` writes **CONFIRMED/CHAINED only** to
   `workspace/<p>/reports/`.
10. **Stop / pause / resume** — Ctrl-C tears down in order (tools first via
    process-group SIGTERM→SIGKILL, then the control plane), writes
    `hunt_state.json`. What survives and what doesn't is stated *in the
    file itself* (`durable` snapshot vs `volatilized_on_stop`) — see the
    cheatsheet §3.0 for the honest split.

## 4. The component → harness contract (the 3 channels)

A component process has exactly three ways to talk to the harness. All are
**env-gated and fail-open**: with the env vars unset, the component behaves
byte-for-byte as standalone (the S4.0 contract, verified per component in
`patches/local-tweaks.md` §7); with a dead harness, every call is swallowed
and the hunt continues.

| Channel | Wire | What flows | Harness side |
|---|---|---|---|
| **Egress** (recon out) | `HTTP(S)_PROXY → :8080` | all target-bound requests | `compliance/egress_proxy.py` — ScopeGate decision per request, 403 + log on deny, strips the `X-Harness-Traffic` marker before it reaches targets |
| **Findings in** (the designed bridge) | `POST :8001/api/triage/callback` | `{title, description, vuln_category, endpoint, evidence, confidence}` | `admiral.ingest_finding()` — §3 step 7 · **endpoint live + tested; see the open-bridge note below for who emits today** |
| **Bookkeeping** | `POST :8001/api/tokens/record` · `POST :8001/api/v1/llm/route` · mempalace search/record | token usage · triage/classification LLM calls · memory reads/writes | `admiral.record_tokens()` → TokenTracker (single cost ledger) · `admiral.route_llm_request()` → ModelRouter (4-tier, budget-aware) · the mempalace shim |

What each component actually uses today (the component-side half of the
contract — full detail in `patches/local-tweaks.md` §7):

- **cbb** (`claude-bug-bounty/`): its own `harness_client.py` bridge.
  `race_analysis()` triage calls go through `/api/v1/llm/route` first (the
  harness's model wins, already budget-accounted; tool-calling stays local —
  it needs the tool schema); its engine sets the proxy vars from the harness
  env; its brain prepends a `[CL4R1T4S TECHNIQUES — learned]` block fetched
  from mempalace; its audit log / pattern DB mirror to mempalace.
- **adhd**: on run end, one FP query against mempalace (advisory warning
  only — the run result is *never* mutated) + one `/api/tokens/record`
  (≈4 chars/token estimate, honestly labeled as an approximation).
- **jsleak**: proxy support only (`http.ProxyFromEnvironment`) + `-json`
  line output. It does **not** call the API at all — and note that when the
  launcher runs it, the tool's stdout is sent to `DEVNULL`
  (`hunt_launcher.py`), so even that `-json` stream is not auto-captured into
  triage; it exists for a collector or an operator to read.
- **mempalace**: no outgoing wiring; it is the *destination*.

So the env block the launcher injects per tool is small and total:
`HARNESS_API_URL`, `HARNESS_EGRESS_PROXY`, `HTTP_PROXY`, `HTTPS_PROXY`,
`NO_PROXY` (registry `build_env()`).

**The open finding-bridge — wired today vs. the designed contract.** Read
this before assuming a finding from a component lands in triage on its own.
The **harness side** of the findings path is complete and tested:
`POST /api/triage/callback` is live on `:8001`, and the whole
`ingest_finding()` pipeline (scope → noise → dual-session → state machine →
report) is proven end to end by the dry-run walk (§5, Mode A) and the test
suite. What the S4.0 component tweaks (`patches/local-tweaks.md` §7) actually
wired on the **component** side is: egress through the proxy, LLM calls
routed to `/api/v1/llm/route`, token usage mirrored to
`/api/tokens/record`, and mempalace reads/mirrors. They did **not** add a
findings emitter — as of these pins, **no external component POSTs a finding
by itself.** So in a live S8 hunt a finding from jsleak/cbb reaches the
admiral by the operator (or a thin collector script) pushing that
component's output to the endpoint; the OOB receive side runs regardless.
The gap is a one-function-per-component addition (a `post_finding()` in the
existing `harness_client`), not an architecture change — the destination is
already there and already tested.

## 5. How the admiral orchestrates (the part "orchestrator" must not oversell)

`OpAdmiral` has **two modes**, and they are easily conflated:

**Mode A — the S3 specialist graph (in-process).** `admiral.dispatch(task,
specialist)` sends a task to an in-repo specialist
(`agents/specialists/*.py` — sqli, ssrf, idor, …) that returns findings.
This is pure Python with mocked LLM calls; it powers the **dry-run graph
walk** and most of the test suite. In the live hunt these in-repo
specialists are *not* the hunters — the external component repos are.

**Mode B — the S8 live hunt (external components).** The components run as
separate processes chosen by the operator (`hunt --tools`). The admiral
does **not** push scan commands to them. It is a **reactive sink and
gatekeeper**: components do the work; the admiral (1) re-checks scope on
everything that comes in, (2) filters noise, (3) runs the triage state
machine, (4) correlates OOB callbacks, (5) gates the shared budget/LLM
routing that components borrow, and (6) writes the reports. Items (1)–(3)
and (6) act on findings *once they reach the endpoint* — per §4's open-bridge
note, as-pinned the operator is what pushes them there; the live, always-on
parts of Mode B are the egress gate, the budget/LLM gateway, the OOB receive
loop, and the war-room sink. Steering in the live path is **the operator's**
(tool selection, targets, confirm/reject) — which is the S0 decision in
deliberate form: the control plane never scans.

The internal pipeline, per finding (all in `admiral.py`):

```
component / OOB callback
   │
   ▼
scope_gate.is_in_scope(endpoint)  ── fail → dropped_out_of_scope + violation count
   │                                   (N=3 violations → KILL SWITCH: dispatch
   ▼                                    halts for the whole hunt; the :8080
noise_filter                          gate is the network-layer backstop)
   │  non-bountiable → dropped_noise
   ▼
dual-session validation (IDOR/BAC with matrix evidence only)
   ▼
state machine: IDENTIFIED → VALIDATING
   │        ← operator confirm → CONFIRMED      → report written
   │        ← operator reject (FP reason) → FALSE_POSITIVE → mempalace
   ▼
reporting (CONFIRMED/CHAINED only) + write_back_memory()
```
(The `write_back_memory` edge is dry-run-walk only as of today — §6 note.)

Two more admiral responsibilities worth naming:

- **OOB correlation (S8.1), the receive side.** The OOB poll loop
  (`main.py _oob_poll_loop`, every 15 s) calls `admiral.poll_oob()`, which
  matches new Interactsh callbacks against registered payloads. A callback
  **is** the proof for blind SSRF/RCE/XXE — no LLM in that path — so it
  transitions `VALIDATING → CONFIRMED` directly, or *synthesizes* a blind
  finding when local checks produced nothing. Fail-open end to end: dead
  Interactsh = 0 callbacks, hunt unharmed. **The send side is in-repo** —
  `generate_payload(context)` is called by the Mode-A specialists
  (`agents/specialist_base.py:OOBMixin`), not by the external components. So
  in a pure-external live hunt the receive loop runs but, with no payloads
  embedded, it confirms nothing until either a specialist dispatch embeds
  them or the component bridge grows an embed call.
- **The single budget ledger.** Components that borrow the harness's LLM
  (`/api/v1/llm/route`) and those that mirror their usage
  (`/api/tokens/record`) both land in the same `TokenTracker`, so the war
  room's budget view is one number, not N component ledgers. The
  `ModelRouter` picks the tier/provider per task type under that budget.

## 6. How the components interact *with each other* (honest answer)

They **mostly don't** — and that's by design. There is no component-to-
component messaging, no shared bus between them. What they share:

1. **The egress gate (`:8080`)** — a shared *choke point*, not a shared
   state. jsleak's and cbb's requests both cross it and both get logged to
   the same `egress_proxy.jsonl`, but the processes never see each other.
2. **The harness API (`:8001`)** — a shared *sink* (tokens + LLM routing
   fully plumbed by the spawned builds; findings-in is the contract, §4
   note). Again concurrent, not interactive.
3. **mempalace — the one genuine shared store.** This is where "components
   interacting" is literally true, *mediated by the memory palace*:

```
   CL4R1T4S/  ──ingest──▶  mempalace  ◀── audit/pattern mirrors ──  cbb
   (corpus)                (ChromaDB)  ◀── FP query before finish ──  adhd
                              ▲
                              └── CONFIRMED/CHAINED/FP write-back ──  the admiral
                                   (write_back_memory — see the note below)
```

   So the real cross-repo data flow is **corpus → mempalace → cbb's system
   prompt** (cbb's brain prepends learned CL4R1T4S techniques to every
   provider call), **findings → mempalace → the next run's specialists**
   (FP reasons taught once apply everywhere), and **adhd → mempalace →
   advisory warning** (a run is warned when its ideas resemble filed
   false-positives — without mutating its output).

   **Which of these fire as-pinned, stated precisely** (the same
   "wired vs. designed" split as the finding-bridge in §4):

   - **cbb → mempalace** (audit/pattern mirror) and **adhd → mempalace**
     (FP query): **wired and live** under-harness — env-gated, fail-open,
     verified per `patches/local-tweaks.md` §7. They talk to the mempalace
     service directly (best-effort against the `:8000` shim gap), *not*
     through the admiral.
   - **CL4R1T4S → mempalace**: real only if the corpus was actually
     ingested into the palace first — cbb's read-back then fires
     under-harness.
   - **admiral → mempalace** (`write_back_memory`, CONFIRMED/CHAINED/FP):
     **dry-run walk only today** — it runs in the graph walk
     (`main.py` dry-run, "would file") and the test suite, but is **not yet
     called from the live `_run_live` loop**. So live-hunt learning
     currently comes from the *component-side* mirrors above, not from the
     admiral filing its adjudications. Wiring the live call in is a
     one-line addition (the method is already built and tested); it is not
     done yet.
4. **The egress log** — `logs/egress_proxy.jsonl` is the one artifact where
   all components' traffic is intermingled (with `X-Correlation-ID` per
   request), which is what makes a *post-hunt* forensic view possible.

One documented gap, stated plainly: the mempalace `:8000` REST surface the
old spec referenced (`/search`, `/record`) was **never confirmed to exist**
— mempalace is a ChromaDB package + MCP/daemon. All component→mempalace
calls are best-effort: absent routes fail open to the components' local
JSONL memory. A thin REST shim turns them on with zero component changes
(`patches/local-tweaks.md` §7, "open shim gap").

## 7. Teardown & pause (where the orchestration unwinds)

The supervisor (`hunt_launcher.py`) is the **sole controller** of the whole
tree — that's what makes logout safe:

- every child (the `run` process *and* each tool) is spawned in its own
  session (`start_new_session=True`), so the launcher can reap a whole tool
  with one `killpg` (SIGTERM, wait 3 s, SIGKILL);
- SIGINT/SIGTERM on `hunt` set a flag (no default handler) → teardown in
  order: **tools first, then the control plane** (the gate must live until
  the last probe is gone, and the brain must live until the last tool
  finishes its final callback);
- `hunt_state.json` is written **early** (status=`running` + the control-
  plane pid right after boot) *and* on every exit (`running|paused|ended|
  failed`), so even a hard logout (SIGKILL to `hunt`) leaves a resumable
  marker — the tools die with their process groups, but the state does not
  die with the supervisor;
- `resume` rebuilds the volatile half and **refuses to double-boot** if a
  control plane somehow survived the logout and still serves `:8001`
  (prints the exact `kill`/`pgrep` teardown instead).

What a stop actually loses is encoded *in the state file*, not implied:
`durable` = `reports/`, `evidence/`, `egress_proxy.jsonl`, scope/profile
(on disk, they survive); `volatilized_on_stop` = in-memory task/finding
maps, triage state, the budget ledger, the Interactsh session (they lived
only in the `run` process). Mid-gap OOB callbacks can never correlate — the
file says so, and the cheatsheet §4 has the symptom row for it.

## 8. Quick orientation

| Question | Answer | Where |
|---|---|---|
| Who scans? | The component repos. Never the control plane (S0). | `tools/registry.py` header |
| Who gates? | mitmdump + `EgressProxy` on `:8080` (network layer) **and** `ScopeGate` at dispatch/ingest (admiral layer) — defense in depth | `compliance/egress_proxy.py`, `admiral._enforce_scope` |
| Who books? | One `TokenTracker` + `ModelRouter` behind the REST bookkeeping endpoints | `budget/` |
| Who triages? | The admiral: noise filter → dual-session → state machine → OOB correlate | `admiral.ingest_finding`, `poll_oob` |
| How do findings get in? | `POST /api/triage/callback` (live, tested) + the OOB receive side. As-pinned, the spawned builds plumb egress + LLM + tokens + memory; the component-side finding emit is the open bridge (§4) | `admiral.ingest_finding`, `create_app` |
| Who writes reports? | `ReportWriter`, CONFIRMED/CHAINED only, only after operator or OOB confirmation | `reporting/writers.py` |
| Who remembers? | mempalace (the shared hub, §6) — live as-pinned via the component-side mirrors; the admiral's `write_back_memory` is dry-run-walk only today | `admiral.write_back_memory`, local-tweaks §7 |
| Who launches/tears down? | The `hunt` supervisor — sole controller of the process tree | `orchestrator/hunt_launcher.py` |
| Who drives? | **You.** Tool choice, targets, confirm/reject — the steering is operator-side by design | cheatsheet §0 |
