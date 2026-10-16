# 🌩️ STORM-HUNT: Generalized Bug-Bounty Swarm Architecture

This document establishes a target-agnostic, modular operational architecture for **STORM-HUNT**. It abstracts program-specific elements into a **Program Profile Schema** and details how the system dynamically configures its specialists, rate limits, and scope gates for *any* Bug Bounty target (HackerOne, Bugcrowd, YesWeHack, or self-hosted programs).

---

## 1. Executive Reassessment (Target-Agnostic Paradigm)

A sustainable solo bug-bounty automation framework must treat targets as dynamic inputs rather than hardcoded scripts. Hardcoding variables leads to rapid technical debt as program rules change.

STORM-HUNT uses a **data-driven execution model**:
1. **Dynamic Program Onboarding:** The framework reads a standardized JSON config (the `Program Profile`) defining in-scope assets, out-of-scope assets, rate limits, platform identity rules, and custom headers.
2. **Specialist Selection Mapping:** Instead of running all specialists on every target, the coordinator analyzes the onboarding metadata (e.g., identifying if the target uses GraphQL, file uploads, OAuth, or client-side heavy frameworks) and activates only the relevant specialist subagents.
3. **Programmatic Safety Gating:** Safe testing boundaries (IP blocks, DNS zones, blacklisted paths) are loaded into memory and enforced at the tool runtime level, independent of LLM decisions.

---

## 2. Program Profile Schema (Onboarding Format)

To onboard any new target program, the analyst creates a `profile.json` file in the program's target directory:

```json
{
  "program_name": "target-corp",
  "platform": "hackerone",
  "rewards": {
    "currency": "USD",
    "low": 200,
    "medium": 600,
    "high": 1500,
    "critical": 5000
  },
  "operational_rules": {
    "max_requests_per_second": 2,
    "user_agent_token": "H1-Hunter-Token-Here",
    "custom_headers": {
      "X-Bug-Bounty": "target-corp-hunter-identifier"
    },
    "rate_limit_429_backoff_seconds": 300
  },
  "scope": {
    "in_scope": [
      {
        "pattern": "^https:\\/\\/([a-z0-9-]+\\.)?targetcorp\\.com(\\/.*)?$",
        "asset_type": "wildcard_domain",
        "features": ["auth", "api", "upload"]
      },
      {
        "pattern": "^api\\.targetcorp\\.com$",
        "asset_type": "api_gateway",
        "features": ["graphql", "oauth"]
      }
    ],
    "out_scope": [
      {
        "pattern": ".*\\/dev-stage\\/.*",
        "reason": "Explicitly out of scope in policy"
      }
    ]
  }
}
```

---

## 3. Revised Bug-Bounty Swarm Architecture

The core framework manages execution dynamically by evaluating the **Program Profile** at runtime.

```mermaid
graph TD
    User([Analyst]) -->|Loads target profile.json| Coordinator[TS Coordinator]
    
    Coordinator -->|Enforces Profile Limits| ScopeGate[Egress Scope Gate]
    ScopeGate -->|Rate Limits & Custom UA| LiveTarget[Target Endpoints]
    
    Coordinator -->|Initializes Program Features| PhaseOrchestrator[Kill Chain Orchestrator]
    
    subgraph Specialists (Activated on demand)
        AuthSpec[Auth & Session Specialist]
        APISpec[API & Parameter Specialist]
        UploadSpec[File Upload Specialist]
        ClientJSSpec[Client-Side JS Auditor]
    end
    
    PhaseOrchestrator -->|Feature: auth| AuthSpec
    PhaseOrchestrator -->|Feature: graphql / api| APISpec
    PhaseOrchestrator -->|Feature: upload| UploadSpec
    PhaseOrchestrator -->|Feature: js_heavy| ClientJSSpec
    
    Specialists -->|Check context & patterns| RAG[Vector RAG MCP Server]
    Specialists -->|Candidate findings| StrictTriager[Strict Triager & Negative Control]
    
    StrictTriager -->|Verified Findings| EvidenceVault[Evidence Vault]
    EvidenceVault -->|Formats Markdown| ReportGen[Bounty Report Formatter]
```

---

## 4. Generalized Target Prioritization Strategy

When analyzing an arbitrary program, STORM-HUNT maps attack surfaces to specific specialists and executes a standard set of initial actions:

