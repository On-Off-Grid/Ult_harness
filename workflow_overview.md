# Bug Bounty Harness — High-Level Workflow & Repo Map

**Purpose:** What each repository provides, how they connect, and where you can visually monitor the hunt.

---

## 1. The Big Picture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        YOU (the operator)                                       │
│                              │                                                  │
│                    ┌─────────▼──────────┐                                       │
│                    │  T3MP3ST War Room  │ ◄── Your primary interface             │
│                    │  http://localhost   │     See everything, approve/reject     │
│                    │      :3333         │     findings, monitor budgets          │
│                    └─────────┬──────────┘                                       │
│                              │ WebSocket + REST                                 │
│                    ┌─────────▼──────────┐                                       │
│                    │   OpAdmiral Brain  │ ◄── Central coordinator                │
│                    │  http://localhost   │     Routes tasks, tracks budget,       │
│                    │      :8001         │     dispatches specialists              │
│                    └──┬──────┬──────┬───┘                                       │
│                       │      │      │                                           │
│          ┌────────────┘      │      └────────────┐                              │
│          ▼                   ▼                    ▼                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐                        │
│  │  16 Specialist│  │   mempalace  │  │  Egress Proxy  │                        │
│  │  Agents       │  │  Memory DB   │  │  (mitmproxy)   │                        │
│  │  (Python)     │  │  :8000       │  │  :8080         │                        │
│  └──────┬───────┘  └──────────────┘  └───────┬────────┘                        │
│         │                                     │                                 │
│         │         ALL outbound traffic ───────┘                                 │
│         │              goes here                                                │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────┐                               │
│  │  External Tools (adhd, claude-bug-bounty,    │                               │
│  │  jsleak, Agent-Reach) + Ollama LLM           │                               │
│  └──────────────────────────────────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Repo-by-Repo Breakdown

### 🧠 `orchestrator/admiral.py` — THE BRAIN

| | |
|---|---|
| **Role** | Central coordinator — receives tasks, dispatches specialists, tracks state |
| **Language** | Python (FastAPI) |
| **Port** | `http://localhost:8001` |
| **Has UI?** | ⚡ **REST API + WebSocket** (consumed by T3MP3ST, not directly by humans) |
| **Provides** | `/api/v1/status`, `/api/v1/findings`, `/api/triage/callback`, `/ws` |
| **Depends on** | Every other component — this is the hub |

**What you'd see if you hit it directly:**
```bash
curl http://localhost:8001/api/v1/status | python3 -m json.tool
# → { "active_specialists": 2, "findings": 5, "budget_used_pct": 23.4, ... }
```

---

### ⚡ `T3MP3ST/` — WAR ROOM UI (Your Primary Dashboard)

| | |
|---|---|
| **Role** | Operator-facing command & control dashboard |
| **Language** | TypeScript/Node + HTML/CSS/JS frontend |
| **Port** | `http://localhost:3333` |
| **Has UI?** | ✅ **YES — Full web dashboard** |
| **Provides** | Real-time hunt visualization, finding approval/rejection, token budget gauge, OOB badges, specialist activity feed, log tailing |
| **Depends on** | `admiral.py` at `:8001` (fetches data via REST, receives live events via WebSocket) |

**What you see in the browser:**

The T3MP3ST War Room is a dark-themed C2 dashboard (hacker-green aesthetic with JetBrains Mono font) that shows:

| Panel | What it displays |
|---|---|
| **Active Scan Status** | Which specialists are running, their current target endpoints |
| **Findings Feed** | Real-time list of discovered vulnerabilities with status badges (🟡 Identified → 🔵 Validating → 🟢 Confirmed → 🔴 False Positive) |
| **Confirm/Reject Modal** | Click a finding → review evidence → approve or mark as FP with reason text |
| **Token Budget Gauge** | Progress bar: `tokens_used / hard_cap` per tier (LOCAL_LIGHT / LOCAL_HEAVY / PAID_FREE / PAID_PREMIUM) |
| **OOB Callback Badges** | Green dot = OOB callback received; yellow = pending; links to Interactsh payload ID |
| **Log Stream** | Tail of structured JSON logs from all components, filterable by specialist |

