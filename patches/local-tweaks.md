# Local component tweaks — complete record (S1.5)

**Date:** 2026-10-15. Every modification applied to the 8 gitignored third-party
components during the surgical restart. After a fresh `./scripts/fetch_components.sh`,
re-apply this list in order.

## 1. `claude-bug-bounty/` — SOURCE OVERRIDE (do first)

- **Tweak:** clone `https://github.com/On-Off-Grid/claude-bug-bounty` (full history,
  main @ `b2e9eb7a8e`) INSTEAD of `shuvonsec/claude-bug-bounty`.
- **Why:** the fork is 140 unique commits with **no merge base** to upstream — it is
  an independently evolved component (WAF bypass pipeline, GraphQL audit skill,
  6 LLM providers, LFI→RCE class, MCP/RAG attack class, deserialization class,
  perf fixes). Upstream would discard all of it.
- **How (after fetch_components.sh):**
  ```bash
  rm -rf claude-bug-bounty
  git clone https://github.com/On-Off-Grid/claude-bug-bounty claude-bug-bounty
  ```
- Provenance: `patches/forks/claude-bug-bounty.commits.log`, `patches/forks/README.md`.
- Root layout (`agent.py`, `brain.py`, `engine.py`, `serve.py`, `memory/`, `tools/`)
  is unchanged from what the v2.1.2 plan assumed, so steps 4.7–4.11 apply as written.

## 2. `adhd/` — rename + security frames (Phase 4.5 re-apply)

- **Tweak A — package rename** (was uncommitted in the stray clone; now safe on GitHub):
  - Source commit: `b2acabe` on branch `local-rename` of `On-Off-Grid/adhd`
    ("chore: rename package connect-dots -> adhd-agent, add adhd-agent dep + node>=18 engines").
  - Re-apply: `git fetch origin local-rename && git checkout --detach origin/local-rename`
    (package.json `name: adhd-agent`, `bin: {adhd: dist/cli.js}`, engines node>=18).
- **Tweak B — 6 security frames** (original applied 2026-08-12, lost with the deleted
  clone; original prompt text recovered verbatim from the 2026-08-12 session
  transcript in `~/.gemini/antigravity-cli/brain/fc58faf8-.../logs/transcript.jsonl`).
  Upstream refactored `frames.ts` into a `packs/` registry after the original edit,
  so instead of re-appending to the flat array the frames live in a **named pack**:
  - **NEW file** `adhd/src/packs/security.ts` — frames `recon_diverge`,
    `payload_mutate`, `chain_explore`, `auth_bypass_brainstorm` (note: the actual id
    in the original was `auth_bypass_brainstorm`, the progress report's shorthand was
    `auth_bypass`), `waf_evasion`, `business_logic_abuse`.
  - **MODIFIED** `adhd/src/frames.ts` (2 lines): import `security`, register in
    `PACKS` → `export const PACKS = { core, security }`.
  - Select at run time: `selectFrames(n, codeMode, ["core", "security"])`.
  - Verified: `npm install && npm run build` clean; `selectFrames(4, true, ["security"])`
    returns the security frames.

## 3. `jsleak/` — Go module shim

- **Tweak:** added `go.mod` + `go.sum` (`module jsleak`, go 1.26, `gopkg.in/yaml.v2`).
  Stock upstream is pre-modules (no `go.mod`) and won't build under Go 1.17+.
- **Why:** without it `go run main.go` / `go install` from a local copy fails.
- **How (after fetch):** `cd jsleak && go mod init jsleak && go mod tidy`.
- Verified: `go build` → binary; `-help` lists `-c -e -k -l -s -t` flags.
- Note for step 4.12: the `-json` flag and `HTTP_PROXY` env support are still TODO.

## 4. `Agent-Reach/`, `T3MP3ST/`, `CL4R1T4S/`, `Awesome-Redteam/` — NO code tweaks

- Stock upstream, verified: `agent_reach` imports (v1.5.0); `T3MP3ST` builds
  (`npm install && npm run build` → `t3mp3st --help` OK, bin `tempest`/`t3mp3st`).
- The only Agent-Reach/T3MP3ST "tweaks" in the old plan were **never applied**
  (see §6). T3MP3ST UI gauge work (old step 7.5) is still future work.

## 5. `mempalace/` — NO code tweaks (correction to the old progress report)

- The "7 new tables (scopes, oob_callbacks, taxonomy_mappings, ...)" were **runtime
  ChromaDB collections/data**, not code. The runtime palace survived the deletion:
  `~/.mempalace/palace/chroma.sqlite3` (184 KB, collection `mempalace_drawers`).
