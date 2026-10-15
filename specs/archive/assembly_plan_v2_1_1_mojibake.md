# Bug Bounty Harness â€” Assembly Plan & Technical Specification v2.1.1

**Version:** 2.1.1 (Planning Mode â€” All Reassessment Fixes Applied)  
**Author:** Senior Cybersecurity Architect & AI Systems Engineer  
**Target Workspace:** `/home/souhail/Desktop/Desktop/Ult_harness`  
**Target Platforms:** HackerOne, Bugcrowd, YesWeHack, Intigriti, Immunefi  
**Reassessment Applied:** All P0â€“P3 items from [`harness_v2_1_reassessment.md`](file:///home/souhail/.gemini/antigravity-cli/brain/fc58faf8-c2cc-4fa7-b4b8-1165b7bf6be3/harness_v2_1_reassessment.md) resolved.

---

## 1. Executive & Architectural Decisions

### 1.1 Python / TypeScript Boundary Resolution
- **Single Orchestration Brain**: Python [`orchestrator/admiral.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/orchestrator/admiral.py) runs as the central async event loop and decision coordinator. **Runs on port `8001`.**
- **T3MP3ST UI / Execution Client**: `T3MP3ST` (TypeScript/Node) runs as a UI presentation layer and command client on port `3333`, communicating with Python `OpAdmiral` via HTTP REST and a **single client-initiated WebSocket**.
- **mempalace Memory Server**: Retains its existing port `8000`. OpAdmiral queries it as a downstream service.

#### Cross-Language Transport Matrix (endpoint ownership annotated)

> **[Fix A-1]** Port collision resolved: admiral = `8001`, mempalace = `8000`.  
> **[Fix A-2]** Single WebSocket connection: T3MP3ST initiates â†’ admiral pushes events back over the same connection.

| Transport | Client (caller) | Server (endpoint owner) | Endpoint | Protocol |
| :--- | :--- | :--- | :--- | :--- |
| **adhd â†’ TokenTracker** | `adhd/src/llm.ts` (HTTP client added in TWEAK) | `orchestrator/admiral.py` (FastAPI) | `POST http://127.0.0.1:8001/api/tokens/record` | HTTP REST |
| **adhd â†’ mempalace FP** | `adhd/src/engine.ts` (HTTP client added in TWEAK) | `mempalace/mempalace/mcp_server.py` | `POST http://127.0.0.1:8000/search` or MCP stdio `search_entries` | HTTP REST or MCP stdio |
| **claude-bug-bounty â†’ Triage** | `claude-bug-bounty/engine.py` (HTTP client) | `orchestrator/admiral.py` (FastAPI) | `POST http://127.0.0.1:8001/api/triage/callback` | HTTP REST |
| **T3MP3ST â†” OpAdmiral** | `T3MP3ST/src/server.ts` (initiates WS + fetch) | `orchestrator/admiral.py` (FastAPI + WS) | `GET/POST http://127.0.0.1:8001/api/v1/*`, `ws://127.0.0.1:8001/ws` | HTTP REST + WebSocket (bidirectional over single conn) |

### 1.2 Single Egress Enforcement Point (`compliance/egress_proxy.py`)
- **mitmproxy Egress Proxy**: All outbound target-directed requests (Go fuzzers, `jsleak -k`, Playwright browsers, `nuclei`, `dalfox`, Python scripts) route through a mitmproxy daemon running on `127.0.0.1:8080` via standard `HTTP_PROXY` / `HTTPS_PROXY` environment variables.
- **Process Lifecycle**: `compliance/egress_proxy.py` is launched as a **standalone child process** by `main.py` during harness bootstrap. It runs as a separate `mitmdump` daemon process (not embedded inside the Python async event loop) to avoid blocking the orchestrator. `main.py` spawns it via `subprocess.Popen(["mitmdump", "-s", "compliance/egress_proxy.py", "-p", "8080", "--set", "block_global=false"])`, manages its PID, and terminates it during harness shutdown.
- **ScopeGate Policy Engine**: `compliance/scope_gate.py` runs inside `egress_proxy.py` as the HTTP flow filter (`request(flow)` hook). Out-of-scope requests are dropped with `HTTP 403 Forbidden` before reaching external networks.

#### OSINT Exemption (Fix A-3: defense-in-depth)

> **Primary gate: destination domain allowlist.** If the request destination matches the configurable OSINT allowlist (`api.twitter.com`, `oauth.reddit.com`, `api.github.com`, `www.googleapis.com`, etc.), it is allowed regardless of any header.  
> **Secondary signal: `X-Harness-Traffic: osint` header.** If the destination is NOT in the OSINT allowlist but the header IS present, the request is **dropped and a security warning is logged** (prevents abuse of the header to bypass scope for arbitrary domains).  
> **Header stripping**: The `X-Harness-Traffic` header is always stripped from outbound requests before forwarding, so target servers never see it.

- **Passive vs. Active Browser Resources**: Playwright sub-resources (fonts, analytics, CDNs) are classified by known CDN domain allowlist (`fonts.googleapis.com`, `cdn.jsdelivr.net`, etc.) and logged as passive without dropping.

### 1.3 Out-of-Band (OOB) Deployment Modes
- **`INTERACTSH_MODE=public` (Default)**: Uses public Interactsh servers (`oast.me`, `oast.fun`).
- **`INTERACTSH_MODE=selfhosted`**: Requires a registered domain and authoritative DNS NS delegation.

### 1.4 Single Source of Truth for Headers & Rate Limits
- `<workspace>/platform_profile.json` is generated at scan initialization by `main.py init`.
- Go tools (`jsleak`) receive headers via `HARNESS_HEADERS_FILE` env var pointing to the generated file.
- **[Fix F-5]** The file is generated into the per-scan workspace directory (e.g., `./workspace/acme/platform_profile.json`), not a repo-level `config/` directory.

#### `platform_profile.json` Schema (Fix M-3)

```json
{
  "platform": "hackerone",
  "program_handle": "acme-corp",
  "researcher_username": "myhacker",
  "headers": {
    "X-BugBounty-HackerOne": "myhacker",
    "User-Agent": "Mozilla/5.0 (BugBounty; HackerOne/myhacker)"
  },
  "rate_limit_rps": 10.0,
  "max_concurrent_requests": 5,
  "auth": {
    "user_a": { "login_url": "https://acme.com/api/login", "payload": {"email": "a@test.com", "password": "..."} },
    "user_b": { "login_url": "https://acme.com/api/login", "payload": {"email": "b@test.com", "password": "..."} },
    "admin":  { "login_url": "https://acme.com/api/login", "payload": {"email": "admin@test.com", "password": "..."} }
  }
}
```

### 1.5 UI Consolidation
- **Tweak `T3MP3ST` UI**: Add operator confirm/reject modals, FP reason capture dialogs, OOB badges, and real-time token budget gauges.

### 1.6 Dry-Run / Safe Test Mode
- **`--dry-run` Flag**: Supported across CLI (`main.py`) and `EgressProxy`.
- In `--dry-run` mode, `EgressProxy` passes requests through `ScopeGate`, logs `[DRY-RUN WOULD ALLOW]` or `[DRY-RUN WOULD DROP]`, and returns mock responses without transmitting any packets externally.

### 1.7 Ollama Graceful Degradation (Fix A-4)
- On startup, `budget/model_router.py` performs a health check against `OLLAMA_URL` (`GET /api/tags`).
- If Ollama is unreachable or returns zero models, `ModelRouter` automatically promotes all `LOCAL` tier tasks to `PAID_FREE` tier (Groq `llama3-70b`) and emits a `[WARN] Ollama unavailable â€” all LOCAL tasks routed to PAID_FREE tier` log entry.
- If `PAID_FREE` tier is also unreachable (no Groq API key), harness refuses to start and prints a clear error: `"No model backend available. Configure Ollama or set GROQ_API_KEY."`.

### 1.8 Logging & Observability (Fix M-4)
- **Format**: All components emit structured JSON Lines to `./workspace/<wing_id>/logs/<component>.jsonl`.
- **Schema**: Each log entry includes `{"ts": "ISO8601", "component": "sqli_specialist", "correlation_id": "task_abc123", "level": "INFO|WARN|ERROR", "msg": "...", "data": {...}}`.
- **Correlation**: Every `Task` object carries a `correlation_id` propagated across HTTP transports (via `X-Correlation-ID` header) and WebSocket events.
- **War Room Tailing**: T3MP3ST War Room UI tails logs via the existing WebSocket connection, receiving real-time `log_event` push messages from OpAdmiral.

---

## 2. Deprecation & Superseded Items Matrix (v2.0 â†’ v2.1.1)

| Feature / Module | Status in v2.0 | Status in v2.1.1 | Rationale |
| :--- | :--- | :--- | :--- |

| **TS OpAdmiral Orchestration** | Direct TS brain | âŒ **SUPERSEDED** | Python `orchestrator/admiral.py` is the single brain on port `8001`. |
| **In-Process Python Scope Gate** | Python wrapping | âŒ **SUPERSEDED** | Replaced by mitmproxy `egress_proxy.py` on `127.0.0.1:8080`. |
| **Triple Header Injector** | Separate Python/Go/TS | âŒ **SUPERSEDED** | Single source: `platform_profile.json` + `HARNESS_HEADERS_FILE`. |
| **Local-only OOB Requirement** | Self-hosted mandatory | âŒ **REVISED** | `INTERACTSH_MODE=public` default. |
| **`claude-bug-bounty` Report Format** | Generic template | âŒ **SUPERSEDED** | Delegated to `reporting/taxonomy.py`. |
| **`claude-bug-bounty/tools/scope_checker.py`** | Active scope checker | âŒ **DEPRECATED** | Superseded by `compliance/scope_gate.py` via egress proxy. |
| **Dual WebSocket (v2.1)** | Two WS in opposite dirs | âŒ **SUPERSEDED** | Single client-initiated WS from T3MP3ST â†’ OpAdmiral. |

---

## 3. Complete Workspace File Structure & Classification

```
Ult_harness/
â”œâ”€â”€ core/                                    ðŸ”´ NEW: Base types, configuration, event bus
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ types.py                             (TargetScope, ScopeRule, PlatformHeaders, MultiSessionContext,
â”‚   â”‚                                         VulnCategory, VulnStatus, TokenBudget, Task, OrchestrationEvent)
â”‚   â”œâ”€â”€ config.py                            (Global YAML/env config loader, dry-run flag, Ollama fallback)
â”‚   â””â”€â”€ event_bus.py                         (IEventBus: async publish/subscribe in-memory topic bus)
â”œâ”€â”€ compliance/                              ðŸ”´ NEW: Layer 0 Platform Compliance & Egress Proxy
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ scope_gate.py                        (Policy engine: IP/CIDR, Wildcards, Regex, DNS Rebinding,
â”‚   â”‚                                         OSINT domain allowlist)
â”‚   â”œâ”€â”€ egress_proxy.py                      (mitmproxy addon script; spawned as standalone mitmdump
â”‚   â”‚                                         child process by main.py; dry-run support)
â”‚   â”œâ”€â”€ header_injector.py                   (Reads platform_profile.json; generates HARNESS_HEADERS_FILE)
â”‚   â”œâ”€â”€ scope_importer.py                    (Parsers: HackerOne CSV, Bugcrowd JSON, Intigriti, YesWeHack)
â”‚   â””â”€â”€ oob_engine.py                       (Interactsh client: public oast.me vs self-hosted modes)
â”œâ”€â”€ budget/                                  ðŸ”´ NEW: Cost Control & Token Tracking
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ token_tracker.py                     (Per-Agent & Per-Task usage, cost logging, hard caps)
â”‚   â””â”€â”€ model_router.py                     (Local Ollama â†” Paid routing + Ollama health check fallback)
â”œâ”€â”€ triage/                                  ðŸ”´ NEW: State Machine & Noise Filter
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ noise_filter.py                      (Pre-triage: drops SPF, security headers, self-XSS, etc.)
â”‚   â””â”€â”€ state_machine.py                    (IDENTIFIED â†’ VALIDATING â†’ CONFIRMED / FALSE_POSITIVE)
â”œâ”€â”€ reporting/                               ðŸ”´ NEW: Taxonomy & Platform Formatters
â”‚   â”œâ”€â”€ __init__.py
â”‚   â””â”€â”€ taxonomy.py                          (VRT, CWE, CVSS 3.1/4.0, H1/BC/YWH/Intigriti templates)
â”œâ”€â”€ sessions/                                ðŸ”´ NEW: Multi-Session Authenticator
â”‚   â”œâ”€â”€ __init__.py
â”‚   â””â”€â”€ session_manager.py                  (User A/B/admin bootstrap + background token refresh loop)
â”œâ”€â”€ agents/                                  ðŸ”´ NEW: Python Specialist Swarm (16 Agents)
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ specialist_base.py                   (Base ISpecialist: mempalace cache, token tracking, OOB mixin)
â”‚   â”œâ”€â”€ dual_session_tester.py               (4-Session matrix tester for IDOR & BAC)
â”‚   â””â”€â”€ specialists/
â”‚       â”œâ”€â”€ sqli_specialist.py
â”‚       â”œâ”€â”€ xss_specialist.py
â”‚       â”œâ”€â”€ ssrf_specialist.py               (with OOB mixin)
â”‚       â”œâ”€â”€ idor_specialist.py               (with dual-session matrix)
â”‚       â”œâ”€â”€ lfi_specialist.py
â”‚       â”œâ”€â”€ rce_specialist.py                (with OOB mixin)
â”‚       â”œâ”€â”€ xxe_specialist.py                (with OOB mixin)
â”‚       â”œâ”€â”€ jwt_specialist.py
â”‚       â”œâ”€â”€ open_redirect_specialist.py
â”‚       â”œâ”€â”€ prototype_pollution_specialist.py
â”‚       â”œâ”€â”€ csti_specialist.py
â”‚       â”œâ”€â”€ mass_assignment_specialist.py
â”‚       â”œâ”€â”€ header_injection_specialist.py
â”‚       â”œâ”€â”€ bac_specialist.py                (with dual-session matrix)
â”‚       â”œâ”€â”€ ai_jailbreak_specialist.py       (with CL4R1T4S templates)
â”‚       â””â”€â”€ business_logic_specialist.py
â”œâ”€â”€ orchestrator/                            ðŸ”´ NEW: Central Orchestrator (port 8001)
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ admiral.py                           (Python OpAdmiral central brain; FastAPI on port 8001;
â”‚   â”‚                                         owns /api/tokens/record, /api/triage/callback,
â”‚   â”‚                                         /api/v1/*, ws://â€¦:8001/ws)
â”‚   â””â”€â”€ cli_tunnel.py                       (Keyless local CLI session interceptor)
â”œâ”€â”€ tests/                                   ðŸ”´ NEW: Test Harness & Validation
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ test_scope_gate.py                   (DNS rebinding, CIDR, IPv6, ws:// scheme unit tests)
â”‚   â”œâ”€â”€ test_osint_exemption.py              (OSINT domain allowlist + header abuse prevention)
â”‚   â”œâ”€â”€ test_taxonomy.py                     (Golden report output verification)
â”‚   â””â”€â”€ test_mock_e2e.py                     (Juice Shop E2E & Dry-Run verification)
â”œâ”€â”€ scripts/                                 ðŸ”´ NEW: Workspace Utilities & Ingestion
â”‚   â”œâ”€â”€ ingest_awesome_redteam.py            (Loads payloads into mempalace)
â”‚   â””â”€â”€ ingest_cl4r1tas.py                   (Loads prompts into mempalace)
â”œâ”€â”€ pyproject.toml                           ðŸ”´ NEW: Root Python Package (control-plane only)
â”œâ”€â”€ main.py                                  ðŸ”´ NEW: Harness Bootstrap, init, & Entry Point
â”‚
â”œâ”€â”€ Agent-Reach/                             ðŸŸ¡ MODIFIED: OSINT Health Daemon
â”‚   â”œâ”€â”€ agent_reach/core.py                  ðŸŸ¡ TWEAK: Post health events to OpAdmiral (port 8001)
â”‚   â”œâ”€â”€ agent_reach/doctor.py                ðŸŸ¡ TWEAK: Export JSON channel health report
â”‚   â”œâ”€â”€ agent_reach/integrations/mcp_server.py ðŸŸ¡ TWEAK: Add trigger_osint_search endpoint
â”‚   â””â”€â”€ (All channels & backends)            ðŸŸ¢ KEEP: twitter.py, reddit.py, github.py, opencli.py
â”‚
â”œâ”€â”€ Awesome-Redteam/                         ðŸŸ¢ KEEP ALL: Static Playbooks & Payload Cheatsheets
â”‚   â”œâ”€â”€ cheatsheets/*                        ðŸŸ¢ KEEP: sqli.md, xss.md, ssrf.md, idor.md, rce.md, etc.
â”‚   â””â”€â”€ tips/*, scripts/*                    ðŸŸ¢ KEEP: OSINT tips and reconnaissance guides
â”‚
â”œâ”€â”€ BugTraceAI/                              âŒ REMOVED: Entire directory removed from workspace
â”‚
â”œâ”€â”€ CL4R1T4S/                                ðŸŸ¢ KEEP ALL: System Prompts & Safety Rules
â”‚   â”œâ”€â”€ ANTHROPIC/*, OPENAI/*, etc.          ðŸŸ¢ KEEP: All extracted system prompt files
â”‚   â””â”€â”€ README.md, LICENSE                   ðŸŸ¢ KEEP
â”‚
â”œâ”€â”€ T3MP3ST/                                 ðŸŸ¡ MODIFIED: War Room UI & Code Auditor
â”‚   â”œâ”€â”€ src/server.ts                        ðŸŸ¡ TWEAK: Add confirm/reject endpoints, token budget
â”‚   â”‚                                              REST APIs, WS event push for logs
â”‚   â”œâ”€â”€ docs/index.html                      ðŸŸ¡ TWEAK: Add budget gauge & OOB badges to War Room UI
â”‚   â”œâ”€â”€ src/recon/whitebox.ts                ðŸŸ¢ KEEP: web-tree-sitter AST code reviewer
â”‚   â””â”€â”€ src/arsenal/*                        ðŸŸ¢ KEEP: Command execution & approval gates
â”‚
â”œâ”€â”€ adhd/                                    ðŸŸ¡ MODIFIED: Divergent Ideation Engine
â”‚   â”œâ”€â”€ src/frames.ts                        ðŸŸ¡ TWEAK: Add 6 security frames + token usage HTTP
â”‚   â”‚                                              callback to POST :8001/api/tokens/record
â”‚   â”œâ”€â”€ src/engine.ts                        ðŸŸ¡ TWEAK: Query mempalace FP anti-patterns before
â”‚   â”‚                                              returning final strategy (was critic.ts â€” FIX F-1)
â”‚   â””â”€â”€ src/index.ts, llm.ts, render.ts,     ðŸŸ¢ KEEP: Core ideation execution pipeline
â”‚       types.ts, cli.ts
â”‚
â”œâ”€â”€ claude-bug-bounty/                       ðŸŸ¡ MODIFIED: ReAct Engine & CLI Runner
â”‚   â”œâ”€â”€ agent.py                             ðŸŸ¡ TWEAK: Route LLM calls to ModelRouter (port 8001)
â”‚   â”œâ”€â”€ engine.py                            ðŸŸ¡ TWEAK: Set HTTP_PROXY env to route via egress proxy
â”‚   â”œâ”€â”€ brain.py                             ðŸŸ¡ TWEAK: Bind prompt builder with CL4R1T4S templates
â”‚   â”œâ”€â”€ memory/audit_log.py                  ðŸŸ¡ TWEAK: Redirect storage to mempalace backend
â”‚   â”œâ”€â”€ memory/pattern_db.py                 ðŸŸ¡ TWEAK: Redirect pattern queries to mempalace
â”‚   â”œâ”€â”€ memory/rotation.py                   ðŸŸ¡ TWEAK: Wire rotation into mempalace sweeper
â”‚   â”œâ”€â”€ memory/schemas.py                    ðŸŸ¢ KEEP: Schema definitions (referenced by tweaked modules)
â”‚   â”œâ”€â”€ tools/scope_checker.py               âŒ DEPRECATED: Superseded by compliance/scope_gate.py
â”‚   â”œâ”€â”€ tools/auth_session.py                ðŸŸ¡ TWEAK: Wire into sessions/session_manager.py
â”‚   â”œâ”€â”€ tools/credential_store.py            ðŸŸ¡ TWEAK: Migrate credentials to mempalace encrypted room
â”‚   â”œâ”€â”€ tools/param_discovery.sh             ðŸŸ¢ KEEP
â”‚   â”œâ”€â”€ tools/zendesk_idor_test.py           ðŸŸ¢ KEEP
â”‚   â”œâ”€â”€ tools/multipart_mutator.py           ðŸŸ¢ KEEP
â”‚   â”œâ”€â”€ tools/wordlist_engine.sh             ðŸŸ¢ KEEP
â”‚   â”œâ”€â”€ tools/external_arsenal.sh            ðŸŸ¢ KEEP
â”‚   â”œâ”€â”€ tools/osint_employees.sh             ðŸŸ¢ KEEP
â”‚   â”œâ”€â”€ tools/(all other tools)              ðŸŸ¢ KEEP: hunt.py, intel_engine.py, waf_encoder.py, etc.
â”‚   â”œâ”€â”€ wordlists/*                          ðŸŸ¢ KEEP: Static wordlists
â”‚   â”œâ”€â”€ rules/*                              ðŸŸ¢ KEEP: Hunting & reporting rules
â”‚   â”œâ”€â”€ skills/*                             ðŸŸ¢ KEEP: Skill definitions
â”‚   â”œâ”€â”€ web3/*                               ðŸŸ¢ KEEP: Web3/Solidity audit guides
â”‚   â”œâ”€â”€ scripts/*                            ðŸŸ¢ KEEP: dork_runner.py, full_hunt.sh
â”‚   â””â”€â”€ tests/*                              ðŸŸ¢ KEEP: Existing test suite
â”‚
â”œâ”€â”€ jsleak/                                  ðŸŸ¡ MODIFIED: Go Secret Scanner
â”‚   â”œâ”€â”€ main.go                              ðŸŸ¡ TWEAK: Add -json output & read HTTP_PROXY env var
â”‚   â”‚                                              (NOTE: no go.mod exists â€” `go mod init` needed
â”‚   â”‚                                               if adding dependencies for -headers-file flag)
â”‚   â””â”€â”€ README.md                            ðŸŸ¢ KEEP
â”‚
â””â”€â”€ mempalace/                               ðŸŸ¡ MODIFIED: Memory Engine (retains port 8000)
    â”œâ”€â”€ mempalace/backends/sqlite_exact.py   ðŸŸ¡ TWEAK: Add v2.0 tables (scopes, oob, taxonomy,
    â”‚                                              dual_session_tests, token_usage, noise_filter_log)
    â”œâ”€â”€ mempalace/mcp_server.py              ðŸŸ¡ TWEAK: Expose FP pattern queries, token log writes
    â”œâ”€â”€ mempalace/cli.py                     ðŸŸ¡ TWEAK: Add CLI commands for harness-specific queries
    â””â”€â”€ mempalace/backends/chroma.py         ðŸŸ¢ KEEP: ChromaDB vector connector
```

---

## 4. Class & Interface Specifications for WRITE Modules

### 4.0 `core/types.py` (Fix M-1 â€” previously unspecified)

```python
# core/types.py
"""Central type definitions imported by every harness module."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime


class Platform(str, Enum):
    HACKERONE = "hackerone"
    BUGCROWD = "bugcrowd"
    YESWEHACK = "yeswehack"
    INTIGRITI = "intigriti"
    IMMUNEFI = "immunefi"


class ScopeMatchType(str, Enum):
    EXACT = "exact"           # app.example.com
    WILDCARD = "wildcard"     # *.example.com
    CIDR = "cidr"             # 10.0.0.0/8
    REGEX = "regex"           # ^api\d+\.example\.com$


class VulnCategory(str, Enum):
    SQLI = "sqli"
    XSS = "xss"
    SSRF = "ssrf"
    IDOR = "idor"
    LFI = "lfi"
    RCE = "rce"
    XXE = "xxe"
    JWT = "jwt"
    OPEN_REDIRECT = "open_redirect"
    PROTOTYPE_POLLUTION = "prototype_pollution"
    CSTI = "csti"
    MASS_ASSIGNMENT = "mass_assignment"
    HEADER_INJECTION = "header_injection"
    BAC = "bac"
    AI_JAILBREAK = "ai_jailbreak"
    BUSINESS_LOGIC = "business_logic"


class VulnStatus(str, Enum):
    IDENTIFIED = "identified"
    VALIDATING = "validating"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    CHAINED = "chained"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass
class ScopeRule:
    pattern: str
    match_type: ScopeMatchType
    description: str = ""


@dataclass
class TargetScope:
    program_handle: str
    platform: Platform
    in_scope: List[ScopeRule] = field(default_factory=list)
    out_of_scope: List[ScopeRule] = field(default_factory=list)
    rate_limit_rps: float = 10.0
    max_concurrent: int = 5


@dataclass
class PlatformHeaders:
    headers: Dict[str, str] = field(default_factory=dict)
    user_agent: str = ""

    @classmethod
    def for_platform(cls, platform: Platform, username: str) -> "PlatformHeaders":
        header_map = {
            Platform.HACKERONE:  {"X-BugBounty-HackerOne": username},
            Platform.BUGCROWD:  {"X-Bugcrowd-Researcher": username},
            Platform.YESWEHACK: {"X-YesWeHack-User": username},
            Platform.INTIGRITI: {"X-Intigriti-Researcher": username},
            Platform.IMMUNEFI:  {"X-Immunefi-Researcher": username},
        }
        return cls(
            headers=header_map.get(platform, {}),
            user_agent=f"Mozilla/5.0 (BugBounty; {platform.value}/{username})"
        )


@dataclass
class MultiSessionContext:
    user_a_headers: Dict[str, str] = field(default_factory=dict)
    user_b_headers: Dict[str, str] = field(default_factory=dict)
    admin_headers: Dict[str, str] = field(default_factory=dict)
    unauth_headers: Dict[str, str] = field(default_factory=dict)
    session_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenBudget:
    warning_threshold: int = 50_000
    hard_cap: int = 100_000
    tokens_used: int = 0
    cost_usd: float = 0.0

    @property
    def remaining(self) -> int:
        return max(0, self.hard_cap - self.tokens_used)

    @property
    def is_exhausted(self) -> bool:
        return self.tokens_used >= self.hard_cap


@dataclass
class Task:
    task_id: str
    wing_id: str
    specialist_id: str
    correlation_id: str
    target_endpoint: str
    vuln_category: VulnCategory
    status: VulnStatus = VulnStatus.IDENTIFIED
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestrationEvent:
    event_type: str           # e.g. "validation_started", "finding_confirmed", "budget_warning"
    correlation_id: str
    source_component: str     # e.g. "sqli_specialist", "triage_controller"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    payload: Dict[str, Any] = field(default_factory=dict)
```

### 4.1 `core/event_bus.py` (Fix M-2 â€” previously unspecified)

```python
# core/event_bus.py
"""Async in-memory publish/subscribe event bus for cross-component coordination."""

import asyncio
import uuid
from typing import Callable, Dict, List, Awaitable
from core.types import OrchestrationEvent


class IEventBus:
    """Interface contract for the harness event bus."""

    async def publish(self, topic: str, event: OrchestrationEvent) -> None:
        """Publish an event to all subscribers of the given topic."""
        raise NotImplementedError

    def subscribe(self, topic: str, callback: Callable[[OrchestrationEvent], Awaitable[None]]) -> str:
        """Subscribe to a topic. Returns a subscription_id for later unsubscribe."""
        raise NotImplementedError

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription by its ID."""
        raise NotImplementedError


class InMemoryEventBus(IEventBus):
    """Production implementation: async in-memory topic event bus."""

    def __init__(self):
        self._subscriptions: Dict[str, Dict[str, Callable]] = {}  # topic -> {sub_id -> callback}

    async def publish(self, topic: str, event: OrchestrationEvent) -> None:
        callbacks = self._subscriptions.get(topic, {})
        tasks = [callback(event) for callback in callbacks.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def subscribe(self, topic: str, callback: Callable[[OrchestrationEvent], Awaitable[None]]) -> str:
        if topic not in self._subscriptions:
            self._subscriptions[topic] = {}
        sub_id = f"sub_{uuid.uuid4().hex[:12]}"
        self._subscriptions[topic][sub_id] = callback
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        for topic_subs in self._subscriptions.values():
            topic_subs.pop(subscription_id, None)
```

### 4.2 `core/config.py`

```python
# core/config.py
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class HarnessConfig:
    dry_run: bool = False
    interactsh_mode: str = "public"       # "public" | "selfhosted"
    interactsh_url: str = "https://interactsh.com"
    egress_proxy_port: int = 8080
    war_room_port: int = 3333
    api_port: int = 8001                  # FIX A-1: admiral on 8001, not 8000
    mempalace_url: str = "http://127.0.0.1:8000"
    ollama_url: str = "http://127.0.0.1:11434"
    groq_api_key: Optional[str] = None
    max_session_cost_usd: float = 10.00
    workspace_dir: str = "./workspace"

    @classmethod
    def load_from_env(cls) -> "HarnessConfig":
        return cls(
            dry_run=os.getenv("HARNESS_DRY_RUN", "false").lower() == "true",
            interactsh_mode=os.getenv("INTERACTSH_MODE", "public"),
            interactsh_url=os.getenv("INTERACTSH_URL", "https://interactsh.com"),
            egress_proxy_port=int(os.getenv("EGRESS_PROXY_PORT", "8080")),
            war_room_port=int(os.getenv("WAR_ROOM_PORT", "3333")),
            api_port=int(os.getenv("HARNESS_API_PORT", "8001")),
            groq_api_key=os.getenv("GROQ_API_KEY"),
            workspace_dir=os.getenv("HARNESS_WORKSPACE", "./workspace"),
        )
```

### 4.3 `pyproject.toml` â€” Python Control-Plane Only

> **Monorepo Boundary Note**: This workspace is a **polyglot monorepo** containing Python (control-plane), TypeScript/Node (`T3MP3ST/`, `adhd/`), and Go (`jsleak/`). `pyproject.toml` manages **only the Python control-plane packages**. TypeScript projects retain their own `package.json`. Go files are built independently. Sub-folder Python projects (`mempalace/`, `Agent-Reach/`, `claude-bug-bounty/`) keep their own independent `pyproject.toml`.
>
> **[Fix F-2]**: `jsleak/` has no `go.mod`. It is a single-file Go program (`main.go`). If TWEAK requires adding Go dependencies, `go mod init` must be run during Phase 4.

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ult_harness"
version = "2.1.1"
description = "Python control-plane for the Autonomous Bug Bounty Harness"
authors = [{ name = "Security Architect" }]
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.100.0",
    "uvicorn>=0.22.0",
    "pydantic>=2.0",
    "requests>=2.31.0",
    "aiohttp>=3.8.0",
    "mitmproxy>=10.0.0",
    "chromadb>=0.4.0",
    "pyyaml>=6.0",
    "cvss>=2.6",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["core*", "compliance*", "budget*", "triage*", "reporting*", "sessions*", "agents*", "orchestrator*"]
```

### 4.4 `compliance/scope_importer.py`

```python
# compliance/scope_importer.py
import csv
import json
from typing import List
from core.types import TargetScope, ScopeRule, ScopeMatchType, Platform

class ScopeImporter:
    """Parses platform-specific scope export files into unified TargetScope."""

    @staticmethod
    def parse_hackerone_csv(file_path: str, program_handle: str) -> TargetScope:
        in_scope, out_of_scope = [], []
        with open(file_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                identifier = row.get("asset_identifier", "").strip()
                asset_type = row.get("asset_type", "").strip()
                eligible = row.get("eligible_for_bounty", "true").lower() == "true"
                match_type = ScopeMatchType.WILDCARD if "*." in identifier else ScopeMatchType.EXACT
                rule = ScopeRule(pattern=identifier, match_type=match_type, description=asset_type)
                (in_scope if eligible else out_of_scope).append(rule)
        return TargetScope(program_handle=program_handle, platform=Platform.HACKERONE,
                           in_scope=in_scope, out_of_scope=out_of_scope)

    @staticmethod
    def parse_bugcrowd_json(file_path: str, program_handle: str) -> TargetScope:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        in_scope, out_of_scope = [], []
        for target in data.get("targets", []):
            name = target.get("name", "")
            match_type = ScopeMatchType.WILDCARD if "*." in name else ScopeMatchType.EXACT
            rule = ScopeRule(pattern=name, match_type=match_type, description=target.get("category", ""))
            (in_scope if target.get("in_scope", True) else out_of_scope).append(rule)
        return TargetScope(program_handle=program_handle, platform=Platform.BUGCROWD,
                           in_scope=in_scope, out_of_scope=out_of_scope)
```

### 4.5 `sessions/session_manager.py`

```python
# sessions/session_manager.py
import asyncio
import aiohttp
import logging
from typing import Dict, Any, Optional
from core.types import MultiSessionContext

logger = logging.getLogger(__name__)

class SessionManager:
    """Bootstraps and maintains dual-session authentication tokens for IDOR/BAC specialists."""

    def __init__(self, auth_config: Dict[str, Any]):
        self.auth_config = auth_config
        self.context: Optional[MultiSessionContext] = None
        self._refresh_task: Optional[asyncio.Task] = None

    async def bootstrap_sessions(self) -> MultiSessionContext:
        """Authenticate User A, User B, Admin, and setup Unauth headers."""
        user_a = await self._login(self.auth_config.get("user_a"))
        user_b = await self._login(self.auth_config.get("user_b"))
        admin = await self._login(self.auth_config.get("admin"))

        self.context = MultiSessionContext(
            user_a_headers={"Authorization": f"Bearer {user_a['token']}"},
            user_b_headers={"Authorization": f"Bearer {user_b['token']}"},
            admin_headers={"Authorization": f"Bearer {admin['token']}"},
            unauth_headers={}
        )

        # Start background token refresh loop
        self._refresh_task = asyncio.create_task(self._token_refresh_loop())
        return self.context

    async def _login(self, creds: Optional[Dict]) -> Dict[str, str]:
        if not creds:
            return {"token": ""}
        async with aiohttp.ClientSession() as session:
            async with session.post(creds["login_url"], json=creds["payload"]) as resp:
                data = await resp.json()
                return {"token": data.get("access_token", "")}

    async def _token_refresh_loop(self):
        """Background loop: re-authenticate all sessions every 25 minutes.
        Implementer note: detect 401 responses from specialists and trigger
        immediate re-auth rather than waiting for the polling interval."""
        while True:
            await asyncio.sleep(25 * 60)  # 25 min default refresh interval
            try:
                await self.bootstrap_sessions()
                logger.info("Session tokens refreshed successfully")
            except Exception as e:
                logger.error(f"Token refresh failed: {e}")

    async def shutdown(self):
        if self._refresh_task:
            self._refresh_task.cancel()
```

---

## 5. Revised Assembly Roadmap (Phases 0 to 6)

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                      HARNESS ASSEMBLY ROADMAP (v2.1.1)                           â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜

 Phase 0: Core Types & Package Foundation
   â””â”€â–º Create pyproject.toml (Python control-plane only)
   â””â”€â–º Write core/types.py (TargetScope, VulnCategory, Task, etc.)
   â””â”€â–º Write core/config.py (HarnessConfig with port 8001, Ollama fallback)
   â””â”€â–º Write core/event_bus.py (IEventBus + InMemoryEventBus)

 Phase 1: Layer 0 Platform Compliance & Egress Proxy
   â””â”€â–º Write compliance/scope_gate.py (policy engine + OSINT domain allowlist)
   â””â”€â–º Write compliance/egress_proxy.py (mitmproxy addon + dry-run)
   â””â”€â–º Write compliance/header_injector.py (generates platform_profile.json)
   â””â”€â–º Write compliance/scope_importer.py (H1 CSV, Bugcrowd JSON parsers)
   â””â”€â–º Write compliance/oob_engine.py (Interactsh public/self-hosted)

 Phase 2: Memory Storage & Reference Ingestion
   â””â”€â–º Update mempalace/backends/sqlite_exact.py (v2.0 tables)
   â””â”€â–º Update mempalace/mcp_server.py (FP patterns, token logs)
   â””â”€â–º Write scripts/ingest_awesome_redteam.py
   â””â”€â–º Write scripts/ingest_cl4r1tas.py

 Phase 3: Budget Routing, Triage & Session Management
   â””â”€â–º Write budget/token_tracker.py & budget/model_router.py (+ Ollama health check)
   â””â”€â–º Write triage/noise_filter.py & triage/state_machine.py
   â””â”€â–º Write sessions/session_manager.py (+ background token refresh)

 Phase 4: Specialist Swarm & Engine Adaptation
   â””â”€â–º Write agents/specialist_base.py, dual_session_tester.py & 16 specialists
   â””â”€â–º Tweak adhd/src/frames.ts (6 security frames + HTTP token callback)
   â””â”€â–º Tweak adhd/src/engine.ts (FP lookup via mempalace â€” was critic.ts)
   â””â”€â–º Tweak claude-bug-bounty/agent.py, engine.py, brain.py
   â””â”€â–º Tweak claude-bug-bounty/memory/ (redirect to mempalace)
   â””â”€â–º Deprecate claude-bug-bounty/tools/scope_checker.py
   â””â”€â–º Tweak jsleak/main.go (+ go mod init if needed)


 Phase 5: Reporting, Orchestration & UI Consolidation
   â””â”€â–º Write reporting/taxonomy.py
   â””â”€â–º Write orchestrator/admiral.py (FastAPI on port 8001 + WS)
   â””â”€â–º Tweak T3MP3ST/src/server.ts & docs/index.html (War Room UI)
   â””â”€â–º Write main.py (bootstrap, mitmdump spawn, init command)

 Phase 6: Validation & Dry-Run Test Harness
   â””â”€â–º Write tests/test_scope_gate.py (DNS rebinding, CIDR, IPv6, ws://)
   â””â”€â–º Write tests/test_osint_exemption.py (allowlist + header abuse)
   â””â”€â–º Write tests/test_taxonomy.py (golden report output)
   â””â”€â–º Write tests/test_mock_e2e.py (Juice Shop E2E + dry-run)
```

---

## 6. Phase 6: Validation Harness Specification

1. **`tests/test_scope_gate.py`**:
   - DNS Rebinding vectors (`127.0.0.1`, `169.254.169.254`, `::1`, `[::ffff:127.0.0.1]`).
   - Regex wildcard matches (`*.example.com`), IPv6 CIDR, WebSocket schemes (`ws://`, `wss://`).
   - Third-party exclusions (`stripe.com`, `okta.com`, `auth0.com`).

2. **`tests/test_osint_exemption.py`**:
   - Requests to OSINT allowlist domains â†’ **allowed** (regardless of header).
   - Non-allowlist domains + `X-Harness-Traffic: osint` header â†’ **dropped + security warning**.
   - In-scope target domains â†’ `X-Harness-Traffic` header **stripped** before forwarding.

3. **`tests/test_taxonomy.py`**:
   - Golden output assertions for VRT, CWE, CVSS 3.1/4.0 per vulnerability category.
   - Platform-specific Markdown template validation (HackerOne, Bugcrowd, YesWeHack).

4. **`tests/test_mock_e2e.py`**:
   - Boots `egress_proxy.py` with `--dry-run`.
   - Fires synthetic requests against OWASP Juice Shop or DVWA.
   - Asserts `[DRY-RUN WOULD ALLOW]` / `[DRY-RUN WOULD DROP]` log correctness.

---

## 7. Reassessment Fix Traceability

| Fix ID | Issue | Resolution in v2.1.1 |
|---|---|---|
| **F-1** | `adhd/src/critic.ts` doesn't exist | Reclassified to TWEAK `adhd/src/engine.ts` |
| **F-2** | `jsleak/go.mod` doesn't exist | Removed reference; noted `go mod init` if needed |
| **F-3** | `BugTraceAI-CLI/` is empty | âŒ **RESOLVED**: Entire `BugTraceAI/` directory removed from workspace |
| **F-4** | `docsite/` TWEAK target wrong | Corrected to `T3MP3ST/docs/index.html` |
| **F-5** | `config/` directory doesn't exist | Changed to per-workspace `platform_profile.json` |
| **A-1** | Port 8000 collision | Admiral â†’ port `8001`; mempalace retains `8000` |
| **A-2** | Dual WebSocket directions | Single client-initiated WS from T3MP3ST â†’ admiral |
| **A-3** | OSINT header bypass risk | Domain-allowlist-primary; header-secondary + stripped |
| **A-4** | No Ollama fallback | Added startup health check + graceful degradation |
| **A-5** | No session token refresh | Added `_token_refresh_loop()` in skeleton |
| **A-6** | `claude-bug-bounty` modules unclassified | Classified: `memory/` â†’ TWEAK, `scope_checker.py` â†’ DEPRECATED |
| **M-1** | `core/types.py` unspecified | Added full dataclass/enum skeleton (Section 4.0) |
| **M-2** | `core/event_bus.py` unspecified | Added `IEventBus` interface + implementation (Section 4.1) |
| **M-3** | `platform_profile.json` schema undefined | Defined JSON schema in Section 1.4 |
| **M-4** | No logging/observability | Added structured JSON Lines spec (Section 1.8) |

---

## ðŸŽ¯ Status Summary

- **Version**: 2.1.1 â€” All 15 reassessment items resolved.
- **Factual Accuracy**: All KEEP/TWEAK/WRITE/DEPRECATED targets verified against actual workspace filesystem.
- **Planning Mode Active**: No code files modified or executed.
- **Ready for**: Implementation Phase 0.