> **This is your primary window into the harness.** Open `http://localhost:3333` and leave it running throughout the hunt.

---

### 🗄️ `mempalace/` — MEMORY ENGINE

| | |
|---|---|
| **Role** | Long-term memory — stores findings, FP patterns, scope rules, token usage, embeddings |
| **Language** | Python (MCP server + SQLite + ChromaDB) |
| **Port** | `http://localhost:8000` |
| **Has UI?** | 🔶 **CLI only** (no web UI, but queryable via MCP tools or CLI commands) |
| **Provides** | Vector similarity search (ChromaDB), relational queries (SQLite), FP pattern matching, token usage tracking |
| **Depends on** | Nothing — it's a stateless data service |

**How you interact:**
```bash
# CLI queries (after Phase 2 tweaks)
mempalace fp-patterns --category sqli
mempalace token-report --wing acme-corp
mempalace scope-check --url "https://app.target.com" --program acme-corp

# Or via MCP tools from any AI agent (Claude, Cursor, etc.)
```

---

### 🛡️ `compliance/egress_proxy.py` — TRAFFIC COP

| | |
|---|---|
| **Role** | Intercepts ALL outbound HTTP traffic, enforces scope, strips headers, blocks forbidden destinations |
| **Language** | Python (mitmproxy addon) |
| **Port** | `http://localhost:8080` (HTTP proxy) |
| **Has UI?** | ✅ **YES — mitmweb available** on `http://localhost:8081` |
| **Provides** | Scope enforcement, OSINT allowlist, DNS rebinding protection, dry-run logging |
| **Depends on** | `compliance/scope_gate.py` (policy engine), `platform_profile.json` (scope source) |

**Bonus: mitmproxy's built-in web UI:**

You can optionally launch with `mitmweb` instead of `mitmdump` to get a visual traffic inspector:

```bash
# Instead of: mitmdump -s compliance/egress_proxy.py -p 8080
# Use:        mitmweb  -s compliance/egress_proxy.py -p 8080 --web-port 8081
```

This gives you `http://localhost:8081` — a full HTTP traffic inspector showing:
- Every request/response flowing through the proxy
- Which requests were ALLOWED vs BLOCKED (403)
- Request/response headers and bodies
- Timing information

> **Use this during debugging and dry-run mode** to visually confirm that scope enforcement is working correctly.

---

### 🌊 `adhd/` — DIVERGENT IDEATION ENGINE

| | |
|---|---|
| **Role** | Creative brainstorming — generates attack vectors using cognitive frames |
| **Language** | TypeScript/Node (CLI tool) |
| **Port** | None (CLI only) |
| **Has UI?** | 🔶 **Terminal output only** (beautifully formatted ANSI with color-coded scores) |
| **Provides** | Attack vector brainstorming, WAF evasion strategies, payload mutation ideas, scored idea lists |
| **Depends on** | Ollama (for LLM inference), mempalace (for FP anti-pattern lookups) |

**What you see in the terminal:**
```
Problem: Find SSRF in https://api.target.com/proxy?url=
Reframed for divergence: bypass URL validation via protocol confusion

── Wide Set (12 ideas) ──────────────────────
  1. DNS rebinding via attacker domain         [N8 V7 F9]
  2. URL scheme confusion (gopher://)          [N6 V8 F8]
  3. IPv6 bracket bypass [::ffff:127.0.0.1]    [N7 V6 F7]
  ...

── Non-obvious pick ──────────────────────────
  → #7: Cloud metadata via redirect chain     [N9 V6 F8]
    Sketch: POST /proxy?url=http://evil.com/redirect→169.254.169.254
```

---

### 🕵️ `claude-bug-bounty/` — ReAct SCANNING ENGINE

| | |
|---|---|
| **Role** | Autonomous vulnerability scanner using ReAct (Reason+Act) loop |
| **Language** | Python |
| **Port** | None (CLI tool, but has a TUI dashboard) |
| **Has UI?** | 🔶 **TUI Dashboard** (terminal-based live progress tracker) |
| **Provides** | Automated recon + hunt workflow, tool orchestration (subfinder, katana, nuclei, dalfox, etc.), wordlist engines, OSINT scripts |
| **Depends on** | Ollama / ModelRouter (for LLM calls), egress proxy (for HTTP traffic) |

