# Bug Bounty Harness — LLM Model Routing & Task Allocation Guide

> [!WARNING]
> **STALE — superseded by Phase S5 (2026-10-16).** This guide describes the
> pre-S5 **3-tier, single-Groq** routing model (`LOCAL` / `PAID_FREE` /
> `PAID_PREMIUM`) with retired model names and the old cost model. It no longer
> matches the approved design. The replacement routing structure is specified in
> `specs/assembly_plan_v3.md` **§S5.1–S5.7** (4 tiers incl. `LOCAL_HEAVY`, the
> multi-provider FREE pool — Groq primary, OpenRouter failover, GitHub Models,
> Mistral, Gemini — SAFE/RESTRICTED data lanes with a pre-call scrub hook,
> per-provider rate limiters + 429 rotation, runtime `/models` discovery, and
> the new S5.7 cost model). Phase S5 (the router reimplementation + this
> guide's rewrite) is **held pending the operator's $10 OpenRouter top-up**;
> see `OPERATIONS.md` §5. Until S5 lands, treat this file as a historical
> reference only — **the operational source of truth is `OPERATIONS.md`.**

**Companion to:** [`bug_bounty_harness_design_v2_1.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/bug_bounty_harness_design_v2_1.md)  
**Hardware Baseline:** AMD Ryzen 5 7535HS | 16 GB DDR5 | RTX 4050 6 GB VRAM | Kali Linux  
**Design Principle:** Maximize local inference. Use free APIs for heavy reasoning. Reserve paid APIs for confirmed findings only.

---

## 1. Bug Bounty Hunt Workflow — Phase Breakdown

A complete bug bounty engagement flows through 12 distinct phases. Each phase has different cognitive demands — some need raw speed (thousands of quick classifications), others need deep reasoning (chain analysis). This determines which model is optimal.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    BUG BOUNTY HUNT WORKFLOW                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ① Scope Parsing ──► ② Recon & Discovery ──► ③ Attack Planning         │
│       (fast)              (no LLM)              (deep reasoning)        │
│         │                    │                       │                   │
│         ▼                    ▼                       ▼                   │
│  ④ Payload Generation ◄── ⑤ JS/Code Analysis ──► ⑥ Fuzzing             │
│    (code-focused)          (code-focused)         (no LLM)              │
│         │                    │                       │                   │
│         ▼                    ▼                       ▼                   │
│  ⑦ Response Analysis ──► ⑧ FP Filtering ──► ⑨ Validation               │
│    (pattern matching)     (fast classify)     (deep reasoning)          │
│         │                    │                       │                   │
│         ▼                    ▼                       ▼                   │
│  ⑩ Chain Discovery ──► ⑪ Triage & Severity ──► ⑫ Report Generation     │
│    (deep reasoning)     (medium reasoning)      (writing quality)       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Available Model Pool

### Tier 1: LOCAL (Free — Ollama on RTX 4050)

| Model | Params | VRAM (Q4) | Speed | Strengths | Weaknesses |
|---|---|---|---|---|---|
| **`qwen2.5-coder:7b`** | 7B | 4.7 GB | 40–55 tok/s | Code understanding, payload syntax, regex, structured output | Weak at multi-step logic chains |
| **`llama3.1:8b`** | 8B | 4.9 GB | 35–50 tok/s | General reasoning, instruction following, JSON output | Weaker code skills than qwen-coder |
| **`mistral:7b`** | 7B | 4.1 GB | 45–60 tok/s | Fastest local option, good at classification tasks | Weakest reasoning of the three |
| **`qwen2.5-coder:3b`** | 3B | 2.0 GB | 70–90 tok/s | Ultra-fast classification, noise filtering | Too small for complex tasks |

> **Constraint:** Only ONE model loaded at a time due to 6 GB VRAM. Ollama swaps on demand (~2s cold-load with persistence mode).

### Tier 2: PAID_FREE (Free API — Groq)

| Model | Params | Speed | Rate Limit (free) | Strengths | Weaknesses |
|---|---|---|---|---|---|
| **`llama-3.1-70b-versatile`** | 70B | 200+ tok/s | 30 RPM / 14.4K tok/min | Deep multi-step reasoning, chain analysis, complex logic | Limited context (128K but high latency) |
| **`llama-3.1-8b-instant`** | 8B | 750+ tok/s | 30 RPM / 14.4K tok/min | Ultra-fast, good for bulk classification | Same quality as local llama3.1:8b |
| **`mixtral-8x7b-32768`** | 46.7B MoE | 400+ tok/s | 30 RPM / 5K tok/min | Good balance of speed and quality | Lower rate limit |
| **`gemma2-9b-it`** | 9B | 500+ tok/s | 30 RPM / 15K tok/min | Strong instruction following | Weaker at code |

> **Constraint:** 30 requests/minute on free tier. Use for tasks that need 70B reasoning but are infrequent (validation, chain analysis, severity assessment).

### Tier 3: PAID_PREMIUM (Paid API — use sparingly)

| Model | Provider | Cost (approx) | Best For |
|---|---|---|---|
| **`gpt-4o`** | OpenAI | $2.50/$10 per 1M tok | Final report writing, CVSS justification |
| **`gpt-4o-mini`** | OpenAI | $0.15/$0.60 per 1M tok | Bulk tasks when Groq rate-limited |
| **`claude-sonnet-4`** | Anthropic | $3/$15 per 1M tok | Security reasoning, exploit chain analysis |
| **`claude-haiku`** | Anthropic | $0.25/$1.25 per 1M tok | Fast paid fallback for classification |

> **Usage rule:** PAID_PREMIUM is used ONLY for confirmed findings (post-triage) or when both LOCAL and PAID_FREE are exhausted/rate-limited.

---

## 3. Task-to-Model Routing Matrix

This is the core routing table that `budget/model_router.py` implements. Each row is a specific task that occurs during the bug bounty workflow, mapped to its optimal model.

### Phase ① Scope Parsing

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| Parse scope CSV/JSON | Structured data extraction | **No LLM needed** | — | `compliance/scope_importer.py` handles this with pure Python parsing |
| Interpret ambiguous scope rules | "All *.example.com except staging" | `llama-3.1-70b` | PAID_FREE | Requires nuanced language understanding to avoid scope violations |
| Generate ScopeGate regex | Convert human scope descriptions to regex patterns | `qwen2.5-coder:7b` | LOCAL | Regex is a code task — qwen-coder excels here |

### Phase ② Recon & Discovery

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| Subdomain enumeration | Run tools (subfinder, amass) | **No LLM needed** | — | Pure CLI tool execution |
| URL crawling / spidering | Crawl target endpoints | **No LLM needed** | — | CLI tools (katana, gospider) |
| jsleak secret scanning | Regex-based JS analysis | **No LLM needed** | — | Go binary, regex-only |
| Prioritize discovered endpoints | Rank URLs by vulnerability likelihood | `qwen2.5-coder:7b` | LOCAL | Fast classification of URL patterns (e.g., `/api/admin/delete` → high priority) |

### Phase ③ Attack Planning (adhd ideation)

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| Divergent brainstorming | Generate attack vectors for an endpoint | `llama-3.1-70b` | PAID_FREE | Needs creative, multi-angle reasoning that 7B models lack |
| Frame-specific ideation | Security-focused adhd frames (recon_diverge, payload_mutate) | `llama3.1:8b` | LOCAL | Fast iteration; quality acceptable for brainstorming |
| FP anti-pattern check | Query mempalace for known false positives before proceeding | `qwen2.5-coder:3b` | LOCAL | Simple lookup + string matching; speed > quality |
| WAF evasion strategy | Plan bypass techniques for detected WAF | `llama-3.1-70b` | PAID_FREE | Requires knowledge of multiple WAF vendors and bypass techniques |

### Phase ④ Payload Generation

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| SQLi payload crafting | Generate UNION/blind/time-based payloads | `qwen2.5-coder:7b` | LOCAL | **Best local model for this.** Understands SQL syntax, encoding, and context |
| XSS payload mutation | Mutate payloads to bypass filters | `qwen2.5-coder:7b` | LOCAL | Code transformation is qwen-coder's strength |
| SSTI/CSTI template payloads | Jinja2, Twig, Freemarker injection strings | `qwen2.5-coder:7b` | LOCAL | Template syntax is code |
| Polyglot payload generation | Multi-context payloads (HTML+JS+SQL) | `llama-3.1-70b` | PAID_FREE | Complex cross-context reasoning benefits from 70B |
| JWT manipulation | Forge/modify JWT tokens (alg:none, key confusion) | `qwen2.5-coder:7b` | LOCAL | JSON/Base64 manipulation is structured code work |
| Prototype pollution chains | Craft `__proto__` / `constructor.prototype` payloads | `qwen2.5-coder:7b` | LOCAL | JavaScript AST understanding |
| OOB payload embedding | Insert Interactsh URLs into SSRF/XXE/RCE payloads | `qwen2.5-coder:7b` | LOCAL | String templating — trivial for any code model |

### Phase ⑤ JavaScript / Source Code Analysis

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| JS endpoint extraction | Find API routes in minified JS bundles | `qwen2.5-coder:7b` | LOCAL | **Primary code analysis model.** Excellent at reading JS/TS |
| Hardcoded secret detection | Find API keys, tokens in source | `qwen2.5-coder:7b` | LOCAL | Pattern recognition in code |
| Source code vulnerability scan | T3MP3ST whitebox AST review | `qwen2.5-coder:7b` | LOCAL | Code-native model handles AST patterns well |
| Complex data flow analysis | Trace user input → sink paths across files | `llama-3.1-70b` | PAID_FREE | Multi-file reasoning needs larger context + deeper logic |
| Deobfuscation assistance | Help understand obfuscated JS | `llama-3.1-70b` | PAID_FREE | Requires pattern recognition beyond 7B capability |

### Phase ⑥ Fuzzing & Scanning

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| Parameter fuzzing | Send payloads to discovered parameters | **No LLM needed** | — | Automated HTTP requests via Python/Go tools |
| Rate-limited request scheduling | Queue requests within platform limits | **No LLM needed** | — | `compliance/header_injector.py` rate limiter |
| Adaptive payload selection | Choose next payload based on prior responses | `mistral:7b` | LOCAL | Fastest local model; simple classification of response patterns |

### Phase ⑦ Response Analysis

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| Error signature detection | Classify error messages (SQL error, stack trace, WAF block) | `qwen2.5-coder:3b` | LOCAL | Ultra-fast classification; 70–90 tok/s; processes thousands of responses |
| DOM-based XSS confirmation | Analyze rendered HTML for reflected input | `qwen2.5-coder:7b` | LOCAL | Needs HTML/DOM understanding |
| HTTP header anomaly detection | Flag unusual headers (CORS misconfig, info leak) | `mistral:7b` | LOCAL | Simple pattern matching, speed matters |
| Time-based blind detection | Analyze response timing patterns | **No LLM needed** | — | Statistical analysis, no language understanding needed |

### Phase ⑧ False Positive Filtering

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| Noise filter (pre-triage) | Drop non-bountiable issues (missing headers, SPF) | `qwen2.5-coder:3b` | LOCAL | **Highest volume task.** Needs maximum speed. Binary classify: bountiable or not |
| Self-XSS detection | Determine if XSS requires victim interaction | `llama3.1:8b` | LOCAL | Needs understanding of attack prerequisites |
| Known FP pattern matching | Compare finding against mempalace FP database | **No LLM needed** | — | Database lookup, no reasoning needed |
| Confidence scoring | Assign 0–100 confidence to each finding | `llama3.1:8b` | LOCAL | Moderate reasoning with JSON output |

### Phase ⑨ Validation (Confirming Real Vulns)

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| SQLi proof-of-concept | Confirm SQLi by extracting data / demonstrating impact | `llama-3.1-70b` | PAID_FREE | **Critical accuracy task.** False confirmation → ban risk. Needs deep reasoning |
| IDOR 4-session matrix test | Cross-check User A/B/Admin/Unauth access patterns | `llama-3.1-70b` | PAID_FREE | Complex authorization logic analysis |
| SSRF/RCE OOB callback confirmation | Correlate Interactsh callback with sent payload | `llama3.1:8b` | LOCAL | Correlation is simple: UUID match + timing |
| Playwright DOM validation | Confirm XSS fires in real browser | **No LLM needed** | — | Headless Chromium executes JS natively |
| Business logic flaw validation | Test multi-step business rule violations | `llama-3.1-70b` | PAID_FREE | Requires understanding application business rules |
| AI jailbreak confirmation | Verify model outputs restricted content | `llama-3.1-70b` | PAID_FREE | Needs to evaluate whether output actually constitutes a jailbreak |

### Phase ⑩ Chain Discovery

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| Vulnerability chaining analysis | Link SSRF + IDOR into account takeover chain | `llama-3.1-70b` | PAID_FREE | **Highest reasoning demand in entire workflow.** Multi-step causal reasoning |
| Impact escalation assessment | Can low-sev finding escalate via other findings? | `llama-3.1-70b` | PAID_FREE | Requires understanding of full attack surface |
| Attack narrative construction | Build coherent multi-step PoC story | `claude-sonnet-4` | PAID_PREMIUM | Writing quality matters for chains — use only for confirmed chains |

### Phase ⑪ Triage & Severity Classification

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| VRT classification | Map finding to Bugcrowd VRT taxonomy | `llama3.1:8b` | LOCAL | Structured mapping with known categories |
| CWE assignment | Map finding to CWE ID | `llama3.1:8b` | LOCAL | Lookup-style reasoning |
| CVSS 3.1 vector calculation | Generate CVSS vector string with justification | `llama-3.1-70b` | PAID_FREE | Needs nuanced understanding of attack complexity, privileges required, scope |
| Severity dispute preparation | Anticipate triager objections and pre-address them | `llama-3.1-70b` | PAID_FREE | Adversarial reasoning: think like the triager |
| Duplicate detection | Check if finding matches existing reports | `qwen2.5-coder:7b` | LOCAL | Semantic similarity comparison |

### Phase ⑫ Report Generation

| Task | Description | Optimal Model | Tier | Why |
|---|---|---|---|---|
| Report draft generation | Write full Markdown report with PoC | `llama-3.1-70b` | PAID_FREE | First draft doesn't need paid quality |
| Report refinement & polish | Professional language, clear impact statement | `gpt-4o` or `claude-sonnet-4` | PAID_PREMIUM | **Only task where paid models are strongly recommended.** Report quality directly affects bounty payout and triager response time |
| Platform-specific formatting | Adapt report to H1/BC/YWH template requirements | `llama3.1:8b` | LOCAL | Template-based transformation; structural, not creative |
| Screenshot annotation | Generate alt-text descriptions for evidence screenshots | `llama3.1:8b` | LOCAL | Simple descriptive task |

---

## 4. Model Router Decision Flowchart

This is the logic `budget/model_router.py` executes for every LLM request:

```
                     ┌──────────────────┐
                     │  Incoming Task   │
                     └────────┬─────────┘
                              │
                     ┌────────▼─────────┐
                     │ Check task_tier   │
                     │ from routing      │
                     │ matrix (§3)       │
                     └────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
     ┌────────▼──────┐ ┌─────▼──────┐ ┌──────▼────────┐
     │  tier=LOCAL   │ │tier=PAID   │ │tier=PAID      │
     │               │ │   _FREE    │ │  _PREMIUM     │
     └────────┬──────┘ └─────┬──────┘ └──────┬────────┘
              │              │               │
     ┌────────▼──────┐ ┌─────▼──────┐ ┌──────▼────────┐
     │ Ollama alive? │ │ Groq key   │ │ API key set?  │
     │ GET /api/tags │ │ set?       │ │               │
     └───┬──────┬────┘ └──┬─────┬──┘ └───┬──────┬────┘
        YES     NO       YES    NO      YES     NO
         │       │        │      │       │       │
         ▼       │        ▼      │       ▼       │
     ┌───────┐   │   ┌────────┐  │  ┌────────┐   │
     │ Run   │   │   │  Groq  │  │  │OpenAI/ │   │
     │Ollama │   │   │  API   │  │  │Claude  │   │
     │ model │   │   │  call  │  │  │  call  │   │
     └───────┘   │   └────────┘  │  └────────┘   │
                 │               │               │
                 └───────┐       │       ┌───────┘
                         │       │       │
                         ▼       ▼       ▼
                    ┌─────────────────────────┐
                    │   FALLBACK CHAIN:       │
                    │   LOCAL → PAID_FREE →   │
                    │   PAID_PREMIUM →        │
                    │   NoBudgetError         │
                    └─────────────────────────┘
```

---

## 5. Token Budget Allocation Strategy

Given your hardware and a $5–10/month budget ceiling, here's how tokens should be distributed across a typical hunting session (4–6 hour session against a single program):

### Per-Session Budget Breakdown

| Workflow Phase | Tasks | Estimated Calls | Model | Tokens/Call | Total Tokens | Cost |
|---|---|---|---|---|---|---|
| ③ Attack Planning | Ideation frames | 10–20 | LOCAL `llama3.1:8b` | 2,000 | 40,000 | $0.00 |
| ③ WAF/Complex planning | Deep brainstorm | 3–5 | Groq `70b` | 3,000 | 15,000 | $0.00 |
| ④ Payload Generation | Craft payloads | 50–100 | LOCAL `qwen2.5-coder:7b` | 500 | 50,000 | $0.00 |
| ⑤ Code Analysis | JS review | 20–40 | LOCAL `qwen2.5-coder:7b` | 1,500 | 60,000 | $0.00 |
| ⑦ Response Analysis | Classify responses | 200–500 | LOCAL `qwen2.5-coder:3b` | 200 | 100,000 | $0.00 |
| ⑧ FP Filtering | Noise filter | 100–300 | LOCAL `qwen2.5-coder:3b` | 150 | 45,000 | $0.00 |
| ⑧ Confidence scoring | Score findings | 10–30 | LOCAL `llama3.1:8b` | 500 | 15,000 | $0.00 |
| ⑨ Validation | Confirm real vulns | 3–8 | Groq `70b` | 4,000 | 32,000 | $0.00 |
| ⑩ Chain Discovery | Link vulns | 1–3 | Groq `70b` | 5,000 | 15,000 | $0.00 |
| ⑪ CVSS + Triage | Severity calc | 3–8 | Groq `70b` | 2,000 | 16,000 | $0.00 |
| ⑫ Report Draft | First draft | 1–3 | Groq `70b` | 4,000 | 12,000 | $0.00 |
| ⑫ Report Polish | Final quality | 1–3 | GPT-4o | 4,000 | 12,000 | ~$0.15 |
| **TOTAL** | | **~400–1,000 calls** | | | **~400K tokens** | **~$0.15** |

### Monthly Projection (20 sessions)

| Tier | Monthly Tokens | Monthly Cost |
|---|---|---|
| LOCAL (Ollama) | ~6.2M tokens | **$0.00** |
| PAID_FREE (Groq) | ~1.8M tokens | **$0.00** |
| PAID_PREMIUM (GPT-4o) | ~240K tokens | **~$3.00** |
| **Total** | **~8M tokens** | **~$3.00/month** |

---

## 6. Model Swap Strategy for 6 GB VRAM

Since only one model fits in VRAM at a time, `model_router.py` must manage swaps efficiently:

```
┌────────────────────────────────────────────────────────────────┐
│                   MODEL SWAP TIMELINE                          │
│                   (typical hunting session)                     │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  Session Start                                                 │
│  ├── Load qwen2.5-coder:7b (4.7 GB) ← stays loaded           │
│  │   └── Handles: payloads, JS review, endpoint priority,     │
│  │       response analysis, duplicate detection                │
│  │                                                             │
│  │   [Groq API handles all 70B tasks in parallel]              │
│  │   └── Handles: validation, chains, CVSS, report draft      │
│  │                                                             │
│  ├── When IDOR/BAC testing starts:                             │
│  │   └── SWAP to llama3.1:8b (~2s) for session reasoning      │
│  │   └── SWAP back to qwen2.5-coder:7b when done              │
│  │                                                             │
│  ├── When bulk noise filtering needed:                         │
│  │   └── SWAP to qwen2.5-coder:3b (~1s) for max throughput    │
│  │   └── SWAP back to qwen2.5-coder:7b when done              │
│  │                                                             │
│  Session End                                                   │
│  └── Report polish: single GPT-4o API call                    │
│                                                                │
│  Expected swaps per session: 2–4 (each ~2 seconds)             │
└────────────────────────────────────────────────────────────────┘
```

### Swap Optimization Rules

1. **Batch similar tasks.** Don't swap for a single query. Queue all noise-filter tasks, swap to `3b`, process batch, swap back.
2. **Default resident model: `qwen2.5-coder:7b`.** This handles the widest range of tasks.
3. **Set `OLLAMA_KEEP_ALIVE=5m`.** After 5 minutes of inactivity, Ollama unloads the model to free VRAM for Playwright.
4. **Never load 14B+ locally.** VRAM spill to RAM drops speed to 1–3 tok/s, which is slower than a Groq API call.

---

## 7. Specialist-to-Model Mapping

Each of the 16 specialist agents has a primary and fallback model assignment:

| Specialist | Primary Task | Primary Model (Tier) | Fallback Model (Tier) |
|---|---|---|---|
| `sqli_specialist` | Payload crafting + response analysis | `qwen2.5-coder:7b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `xss_specialist` | Payload mutation + DOM analysis | `qwen2.5-coder:7b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `ssrf_specialist` | URL crafting + OOB correlation | `qwen2.5-coder:7b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `idor_specialist` | Session matrix reasoning | `llama3.1:8b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `lfi_specialist` | Path traversal payload crafting | `qwen2.5-coder:7b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `rce_specialist` | Command injection + OOB | `qwen2.5-coder:7b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `xxe_specialist` | XML payload crafting + OOB | `qwen2.5-coder:7b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `jwt_specialist` | Token manipulation + crypto analysis | `qwen2.5-coder:7b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `open_redirect_specialist` | URL bypass techniques | `qwen2.5-coder:7b` (LOCAL) | `llama3.1:8b` (LOCAL) |
| `prototype_pollution_specialist` | JS prototype chain analysis | `qwen2.5-coder:7b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `csti_specialist` | Template injection payloads | `qwen2.5-coder:7b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `mass_assignment_specialist` | Object property guessing | `llama3.1:8b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `header_injection_specialist` | HTTP header crafting | `qwen2.5-coder:7b` (LOCAL) | `llama3.1:8b` (LOCAL) |
| `bac_specialist` | Authorization logic reasoning | `llama3.1:8b` (LOCAL) | Groq `70b` (PAID_FREE) |
| `ai_jailbreak_specialist` | Prompt injection + CL4R1T4S | Groq `70b` (PAID_FREE) | `gpt-4o-mini` (PAID_PREMIUM) |
| `business_logic_specialist` | Multi-step logic reasoning | Groq `70b` (PAID_FREE) | `claude-sonnet-4` (PAID_PREMIUM) |

### Pattern Summary

- **12 specialists** default to LOCAL `qwen2.5-coder:7b` — all code/payload-heavy tasks
- **2 specialists** (IDOR, BAC, mass_assignment) default to LOCAL `llama3.1:8b` — reasoning over authorization logic
- **2 specialists** (AI jailbreak, business logic) default to PAID_FREE `70b` — require deep reasoning that 7B/8B can't handle

---

## 8. Configuration for `model_router.py`

This is the configuration data structure the implementer should embed in `budget/model_router.py`:

```python
MODEL_ROUTING_TABLE = {
    # Phase ① Scope
    "scope_regex_gen":        {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "scope_interpret":        {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},

    # Phase ③ Planning
    "ideation_frame":         {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "ideation_deep":          {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "waf_evasion":            {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "fp_pattern_check":       {"tier": "LOCAL",        "model": "qwen2.5-coder:3b"},

    # Phase ④ Payloads
    "payload_craft":          {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "payload_polyglot":       {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "oob_embed":              {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},

    # Phase ⑤ Code Analysis
    "js_endpoint_extract":    {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "secret_detection":       {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "source_vuln_scan":       {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "dataflow_analysis":      {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "deobfuscation":          {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},

    # Phase ⑥ Fuzzing
    "adaptive_payload_select":{"tier": "LOCAL",        "model": "mistral:7b"},

    # Phase ⑦ Response Analysis
    "error_classify":         {"tier": "LOCAL",        "model": "qwen2.5-coder:3b"},
    "dom_xss_confirm":        {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},
    "header_anomaly":         {"tier": "LOCAL",        "model": "mistral:7b"},

    # Phase ⑧ FP Filtering
    "noise_filter":           {"tier": "LOCAL",        "model": "qwen2.5-coder:3b"},
    "self_xss_detect":        {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "confidence_score":       {"tier": "LOCAL",        "model": "llama3.1:8b"},

    # Phase ⑨ Validation
    "vuln_confirm":           {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "idor_matrix_analyze":    {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "oob_correlate":          {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "biz_logic_validate":     {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "ai_jailbreak_confirm":   {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},

    # Phase ⑩ Chains
    "chain_analysis":         {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "impact_escalation":      {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "chain_narrative":        {"tier": "PAID_PREMIUM", "model": "claude-sonnet-4-20250514"},

    # Phase ⑪ Triage
    "vrt_classify":           {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "cwe_assign":             {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "cvss_calculate":         {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "dispute_prep":           {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "duplicate_detect":       {"tier": "LOCAL",        "model": "qwen2.5-coder:7b"},

    # Phase ⑫ Reports
    "report_draft":           {"tier": "PAID_FREE",    "model": "llama-3.1-70b-versatile"},
    "report_polish":          {"tier": "PAID_PREMIUM", "model": "gpt-4o"},
    "report_format":          {"tier": "LOCAL",        "model": "llama3.1:8b"},
    "screenshot_alt_text":    {"tier": "LOCAL",        "model": "llama3.1:8b"},
}
```

---

## 9. Ollama Model Pull Commands (Profile A)

```bash
# Required models (pull these before first session)
ollama pull qwen2.5-coder:7b      # 4.7 GB — primary code model
ollama pull llama3.1:8b            # 4.9 GB — general reasoning
ollama pull qwen2.5-coder:3b      # 2.0 GB — ultra-fast classifier

# Optional (only if you want a pure speed fallback)
ollama pull mistral:7b             # 4.1 GB — fastest general model

# Total disk: ~16 GB for all four models
# Only ONE loaded in VRAM at a time
```

---

## 10. Cost Ceiling Enforcement

`budget/token_tracker.py` enforces these hard limits:

| Parameter | Value | Effect |
|---|---|---|
| `LOCAL_TOKEN_CAP` | Unlimited | Local models have no cost ceiling |
| `PAID_FREE_RPM_CAP` | 30 requests/min | Groq rate limit — queue excess requests |
| `PAID_PREMIUM_SESSION_CAP` | 50,000 tokens | ~$0.50 max per session for paid APIs |
| `PAID_PREMIUM_MONTHLY_CAP` | 500,000 tokens | ~$5.00 max per month |
| `BUDGET_WARNING_THRESHOLD` | 80% of any cap | Emits `budget_warning` event to War Room |
| `BUDGET_EXHAUSTED_ACTION` | Block PAID_PREMIUM | Falls back to PAID_FREE, never exceeds cap |
