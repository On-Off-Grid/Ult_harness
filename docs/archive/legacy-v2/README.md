# Archive — legacy v2.x doc corpus

**Archived 2026-10-17.** These 10 files are the v2.1.1 / v2.1.2 planning
corpus (Sept 2026), predating the S0 surgical restart. They are the design
rationale and reassessment record behind the current v3.0 build — kept for
provenance, **not** to be treated as instructions.

> **Standing rule:** a doc in this folder carries no status of its own. If it
> disagrees with `OPERATIONS.md` or `specs/assembly_plan_v3.md`, it is
> historical — the v3.0 docs win.

## Supersession chain

```
v2.1.1 (2026-09-06)          v2.1.2 (2026-09-06)         v3.0 (2026-10-15+)
design v2.1 + infra +         gap-bridging spec +         assembly_plan_v3.md
implementation guide +        Qwen-27B addendum +         (the living plan)
workflow overview +           progress report             + OPERATIONS.md
roadmap/mind maps             (narrative of what was      + docs/ (audit,
                              built under v2.x)           provisioning, cheatsheet)
        │                            │                            │
        └────────────────────────────┴──────── archived here ──────┘
```

The mojibake-corrupted *recovered copies* of the v2.1.1 plan/guide were
already quarantined earlier and live in `specs/archive/` (kept as the record
of the corruption incident). This folder holds the **clean-encoding**
originals.

## What replaced each file

| Archived file | Replaced by |
|---|---|
| `bug_bounty_harness_design_v2_1.md` | `specs/assembly_plan_v3.md` (architecture) + `OPERATIONS.md` (operations). Note: v2.1 described T3MP3ST as the `:3333` war room — replaced by the same-origin S7 war room on `:8001` (T3MP3ST is a design reference only, never vendored). |
| `Bug Bounty Harness Orchestration and AI Gateway Specification v2.1.2.md` | `specs/assembly_plan_v3.md` §S5 + `model_routing_guide.md` (current S5 router). |
| `Bug Bounty Harness Orchestration and AI Gateway Specification v2.1.2 (Qwen3.8-27B Integration).md` | `model_routing_guide.md` — the Qwen-27B integration landed as the Groq `qwen/qwen3.8-27b` FREE-tier entry + the deferred `LOCAL_HEAVY` tier (operator GPU-gated). |
| `harness_gap_bridging_specification_v2_1_2.md` | `specs/assembly_plan_v3.md` S0–S7 (every gap it tracked was either closed or re-scoped in v3). |
| `implementation_guide.md` | `specs/assembly_plan_v3.md` phase tables (per the S0.4 decision it was the "historical guide of record" — now archived as such). |
| `infrastructure_specs.md` | `docs/provisioning.md` (accounts, keys, hardware, S0.7 AMD check). Port table here lists dropped components (T3MP3ST `:3333`, BugTraceAI `:8002` — removed from scope in v3). |
| `progress_report.md` | `specs/assembly_plan_v3.md` status banners + `OPERATIONS.md` §4–5. S1.4 already mined its Phase 4.6–4.12 content into `patches/local-tweaks.md` §7. |
| `workflow_overview.md` | `OPERATIONS.md` §1 (what exists, how it connects) + the war-room section §3.4. |
| `harness_roadmap_mindmap.mmd` | `specs/assembly_plan_v3.md` (the phase plan *is* the roadmap). |
| `product_development_mind_map.jpg` | (visual artifact only — no successor needed). |

## Internal links

The archived files cross-link to each other with relative paths, so those
links survive the move intact. Outbound links from living docs into this
folder use the full `docs/archive/legacy-v2/` path.