- Fresh clone needs `pip install -e mempalace` (or path-based import) before the
  `scripts/ingest_*.py` dry-runs (S2.9).

## 6. Phase 4B tweaks 4.6–4.12 — NEVER WERE DONE (not lost)

`progress_report.md` §4 (archived: `docs/archive/legacy-v2/`) marks 4.6 (adhd engine FP query), 4.7 (cbb agent router),
4.8 (cbb engine proxy), 4.9 (cbb brain CL4R1T4S), 4.10 (cbb memory redirect),
4.11 (cbb scope_checker deprecation), 4.12 (jsleak proxy/-json) all as **❌ TODO**
in the original build. There is nothing to "re-apply" — they are outstanding
integration work, scheduled under S3/S4 of plan v3 (component wiring + orchestrator).
This corrects plan v3 S1.4, which assumed they had been applied.

## 7. Phase 4B tweaks 4.6–4.12 — APPLIED (S4.0, 2026-10-16)

These were the never-shipped component-side half of the 4.6/4.7 contract
(S3 delivered the harness side: `POST /api/tokens/record` +
`POST /api/v1/llm/route`). Now implemented. **Every tweak is env-gated and
fail-open**: with the relevant env var unset the component behaves *byte-for-byte
as standalone*; with it set, the component talks to the harness; a dead harness
never breaks a hunt.

**Gate vars (set by `main.py` live mode / `.env`):**
- `HARNESS_API_URL`  → OpAdmiral REST (default `http://127.0.0.1:8001`)
- `HARNESS_MEMPALACE_URL` → mempalace REST surface (default `http://127.0.0.1:8000`)
- `HARNESS_EGRESS_PROXY` → egress proxy (default `http://127.0.0.1:8080`)

### 4.6 — `adhd/` (TypeScript, `tsc` clean)
- **NEW logic in `adhd/src/llm.ts`:** module-level `_promptChars`/`_completionChars`
  counters incremented inside `callLLM`; exported `_resetTokenEstimate()` +
  `_takeTokenEstimate()` (≈4 chars/token). The Claude Agent SDK `query()` exposes
  no exact token count, so this is an honest approximation, clearly labeled.
- **`adhd/src/engine.ts`:** `run()` calls `_resetTokenEstimate()` at start and,
  immediately before its final `return`, awaits `_harnessPostHook(...)`:
  1. **FP query** — `POST {HARNESS_MEMPALACE_URL}/search` (`{query, k:5}`); any
     non-empty hit emits an *advisory* `{kind:"warn"}` event. The run result is
     **never mutated** (non-destructive).
  2. **Token callback** — `POST {HARNESS_API_URL}/api/tokens/record`
     (`{agent_id:"adhd", task_id, input_tokens, output_tokens, model}`).
  Both wrapped in try/catch (fail-open, `AbortSignal.timeout(5000)`); `finally`
  resets the counters so a throw can't leak state into the next run.
  Imported `RunEvent` from `./types.js` for the advisory event type.
- Verified: `tsc --noEmit` + `tsc -p tsconfig.json --noEmit` clean; counters
  2000/80 as expected; both POSTs land against a fake harness; dead service
  swallowed.

### 4.7 — `claude-bug-bounty/agent.py` (Python)
- **NEW file `claude-bug-bounty/harness_client.py`** — the shared stdlib-only
  (urllib) bridge. Four fail-open, env-gated, live-env-reading functions:
  `route_llm`, `record_tokens`, `mempalace_search`, `mempalace_record`, plus a
  `_est_tokens` helper. **This file is the single integration surface for
  cbb; keep it.**
- `agent.py`: `import harness_client as _harness_client` under try/except (top,
  after the brain import). `race_analysis()` (plain-text triage/classification
  calls) first tries `route_llm("triage_decision", ...)`; on a non-empty routed
  answer it returns that (already budget-accounted by the harness) and skips the
  local Ollama race. Tool-calling path is **not** routed (needs the tool schema)
  — it stays local. Standalone → `route_llm` returns None → local race runs as before.
- Verified: routed path returns the harness answer; standalone path returns the
  local race winner; `record_tokens` acked against a fake harness.

### 4.8 — `claude-bug-bounty/engine.py`
- At module init (after `from pathlib import Path`), **if** `HARNESS_API_URL` is
  set: `os.environ.setdefault` `HTTP_PROXY`/`HTTPS_PROXY` to
  `HARNESS_EGRESS_PROXY` (default `http://127.0.0.1:8080`) and `NO_PROXY`/
  `no_proxy` to `localhost,127.0.0.1`. Standalone (no `HARNESS_API_URL`) → no-op.