**TUI Dashboard (`tools/dashboard.py`):**
```
╔═══════════════════════════════════════════╗
║  HUNT ─ target.com                        ║
╠═══════════════════════════════════════════╣
║  [✓] Subdomain enum      1,247 subs  12s ║
║  [⠹] Live host probe     ...             ║
║  [ ] URL crawling         pending         ║
║  [ ] Parameter discovery  pending         ║
╠═══════════════════════════════════════════╣
║  Latest: katana https://api.target.com/.. ║
╚═══════════════════════════════════════════╝
```

---

### 🔗 `jsleak/` — JAVASCRIPT SECRET SCANNER

| | |
|---|---|
| **Role** | Scans JavaScript files for leaked secrets, API keys, endpoints |
| **Language** | Go (single binary) |
| **Port** | None |
| **Has UI?** | ❌ **No** — pure CLI, outputs to stdout |
| **Provides** | Secret detection, API endpoint extraction from JS bundles |
| **Depends on** | Egress proxy (reads `HTTP_PROXY` env var after Phase 4 tweak) |

**Usage:**
```bash
cat js_urls.txt | jsleak -s        # find secrets
cat js_urls.txt | jsleak -e        # extract endpoints
cat js_urls.txt | jsleak -l        # find link references
```

---

### 📡 `Agent-Reach/` — OSINT HEALTH DAEMON

| | |
|---|---|
| **Role** | Monitors OSINT channels (Twitter, Reddit, GitHub) for target intelligence |
| **Language** | Python (CLI + MCP server) |
| **Port** | Via MCP stdio (no HTTP port) |
| **Has UI?** | ❌ **No** — CLI output and MCP tool interface |
| **Provides** | Social media monitoring, breach alert tracking, channel health reports |
| **Depends on** | API keys for Twitter/Reddit/GitHub, admiral (posts health events) |

---

### 📚 `Awesome-Redteam/` — STATIC PAYLOAD LIBRARY

| | |
|---|---|
| **Role** | Read-only reference material — payload cheatsheets, OSINT guides, recon tips |
| **Language** | Markdown (static files) |
| **Port** | None |
| **Has UI?** | ❌ **No** — Markdown files, ingested into mempalace by `scripts/ingest_awesome_redteam.py` |
| **Provides** | Curated payloads for SQLi, XSS, SSRF, IDOR, RCE; reconnaissance methodologies |
| **Depends on** | Nothing — consumed by specialists via mempalace search |

---

### 🔐 `CL4R1T4S/` — AI SYSTEM PROMPT ARCHIVE

| | |
|---|---|
| **Role** | Collection of extracted AI system prompts (Anthropic, OpenAI, etc.) |
| **Language** | Text/Markdown (static files) |
| **Port** | None |
| **Has UI?** | ❌ **No** — Markdown files, ingested into mempalace by `scripts/ingest_cl4r1tas.py` |
| **Provides** | Reference prompts for the `ai_jailbreak_specialist` to study and craft bypass attempts |
| **Depends on** | Nothing — consumed by the AI jailbreak specialist via mempalace |

---

### 🤖 `Ollama` — LOCAL LLM INFERENCE SERVER

| | |
|---|---|
| **Role** | Runs local LLM models on your RTX 4050 GPU |
| **Language** | Go (external service) |
| **Port** | `http://localhost:11434` |
| **Has UI?** | 🔶 **API only** (no web dashboard, but many third-party UIs exist) |
| **Provides** | Local inference for `qwen2.5-coder:7b`, `llama3.1:8b`, `qwen2.5-coder:3b`, `mistral:7b` |
| **Depends on** | NVIDIA GPU + drivers |

**Quick status check:**
```bash
curl http://localhost:11434/api/tags | python3 -m json.tool  # list loaded models
```

