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

`progress_report.md` §4 marks 4.6 (adhd engine FP query), 4.7 (cbb agent router),
4.8 (cbb engine proxy), 4.9 (cbb brain CL4R1T4S), 4.10 (cbb memory redirect),
4.11 (cbb scope_checker deprecation), 4.12 (jsleak proxy/-json) all as **❌ TODO**
in the original build. There is nothing to "re-apply" — they are outstanding
integration work, scheduled under S3/S4 of plan v3 (component wiring + orchestrator).
This corrects plan v3 S1.4, which assumed they had been applied.

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