- Verified: under-harness exports the proxies; standalone leaves them unset.

### 4.9 — `claude-bug-bounty/brain.py`
- `import harness_client as _harness_client` (try/except) + `_mempalace_cl4r1tas()`
  which best-effort calls `mempalace_search("cl4r1tas_prompts")` and formats any
  hits as a `[CL4R1T4S TECHNIQUES — learned]` block (returns `""` on any miss).
- `LLMClient.chat()` prepends that block to the system prompt (single choke point
  for every provider). Standalone / dead palace → `""` → unchanged prompt.
- Verified: live fake palace → block prepended; dead palace → `""`.

### 4.10 — `claude-bug-bounty/memory/{audit_log,pattern_db}.py`
- Both import `harness_client` (try/except).
- `audit_log.AuditLog.log()` and `pattern_db.PatternDB.save()`: after the local
  JSONL write succeeds, `mempalace_record("audit"|"pattern", entry)` (fire-and-
  forget, swallowed). **Local storage is never replaced** — mempalace is a
  mirror only.
- Verified: import OK; fail-open (no env → no network).

### 4.11 — `claude-bug-bounty/tools/scope_checker.py`
- Added a **one-shot, stderr** deprecation notice (`_warn_under_harness()`) that
  fires **only when `HARNESS_API_URL` is set**, pointing at the authoritative
  `compliance/scope_gate.ScopeGate` (enforced at the egress proxy). The checker
  itself is untouched and still works standalone (silent).
- Verified: standalone → no warning; under-harness → exactly one warning.

### 4.12 — `jsleak/main.go` (Go, `go build` clean)
- `httpClient.Transport` gains `Proxy: http.ProxyFromEnvironment` so
  `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` are honored (no proxy set → direct,
  unchanged). Verified a dead proxy flips the error to `proxyconnect ...
  connection refused` (proxy actually used); loopback targets are bypassed by
  Go's default proxy logic — real harness targets are external, so this is correct.
- Added `-json` flag → findings emit as JSON lines
  (`{"kind","name","value","source"}`) via `emitFinding()`; **non-json output is
  byte-identical to stock** (verified: same `[+] Found ...` lines). `encoding/json`
  import added. Verified: `go build` → binary; `-help` lists `-json`.

### S4.0 verification summary
| Component | Check | Result |
|---|---|---|
| adhd | `tsc --noEmit` + `tsc -p tsconfig.json --noEmit` | ✅ clean |
| claude-bug-bounty | `python3 -m py_compile` (6 files) + import + live fake-harness | ✅ |
| jsleak | `go build` + `-help` + JSON/proxy smoke test | ✅ |
| all | 149-test harness regression | ✅ still green |

**Standalone guarantee (the S4.0 contract):** every tweak degrades to a no-op
when its env var is unset — confirmed by re-running each component with the env
cleared (bridge returns None/False, counters floor, no proxy, no warning, no
system-prompt change, local race preserved).

**Re-apply after a fresh `./scripts/fetch_components.sh`:** the three component
dirs are gitignored, so a fresh clone reverts 4.6–4.12. Re-do the edits above
(in particular **keep `claude-bug-bounty/harness_client.py`** — it is new and not
in any upstream). Then re-run the §7 verification row.

**Open shim gap (documented, fail-open):** the spec cited a mempalace `:8000`
REST surface (`/search`, `/record`), but the on-disk mempalace is a ChromaDB
package + MCP/daemon with **no confirmed REST API** on :8000. All 4.6/4.9/4.10
mempalace calls are therefore best-effort: absent/differing routes → fail open,
component continues on its local JSONL memory. A thin REST/MCP shim on :8000
turns them on without any further component change.

## Gate S1 result (2026-10-15): PASS

| Component | Present | Entry point check |
|---|---|---|
| Agent-Reach | ✅ | `import agent_reach` OK (v1.5.0) |
| Awesome-Redteam | ✅ | corpus (cheatsheets/tips) present for ingest |
| CL4R1T4S | ✅ | corpus (system prompts) present for ingest |
| T3MP3ST | ✅ | `t3mp3st --help` after `npm i && npm run build` |
| adhd | ✅ | `node dist/cli.js --help` + security pack selectable |
| claude-bug-bounty | ✅ | fork @ b2e9eb7; root .py syntax OK |
| jsleak | ✅ | `go build` + `-help` (after module shim) |
| mempalace | ✅ | `import mempalace` OK; runtime palace intact |

Only modifications on disk = the ones listed above (§1–§3).