**Optional web UIs for Ollama** (install separately if desired):
- [Open WebUI](https://github.com/open-webui/open-webui) — `http://localhost:8080` (would conflict with egress proxy; change port)
- [Ollama Web UI](https://github.com/ollama-webui/ollama-webui)

---

## 3. Port Map (All Localhost Services)

```
┌──────────────────────────────────────────────────────────────┐
│                    PORT ALLOCATION MAP                        │
├──────────┬────────────────────────┬──────────────────────────┤
│   Port   │  Service               │  UI Available?           │
├──────────┼────────────────────────┼──────────────────────────┤
│   3333   │  T3MP3ST War Room      │  ✅ Web Dashboard        │
│   8000   │  mempalace MCP/API     │  🔶 CLI only             │
│   8001   │  OpAdmiral Brain       │  ⚡ REST API + WS        │
│   8080   │  Egress Proxy (mitm)   │  ✅ mitmweb on :8081     │
│   8081   │  mitmweb (optional)    │  ✅ Traffic Inspector     │
│  11434   │  Ollama LLM Server     │  🔶 API only             │
├──────────┼────────────────────────┼──────────────────────────┤
│          │  adhd                  │  🔶 Terminal (ANSI TUI)  │
│          │  claude-bug-bounty     │  🔶 Terminal (TUI dash)  │
│          │  jsleak                │  ❌ stdout only          │
│          │  Agent-Reach           │  ❌ MCP/CLI only         │
└──────────┴────────────────────────┴──────────────────────────┘
```

---

## 4. The Hunt — End-to-End Workflow

Here's how a complete hunt flows from start to finish, showing which repo is active at each stage and where you watch progress:

### Stage 1: Initialize (`main.py init`)
```
You run:  python main.py init --platform hackerone --program acme-corp

What happens:
  ┌─ main.py reads platform scope (CSV/JSON from H1/BC download)
  ├─ compliance/scope_importer.py parses scope → TargetScope object
  ├─ compliance/header_injector.py generates platform_profile.json
  └─ workspace/acme-corp/ directory created with all config

Where to look: Terminal output
```

### Stage 2: Boot Services (`main.py run`)
```
You run:  python main.py run --program acme-corp [--dry-run]

What starts (in order):
  1. mitmdump egress proxy            → :8080  (optionally mitmweb → :8081)
  2. mempalace (if not running)       → :8000
  3. OpAdmiral FastAPI                → :8001
  4. SessionManager bootstraps auth tokens
  5. ModelRouter health-checks Ollama → :11434
  6. ScopeGate loaded with parsed rules

Where to look:
  ✅ http://localhost:3333        ← T3MP3ST War Room (open this now)
  ✅ http://localhost:8081        ← mitmweb traffic inspector (optional)
  ⚡ http://localhost:8001/api/v1/status  ← JSON API
```

### Stage 3: Recon & Discovery
```
Active repos:
  ├─ claude-bug-bounty/     → runs subfinder, katana, gospider, param discovery
  ├─ jsleak/                → scans discovered JS files for secrets
  └─ Agent-Reach/           → monitors OSINT channels for target intel

LLM usage:
  └─ qwen2.5-coder:7b (LOCAL) → prioritizes discovered endpoints

Where to look:
  ✅ T3MP3ST War Room       ← live endpoint discovery feed
  🔶 Terminal               ← claude-bug-bounty TUI dashboard
  ✅ mitmweb :8081           ← watch outbound recon traffic
```

### Stage 4: Attack Planning
```
Active repos:
  └─ adhd/                  → divergent brainstorming per endpoint

LLM usage:
  ├─ llama3.1:8b (LOCAL)    → frame-specific ideation
  └─ Groq 70b (PAID_FREE)  → deep WAF evasion / complex planning

Where to look:
  🔶 Terminal               ← adhd ANSI-formatted idea output
  ✅ T3MP3ST War Room       ← planned attack vectors listed
```

### Stage 5: Scanning & Fuzzing
```
Active repos:
  ├─ agents/specialists/*   → 16 specialist agents craft + send payloads
  ├─ compliance/egress_proxy → enforces scope on every outbound request
  └─ budget/model_router     → routes LLM calls to cheapest capable model

LLM usage:
  ├─ qwen2.5-coder:7b (LOCAL)   → payload crafting (high volume)
  ├─ qwen2.5-coder:3b (LOCAL)   → response classification (highest volume)
  └─ mistral:7b (LOCAL)         → adaptive payload selection

Where to look:
  ✅ T3MP3ST War Room       ← live specialist activity, finding count
  ✅ mitmweb :8081           ← watch actual requests to target
  ⚡ :8001/api/v1/status    ← active specialist count, budget %
```

### Stage 6: Validation & Triage
```
Active repos:
  ├─ triage/noise_filter    → drops non-bountiable findings
  ├─ triage/state_machine   → transitions: IDENTIFIED → VALIDATING → CONFIRMED
  ├─ sessions/session_manager → provides 4-session matrix for IDOR/BAC
  └─ compliance/oob_engine  → polls Interactsh for OOB callbacks

LLM usage:
  └─ Groq 70b (PAID_FREE)  → confirmation reasoning, IDOR matrix analysis

Where to look:
  ✅ T3MP3ST War Room       ← findings change status in real-time
                               🟡 Identified → 🔵 Validating → 🟢 Confirmed
                               OOB badges light up on callback receipt
```

### Stage 7: Operator Review (YOU)
```
In T3MP3ST War Room (:3333):
  ├─ Review confirmed findings
  ├─ Click finding → see evidence (request/response, screenshots, OOB proof)
  ├─ Click [✅ Confirm] → moves to report generation
  └─ Click [❌ Reject] → enter FP reason → archived for mempalace learning

This is the human-in-the-loop checkpoint.
No report is generated without your explicit approval.
```

### Stage 8: Report Generation
```
Active repos:
  ├─ reporting/taxonomy     → maps to VRT, CWE, CVSS 3.1
  └─ orchestrator/admiral   → generates + polishes report

LLM usage:
  ├─ llama3.1:8b (LOCAL)     → VRT/CWE classification, template formatting
  ├─ Groq 70b (PAID_FREE)   → CVSS justification, report draft
  └─ GPT-4o (PAID_PREMIUM)  → final polish (only task using paid API)

Output:
  └─ workspace/acme-corp/reports/finding_001.md  ← platform-ready Markdown

Where to look:
  ✅ T3MP3ST War Room        ← rendered report preview
  📂 workspace/acme-corp/    ← report files on disk
```

---

## 5. What to Open During a Hunt

| Window | URL / Command | Purpose | Priority |
|---|---|---|---|
| **Browser Tab 1** | `http://localhost:3333` | T3MP3ST War Room — your main dashboard | 🔴 **Essential** |
| **Browser Tab 2** | `http://localhost:8081` | mitmweb traffic inspector (optional) | 🟡 Useful for debugging |
| **Terminal 1** | `python main.py run --program acme-corp` | Main harness process | 🔴 **Essential** |
| **Terminal 2** | `ollama serve` (if not running as service) | Local LLM server | 🔴 **Essential** |
| **Terminal 3** | `tail -f workspace/acme-corp/logs/*.jsonl \| jq .` | Raw log stream | 🟢 Optional |

---

## 6. Data Flow Summary

```
                    ┌──────────────┐
                    │  Target App  │
                    └──────┬───────┘
                           │ HTTPS
                    ┌──────▼───────┐
                    │ Egress Proxy │ ← Scope check every request
                    │    :8080     │
                    └──────┬───────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
   ┌────────▼───────┐ ┌───▼────┐ ┌───────▼────────┐
   │ 16 Specialists │ │ jsleak │ │ claude-bug-     │
   │ (Python)       │ │ (Go)   │ │ bounty (Python) │
   └────────┬───────┘ └───┬────┘ └───────┬────────┘
            │              │              │
            └──────────────┼──────────────┘
                           │ Findings
                    ┌──────▼───────┐
                    │  OpAdmiral   │ ← Triage, budget, dispatch
                    │    :8001     │
                    └──┬───────┬───┘
                       │       │
              ┌────────▼──┐ ┌──▼─────────┐
              │ mempalace │ │  T3MP3ST   │ ← You watch here
              │   :8000   │ │   :3333    │
              └───────────┘ └────────────┘
                       │
              ┌────────▼──────┐
              │ Ollama / Groq │ ← LLM inference
              │   :11434      │
              └───────────────┘
```
