# CREDITS — third-party components

This repository contains only the harness **control-plane** (Python packages,
specs, guides, scripts). The design targets a polyglot workspace of
third-party agent components that integrate with it (see
`bug_bounty_harness_design_v2_1.md`). Those components are **not vendored
here** — fetch them into the repo root with:

```sh
./scripts/fetch_components.sh
```

Integration specs written for each component live in [`specs/`](specs/).

| Component | Upstream | Role in harness |
|---|---|---|
| Agent-Reach | <https://github.com/Panniantong/agent-reach> | OSINT health daemon |
| Awesome-Redteam | <https://github.com/Threekiii/Awesome-Redteam> | Static playbooks & payload cheatsheets |
| CL4R1T4S | <https://github.com/elder-plinius/CL4R1T4S> | System prompts & safety rules corpus |
| T3MP3ST | <https://github.com/elder-plinius/T3MP3ST> | War-room UI & code auditor |
| adhd | <https://github.com/UditAkhourii/adhd> | Divergent ideation engine (tree-of-thought) |
| claude-bug-bounty | <https://github.com/shuvonsec/claude-bug-bounty> | ReAct engine & CLI runner |
| jsleak | <https://github.com/channyein1337/jsleak> | JS secret scanner |
| mempalace | <https://github.com/MemPalace/mempalace> | Memory engine (ChromaDB/SQLite backends) |

All rights to these components belong to their respective authors; each ships
under its own license. Fresh clones are stock upstream — the design spec marks
several as `TWEAK`/`MODIFIED`; local modifications must be re-applied after
fetching.
