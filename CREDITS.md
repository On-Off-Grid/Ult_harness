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

### Pin commits (what this build was verified against — 2026-10-16)

`fetch_components.sh` clones the components fresh; **re-apply the local tweaks
after every fetch** (`patches/local-tweaks.md` §7 has the exact recipe). The
build above was verified against these HEAD commits:

| Component | Pin | As of | Source actually cloned |
|---|---|---|---|
| adhd | `b5d7e33` | 2026-10-15 | **fork** `On-Off-Grid/adhd` @ `local-rename` |
| claude-bug-bounty | `b2e9eb7` | 2026-06-21 | **fork** `On-Off-Grid/claude-bug-bounty` (the fork IS the component) |
| Agent-Reach | `94f06c1` | 2026-10-08 | stock upstream |
| Awesome-Redteam | `562ce8c` | 2026-06-23 | stock upstream |
| CL4R1T4S | `a4d3da0` | 2026-09-22 | stock upstream |
| T3MP3ST | `29824d5` | 2026-09-07 | stock upstream |
| jsleak | `f625a96` | 2025-09-25 | stock upstream |
| mempalace | `196f91e` | 2026-10-15 | stock upstream |

> `adhd` and `claude-bug-bounty` are pulled from the **On-Off-Grid forks**, not
> the stock upstream listed above (the `claude-bug-bounty` fork has no merge
> base to upstream and carries all the customization — see
> `patches/local-tweaks.md` §1). The upstream column records original
> authorship for licensing; the clone source is what matters for repro.

All rights to these components belong to their respective authors; each ships
under its own license. Fresh clones are stock upstream (or the forks above) —
the design spec marks several as `TWEAK`/`MODIFIED`; local modifications must
be re-applied after fetching.
