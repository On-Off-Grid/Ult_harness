# Fork salvage — provenance of the 8 components' local modifications

Captured during S0 (2026-10-15). Determines, for S1, whether each component is
re-fetched from **stock upstream** or taken from the **On-Off-Grid fork**.

Method: cloned each fork to `/tmp/opencode/salvage/`, added its upstream remote,
fetched, and compared `fork main` vs `upstream main` (ahead / behind / merge-base).

## Results

| Component | Fork main | vs upstream | Unique fork work? | S1 source of truth |
|---|---|---|---|---|
| Agent-Reach | `1494c2ab` | 0 ahead / 72 behind, merge-base = fork | **No** (stale snapshot) | **Stock upstream** |
| claude-bug-bounty | `b2e9eb7a` | 140 ahead / 262 behind, **no merge base** (diverged) | **YES — 140 commits** | **The fork itself** |
| jsleak | `f625a968` | 0 ahead / 0 behind | **No** (identical) | **Stock upstream** |
| adhd | (stray clone `~/Desktop/Desktop/adhd`) | local uncommitted rename | rename commit (S0.3) | fork + re-applied rename + frames tweak |
| Awesome-Redteam, CL4R1T4S, T3MP3ST, mempalace | no fork (404) | — | only spec-driven tweaks | **Stock upstream** + re-apply `specs/*_spec.md` tweaks |

## claude-bug-bounty — the fork is the component (140 unique commits)

No merge base with upstream, so a diff patch is meaningless; the fork's `main`
**is** the customized component. Saved full fork history to
`claude-bug-bounty.commits.log`. Highlights of the unique work:

- `67d33c5` feat(waf-bypass): systematic WAF bypass pipeline (encoder, analyzer, soft-block detection)
- `10e0804` feat: GraphQL audit skill + tool (introspection, batching DoS, IDOR, injection)
- `29b1e3f` feat(brain): 6 new LLM providers — Gemini, Kimi, Mistral, Together, Cerebras, Perplexity
- `261b278` feat(web2-vuln-classes): LFI / file inclusion → RCE class
- `d137155` feat(web2-vuln-classes): MCP & RAG-specific attacks (LLM/AI class)
- `0a739fd` feat(web2-vuln-classes): Insecure Deserialization as class 24
- `2a64de3` fix: OpenCode tool mappings for agents
- `b2e9eb7` perf: speed up nuclei, httpx, subfinder, katana, dalfox, gau, arjun

**S1 action:** clone `On-Off-Grid/claude-bug-bounty` main (not upstream) into the
repo root as the `claude-bug-bounty/` component; do NOT run it through
`fetch_components.sh` (which would pull the diverged upstream and discard the work).

## Files in this directory
- `<name>.commits.log` — `git log --oneline` of the fork main (provenance record).
- `README.md` — this file.
