# Bug Bounty Harness Orchestration and AI Gateway Specification v2.1.2 (Qwen3.8-27B Integration)

> [!WARNING]
> **Routing section superseded (2026-10-16, Phase S5).** The model-routing
> adjustments below are a **v2.1.2 draft** and are superseded by
> `specs/assembly_plan_v3.md` **§S5.1–S5.7**, which defines the final routing
> structure (4 tiers incl. a config-driven `LOCAL_HEAVY`, the multi-provider
> FREE pool, SAFE/RESTRICTED data lanes with a pre-call scrub hook, per-provider
> rate limiting + 429 rotation, and runtime `/models` discovery). Phase S5 — the
> router reimplementation and the `model_routing_guide.md` rewrite — is **held
> pending the operator's $10 OpenRouter top-up**. The Qwen3.8-27B profile
> itself (S5.5, on-demand cloud GPU) remains valid reference; only the routing
> table/tier wiring in this file is outdated. Operational source of truth:
> `OPERATIONS.md`.

## Overview

This updated specification (v2.1.2) incorporates Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP as a new LOCAL AI gateway option for the bug bounty harness. It refines the orchestration and model-routing blueprint to account for on-demand cloud GPU or high-VRAM workstation deployments capable of serving this 27B model via llama-server with HauhauCS FastMTP acceleration.[^1]

## Qwen3.8-27B Aggressive FastMTP Profile

### Model and Quantization Characteristics

Qwen3.8-27B is a 27B-parameter causal language model with native text, image, and video capabilities, released under Apache 2.0 and further uncensored by HauhauCS with an “Aggressive” profile (0 refusals). The Aggressive MTP GGUF release preserves Qwen3.8’s native NextN/embedded-MTP heads and adds a HauhauCS FastMTP sidecar for acceleration across all text quantizations.[^1]

The text quantizations relevant to the harness are:

- Q4_K_P: 17.92 GB GGUF, approximate 5.25 BPW.
- Q3_K_P: 13.44 GB GGUF.
- IQ4_XS and IQ3_M/Xs: 12–15.7 GB GGUF range.

A separate BF16 mmproj projector (931 MB) enables vision, and a FastMTP 32K sidecar (903 MB) is used to accelerate text generation.[^1]

### Context and Reasoning Capabilities

The base model supports a native maximum context of 262,144 tokens and can be configured up to 1,000,000 tokens in specialized runtimes, though KV cache VRAM becomes the limiting factor. HauhauCS FastMTP provides up to 3.02× document TG and 1.93× reasoning TG versus non-MTP, and up to 35.2% more document TG and 21.1% more reasoning TG than standard embedded MTP at Q8_K_P, with all drafted tokens verified by the target model.[^1]

The recommended thinking-mode parameters are temperature 1.0, top-p 0.95, top-k 20, no presence penalty, repetition penalty 1.0, with reasoning-effort set to `xhigh` for deepest chains. Non-thinking mode uses lower temperature and top-p and disables the embedded reasoning path.[^1]

### Hardware and Runtime Assumptions

HauhauCS qualifies FastMTP on an RTX PRO 6000 Blackwell 96 GB GPU for maximum native context and high throughput. Embedded MTP reference speeds on RTX 6000 Ada for Q4_K_P show ~92.6 TG tokens/s, while FastMTP at depth 3 increases document and reasoning throughput significantly.[^1]

For harness deployment, a more modest but realistic configuration is:

- Workstation: 24–48 GB VRAM (RTX 4090, RTX A6000) running Q4_K_P with context reduced to 8k–32k.
- Cloud GPU: 24 GB RTX 4090 or 48 GB L40S on RunPod/Vast/Lambda with `--ctx-size` tuned to hunt workloads rather than maximum native context.

The runtime is llama.cpp with HauhauCS FastMTP patch applied, serving via `llama-server` in OpenAI-compatible mode. The recommended service command for Q4_K_P + FastMTP is:

- `--model` set to Q4_K_P GGUF.
- `--spec-draft-model` set to FastMTP-32K sidecar.
- `--spec-type draft-mtp` and `--spec-draft-n-max 3`.
- `--ctx-size` tuned (e.g., 8192–204800 depending on VRAM).
- `--reasoning on`, `--reasoning-effort xhigh`, `--jinja` for chat template.[^1]

## Role of Qwen3.8-27B in the Harness

### New LOCAL Tier: High-Reasoning Uncensored Backend

Qwen3.8-27B Aggressive serves as a high-reasoning, uncensored LOCAL backend for exploit ideation, payload mutation, and offensive strategy planning, complementing and partially replacing Groq 70B usage in offensive phases.[^2][^1]

Key harness roles:

- `adhd` divergence frames: deep brainstorming of attack vectors, WAF bypasses, and business-logic abuse.
- Specialist payload generation: complex polyglot and chained payloads for SQLi, XSS, SSRF, RCE, XXE, CSTI, and prototype pollution.
- Exploit chain synthesis: multi-step reasoning over findings, OOB callbacks, and session matrices.
- AI jailbreak and CL4R1T4S-based bypass attempts where uncensored output is critical.

Qwen3.8-27B remains text-focused in this integration; the mmproj vision projector is optional and can be added later for screenshot/DOM image analysis, but the current harness design focuses on text-only exploit reasoning.[^1]

### Routing Adjustments

> [!NOTE]
> **Superseded — see the banner at the top of this file and `specs/assembly_plan_v3.md` §S5.4.**
> The illustrative table below is the v2.1.2 draft; the final per-task routing
> table and tier wiring are specified in S5.4.5. Kept for reference only.

The model-routing table is updated to add a new LOCAL tier model identifier, e.g., `qwen3.8-27b-aggressive-q4-local`, pointing at the llama-server endpoint hosting Q4_K_P + FastMTP. Tasks that previously routed to Groq Llama 3.1 70B for deep offensive reasoning now have the option to route to this LOCAL model when the 27B gateway is available.[^3][^2]

Illustrative changes:

- `ideation_deep` (Phase ③):
  - Primary: `qwen3.8-27b-aggressive-q4-local` (LOCAL_27B).
  - Fallback: `llama-3.1-70b-versatile` (PAID_FREE).

- `payload_polyglot` (Phase ④):
  - Primary: `qwen3.8-27b-aggressive-q4-local`.
  - Fallback: Groq 70B.

- `chain_analysis` and `impact_escalation` (Phase ⑩):
  - Primary: Groq 70B for general reasoning and business logic.
  - Optional: Qwen3.8-27B for exploit-centric chains where uncensored exploration is needed.

- `ai_jailbreak_confirm`:
  - Primary: `qwen3.8-27b-aggressive-q4-local` for crafting and testing jailbreak payloads.
  - Fallback: Groq 70B and GPT-4o-mini for confirmation in frontier models.

ModelRouter’s configuration gains an additional tier label (for clarity) or reuses LOCAL tier with an internal flag specifying “LOCAL_HEAVY” to distinguish laptop-scale models from 27B-scale deployments.[^2][^3]

## Deployment Profiles Including Qwen3.8-27B

### Profile E: Local 27B on Workstation

**Use case:** Single operator with a dedicated workstation (24–48 GB GPU) running Qwen3.8-27B locally alongside the harness control plane.[^2][^1]

**Hardware:**

- CPU: 8–16 cores.
- RAM: 64–128 GB.
- GPU: RTX 4090 (24 GB) or A6000 (48 GB).

**Model configuration:**

- Text quant: Q4_K_P (17.92 GB).
- FastMTP sidecar: FastMTP-32K (903 MB).
- Context: 8k–32k tokens to match exploit-hunt workflows and avoid KV cache exhaustion.[^1]

**Gateway wiring:**

- `llama-server` listens on `http://127.0.0.1:8080` or another dedicated port.
- Harness `HarnessConfig` adds `qwen3_27b_url` or repurposes `ollama_url` when Ollama is not used.
- ModelRouter maps `LOCAL_HEAVY` tasks to this endpoint.