### A. Wildcard DNS & Subdomains
* **Rationale:** Finds forgotten endpoints, staging environments, or exposed administrative portals.
* **Workflow Owner:** Coordinator (using local recon tools).
* **Initial Actions:**
  1. Retrieve subdomains using passive OSINT APIs (e.g., crt.sh, subfinder) to avoid sending direct traffic.
  2. Filter results against the `in_scope` regex patterns defined in the Program Profile.

### B. API Gateways (REST, GraphQL, gRPC)
* **Rationale:** Exposes logical checks, unauthenticated routes, and BOLA/IDOR entry points.
* **Workflow Owner:** API & Parameter Specialist.
* **Initial Actions:**
  1. Parse OpenAPI specs, `/swagger.json`, or attempt GraphQL introspection queries.
  2. Extract parameter lists and rank them locally using the local GPU model.

### C. Authentication & Session States
* **Rationale:** Exposes account recovery flaws, cookie misconfigurations, and OAuth callback bypasses.
* **Workflow Owner:** Auth & Session Specialist.
* **Initial Actions:**
  1. Trace authentication HTTP requests to identify cookie/header mechanics (JWT, session tokens).
  2. Run standard local checks for token entropy, cookie flag omissions (`Secure`, `HttpOnly`), and CORS policies.

### D. File Upload Fields
* **Rationale:** Exposes Critical/High severity bugs such as Remote Code Execution (RCE) via web shells, XML External Entity (XXE), or path traversals.
* **Workflow Owner:** File Upload Specialist.
* **Initial Actions:**
  1. Map multipart form inputs across discovered endpoints.
  2. Probe with benign, small metadata payloads (e.g., SVG containing basic XML tags) to check parser output anomalies.

---

## 5. Phased 2-Week Campaign Runbook

Below is the standard, target-agnostic 2-week execution schedule for running STORM-HUNT against *any* onboarded program:

```
                  STORM-HUNT GENERALIZED RUNBOOK
                  
  [ WEEK 1: ONBOARDING & PASSIVE SCOUTING ]
  ┌─────────────────────────────────────────────────────────────┐
  │  • Day 1-2: Onboard target profile & Index source (if white)│
  │  • Day 3-4: Passive DNS/Subdomain enumeration               │
  │  • Day 5-7: Low-volume active mapping (max 2 req/s)         │
  └─────────────────────────────────────────────────────────────┘
  
  [ WEEK 2: SPECIALIST SWARM & VERIFICATION ]
  ┌─────────────────────────────────────────────────────────────┐
  │  • Day 8-9: Activate specialists based on surface profiles   │
  │  • Day 10-12: Execute Negative Control triaging             │
  │  • Day 13-15: Export report formats & Ingest lessons to RAG  │
  └─────────────────────────────────────────────────────────────┘
```

### Week 1: Onboarding and Passive Scouting
* **Day 1–2: Program Configuration**
  * Populate `profile.json` with target constraints, reward grids, and scope rules.
  * If the target is white-box/source-available, ingest the source tree into the local RAG index.
* **Day 3–4: Passive Scanning & Asset Inventory**
  * Aggregate domain lists from public certificates and DNS dumps.
  * Run local deduplication and clean files of out-of-scope assets.
* **Day 5–7: Passive Fingerprinting & Active Mapping**
  * Map endpoints, analyze HTTP header options, and extract public JS bundles.
  * Feed findings into the local GPU model for parameter categorization.

### Week 2: Specialist Swarming and Verification
* **Day 8–9: Focused Scanning**
  * Dispatch target-specific specialists (e.g., run the **API Specialist** on targets with JSON/GraphQL APIs).
  * Enforce maximum request limits to prevent triggering target protective rate limiters.
* **Day 10–12: Triaging Anomalies**
  * Route all flagged vulnerabilities to the **Strict Triager**.
  * Run negative controls (making requests with modified inputs that should fail) to isolate validation logic.
* **Day 13–15: Final Documentation**
  * Format reports into platform-ready Markdown templates (outlining impacted endpoint, reproduction steps, impact, and remediation).
  * Write lessons learned to the local RAG engine.

---

## 6. Token & Model Routing Policy

To ensure high-efficiency solo operations, STORM-HUNT enforces these routing rules:

| Operational Step | Model Used | Pricing Class | Objective / Context Limit |
| :--- | :--- | :--- | :--- |
| **Log Parsing & Sorting** | Local Llama-3-8B | Free (GPU) | Truncates raw tool outputs down to high-signal subsets (<20 lines). |
| **Endpoint Classification** | DeepSeek-V3 / Llama-3.1 | Mechanical ($0.14/MT) | Categorizes parameters and assigns them to specialists. |
| **Target Auditing & Fuzzing** | Claude 3.5 Sonnet | Standard ($3.00/MT) | Specialist ReAct loops executing specific payload test cases. |
| **Final Exploit Triaging** | Claude 3 Opus / 4.8 | Flagship ($15.00/MT) | Generates reports and verifies negative controls. |

### Strict Budgets
* **Daily Cap:** $20.00 maximum cloud API token spend.
* **Turn Cap:** Maximum **15 turns** per specialist run. If a logical bug is not isolated within 15 turns, STORM-HUNT will abort that execution path to prevent infinite loops.

---

## 7. Database Schemas

These tables run on SQLite or PostgreSQL to log campaign cost metrics and findings.

### A. Token Tracker Schema
```sql
CREATE TABLE token_logs (
    run_id VARCHAR(36) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    agent_id VARCHAR(50) NOT NULL,
    model_tier VARCHAR(20) CHECK (model_tier IN ('local', 'mechanical', 'standard', 'flagship')),
    prompt_type VARCHAR(30) NOT NULL, -- e.g., system, user, tool_result, chain
    tool_name VARCHAR(50),
    target VARCHAR(255) NOT NULL,     -- Specific target URL
    program VARCHAR(100) NOT NULL,    -- Parent program name (e.g., target-corp)
    phase VARCHAR(20) CHECK (phase IN ('recon', 'scan', 'exploit', 'triage')),
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd NUMERIC(10, 6) NOT NULL,
    severity_class VARCHAR(10) CHECK (severity_class IN ('none', 'low', 'medium', 'high', 'critical')),
    yield BOOLEAN NOT NULL            -- TRUE if call led directly to a validated finding
);
```

### B. Report State Tracker Schema
```sql
CREATE TABLE report_state (
    finding_id VARCHAR(36) PRIMARY KEY,
    target VARCHAR(255) NOT NULL,
    program VARCHAR(100) NOT NULL,
    severity VARCHAR(10) CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    bug_class VARCHAR(50) NOT NULL,
    discovery_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    state VARCHAR(20) CHECK (state IN ('candidate', 'triaged', 'submitted', 'accepted', 'rejected', 'duplicate', 'informational')),
    triager_notes TEXT,
    model_confidence NUMERIC(3, 2),
    evidence_quality_score INTEGER CHECK (evidence_quality_score BETWEEN 1 AND 10),
    submission_url VARCHAR(255),
    payout_usd NUMERIC(10, 2),
    rag_ingested BOOLEAN DEFAULT FALSE,
    rejection_reason VARCHAR(255)
);
```

---

## 8. Hardcoded Risk Controls & Anti-Waste Rules

* **Scope Enforcement Filter:** Every command output containing IP/host addresses must be parsed through the Scope Gate prior to tool execution. If a target fails to match the onboarded profile regex, the command is blocked (`SCOPE DENIED`).
* **Rate-Limit Guard:** Active HTTP request engines must enforce a hard limit of **2 requests per second**.
* **Automatic Backoff:** If the target returns HTTP status code `429`, STORM-HUNT must sleep for `rate_limit_429_backoff_seconds` and halve the current request speed.
* **Low-Severity Suppression:** Any candidate finding classified as Low (e.g., missing cookie flag, directory listing on an empty staging folder) is logged as `informational` and suppressed from final reporting queues to prevent token waste.

---

## 9. Top Metrics to Monitor

1. **Campaign API Burn Rate:** `Total Cloud USD / Number of onboarded targets`.
2. **Specialist Turn Density:** `Total turns / Number of findings discovered`. High turn density without findings indicates model loop traps.
3. **Triager Precision:** `Number of findings in state 'accepted' / Number of findings in state 'triaged'`.
4. **Local Offload Yield:** `Input tokens processed locally / Input tokens sent to Cloud APIs`.
5. **Program Payout Ratio:** `Total payouts USD / Total API spend USD`.
