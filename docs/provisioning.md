# Provisioning — accounts, keys, hardware (S0.7 / S0.8)

**Date:** 2026-10-15. Companion to `specs/assembly_plan_v3.md` (S5 routing redesign).

## Confirmed operator accounts (decision 1, 2026-10-15)

| Account | Status | Used for |
|---|---|---|
| GitHub Student Pack | ✅ active (GITHUB_TOKEN in env) | **GitHub Models** free API (GPT-4o, Claude 3.5 Sonnet, gpt-4o-mini) |
| AMD Developer free pack | ⚠️ **TO VERIFY** (see below) | potential $0 cloud GPU hours for the 27B |
| Google AI Studio free API | ✅ (key needed in `.env`) | 1M-context lane (Gemini Flash) — RESTRICTED data lane |
| Mistral free | ✅ (key needed; **opt OUT of data training in console**) | code lane (Codestral) |
| OpenRouter free + $10/mo | ✅ (key needed; apply $10 top-up) | failover layer, 1,000 RPD free-model quota |
| Groq free API | ✅ (key needed in `.env`) | primary FREE lane (gpt-oss-120b, qwen/qwen3.8-27b) |
| Local (Ollama) | ✅ verified 2026-10-15 | `hf.co/dr-ry/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M` (primary), `qwen2.5:7b` (fallback) — both smoke-tested OK |

## ⚠️ AMD Developer free pack — manual verification (S0.7, blocked on login)

No local artifacts found (`~/.amd`, `~/.rocm` absent; no program files on disk).
**Required manual step:** log in at <https://www.amd.com/en/products/developer.html> →
check whether the pack grants **cloud GPU hours** (e.g. partner cloud credits, MI-series
access, or bundled inference credits). Record the result here:

- [ ] Contains cloud GPU hours: ______ (provider / hours / instance types)
- [ ] No GPU component (drivers/tools only) → LOCAL_HEAVY = RunPod EU (Paris/NL), 4090 24GB community/spot, Tailscale + `llama-server --api-key`.

Until resolved, the router must treat LOCAL_HEAVY as **optional/off** and rely on the
free `qwen/qwen3.8-27b` on Groq for heavy-reasoning tasks (S5.2).

## API keys (S0.8) — keys NEVER in git

Create `.env` at the repo root (already gitignored) with:

```
GROQ_API_KEY=
OPENROUTER_API_KEY=
GEMINI_API_KEY=
MISTRAL_API_KEY=
GITHUB_TOKEN=        # present in env; reuse for GitHub Models
LOCAL_HEAVY_URL=     # e.g. http://100.x.y.z:8080 (Tailscale) when GPU spun up
LOCAL_HEAVY_API_KEY=
LOCAL_HEAVY_HOURLY_COST=0.40
```

- `GITHUB_TOKEN` already present in the environment (used by GitHub MCP) — it also
  authenticates GitHub Models.
- Operator must paste in the 4 missing keys before S5 (Groq, OpenRouter, Gemini, Mistral)
  and apply the $10 OpenRouter top-up.

## Local model verification (S0.9, PASS 2026-10-15)

- `ollama list` → `hf.co/dr-ry/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M`, `qwen2.5:7b`
- Smoke call (num_predict=8) to both → `OK` returned.
- Optional later: `ollama pull qwen2.5-coder:3b` for max-throughput bulk classification.