**Cost:**

- Upfront hardware (~1,200–3,000 USD for GPU and RAM as per infrastructure specs).[^1]
- Ongoing cost mainly electricity; no per-token charges.

This profile significantly reduces reliance on Groq 70B in phases ③–⑩, at the expense of hardware investment.[^2][^1]

### Profile F: Cloud 27B Gateway (RTX 4090/L40S)

**Use case:** Laptop control-plane with a cloud GPU instance hosting Qwen3.8-27B for a limited time-window during hunts.[^1]

**Hardware (cloud):**

- RTX 4090 (24 GB) or L40S (48 GB) on RunPod/Vast/Lambda.

**Model configuration:**

- Text quant: Q4_K_P.
- FastMTP sidecar: FastMTP-32K.
- Context: 8k–16k (4090) or 32k–64k (L40S).[^1]

**Gateway wiring:**

- `llama-server` listens on a public or VPN-exposed address; OpAdmiral and ModelRouter use its URL as the LOCAL_27B endpoint.
- Egress proxy rules must treat calls to this endpoint as internal (no scope enforcement), while all target traffic continues through compliance proxy.[^4][^1]

**Cost:**

- 4090 instance: ~0.35 USD/hr; L40S ~0.79 USD/hr, yielding ~2.8–6.3 USD for an 8-hour intensive hunt.[^1]

This profile adds a pay-per-hour heavy LOCAL backend for select hunts without permanent hardware, with ModelRouter configured to fall back to Groq 70B when the cloud endpoint is offline.[^3][^2]

## Updated AI Gateway Matrix

### Gateway Types (v2.1.2)

The harness now recognizes four effective gateway categories:

1. **LOCAL_LIGHT:** Laptop Ollama models (3–8B) for cheap classification and basic payloads.
2. **LOCAL_HEAVY:** Qwen3.8-27B Aggressive served via llama-server on workstation or cloud GPU.
3. **PAID_FREE:** Groq 70B and related models.
4. **PAID_PREMIUM:** GPT-4o/4o-mini, Claude Sonnet/Haiku.

LOCAL_LIGHT and LOCAL_HEAVY share the `LOCAL` tier conceptually but differ in endpoint and applicable tasks. LOCAL_HEAVY is reserved for tasks that benefit from uncensored deep reasoning and can tolerate slower generation relative to Groq’s hosted 70B, while LOCAL_LIGHT remains the default for high-volume classification.[^3][^2]

### Comparative Gateway Usage by Phase

- Phase ①–② (scope, recon): Mostly unchanged; LOCAL_LIGHT and PAID_FREE handle edge cases; LOCAL_HEAVY not required.
- Phase ③ (attack planning): LOCAL_HEAVY (Qwen3.8-27B) becomes primary for `ideation_deep` and WAF evasion when available; Groq 70B remains fallback.[^2][^1]
- Phase ④–⑤ (payloads, code analysis): LOCAL_HEAVY used for complex payload generation and multi-language exploit reasoning; LOCAL_LIGHT and tool-based analysis handle routine cases.[^2]
- Phase ⑦–⑧ (response analysis, FP filtering): LOCAL_LIGHT remains primary, with LOCAL_HEAVY reserved for ambiguous or high-impact findings.
- Phase ⑨–⑩ (validation, chains): PAID_FREE and PAID_PREMIUM still lead general triage and narrative; LOCAL_HEAVY is used for exploit-centric chain construction and jailbreak-specific flows.[^3][^2]
- Phase ⑪–⑫ (triage, reporting): PAID_PREMIUM (Sonnet/GPT-4o) remains the main narrative/report writer, using findings enriched by LOCAL_HEAVY reasoning where available.[^2]

## Integration Considerations

### Security and Compliance

Qwen3.8-27B Aggressive is explicitly uncensored, which increases the risk of generating payloads or strategies that could violate program rules if applied out-of-scope. Therefore:

- All HTTP requests produced as a result of LOCAL_HEAVY planning must still pass through `compliance/egress_proxy.py` and ScopeGate.[^4][^3]
- AI jailbreak and offensive payload specialists using this backend must be constrained to in-scope assets and targets as defined in `TargetScope` and platform_profile.json.

The harness does not allow direct network access from the model runtime to targets; Qwen3.8-27B integration adds reasoning power, not new network surfaces, which preserves compliance invariants.[^4]

### Observability and Budgeting

TokenTracker must gain awareness of LOCAL_HEAVY usage as a separate bucket so that GPU-hours and inference load can be monitored and optionally billed or cost-shared. New events such as `local_heavy_usage` can be emitted to T3MP3ST, showing how often Qwen3.8-27B is invoked and how many tasks route to it versus Groq or laptop-local models.[^5][^3]

HarnessConfig may gain additional fields:

- `local_heavy_enabled: bool`.
- `local_heavy_url: str` (llama-server endpoint).
- `local_heavy_hourly_cost: float` (for cloud GPU sessions).

These allow OpAdmiral to make cost-aware routing decisions, e.g., only using LOCAL_HEAVY when a wing’s expected value justifies GPU-hour spend.[^6][^3]

### Failure and Fallback

If the LOCAL_HEAVY endpoint is unavailable or misconfigured, ModelRouter should transparently fall back to Groq 70B for affected tasks. Startup health checks can probe `local_heavy_url` alongside `ollama_url` and Groq, emitting warnings in logs and the war room when Qwen3.8-27B is offline.[^3]

## Blueprint Updates

The blueprint to complete Qwen3.8-27B integration is:

1. **Deploy llama-server with Q4_K_P + FastMTP** on either workstation or cloud GPU, exposing an OpenAI-compatible HTTP endpoint.[^1]
2. **Extend HarnessConfig and ModelRouter** to recognize a `LOCAL_HEAVY` endpoint and update routing entries for deep offensive reasoning tasks (ideation, payload_polyglot, chain_analysis, ai_jailbreak_confirm).
3. **Update TokenTracker and T3MP3ST** to display LOCAL_HEAVY usage, GPU-hour estimates, and budget impact.
4. **Ensure egress proxy and ScopeGate invariants** remain unchanged; Qwen3.8-27B must not bypass compliance layers.
5. **Document cost models** for workstation and cloud GPU deployments using the infrastructure and cloud pricing specs to decide when to enable or disable LOCAL_HEAVY per engagement.[^1]

This v2.1.2 specification keeps the original harness orchestration intact while layering in Qwen3.8-27B as a powerful, uncensored LOCAL reasoning engine, with clear routing, compliance, and cost boundaries.[^3][^2][^1]

---

## References

1. [`infrastructure_specs.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/infrastructure_specs.md) - # Bug Bounty Harness — Infrastructure & Machine Specifications

**Version:** 2.1.1  
**Companion to:...

2. [`model_routing_guide.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/model_routing_guide.md) - # Bug Bounty Harness — LLM Model Routing & Task Allocation Guide

**Companion to:** [``bug_bounty_har...

3. [progress_report.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/`bug_bounty_har...

3. [progress_report.md) - # Bug Bounty Harness — Progress Report & Remaining Work

**Date:** 2026-09-06  
**Project:** Autonom...

4. [`bug_bounty_harness_design_v2_1.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/bug_bounty_harness_design_v2_1.md) - # Bug Bounty Harness — Assembly Plan & Technical Specification v2.1.1

**Version:** 2.1.1 (Planning ...

5. [`workflow_overview.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/workflow_overview.md) - # Bug Bounty Harness — High-Level Workflow & Repo Map

**Purpose:** What each repository provides, h...

6. [`implementation_guide.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/implementation_guide.md) - # Bug Bounty Harness — Step-by-Step Implementation Guide

**Companion to:** [`bug_bounty_harness_des...

