# Bug Bounty Harness — Gap-Bridging Technical Specification & Implementation Blueprint (v2.1.2)

**Version:** 2.1.2  
**Date:** 2026-09-06  
**Status:** Active Implementation Blueprint  
**Target Workspace:** `/home/souhail/Desktop/Desktop/Ult_harness`  
**Companion Documents:**
- [`bug_bounty_harness_design_v2_1.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/bug_bounty_harness_design_v2_1.md)
- [`Bug Bounty Harness Orchestration and AI Gateway Specification v2.1.2.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/Bug%20Bounty%20Harness%20Orchestration%20and%20AI%20Gateway%20Specification%20v2.1.2.md)
- [`progress_report.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/progress_report.md)

---

## 1. Executive Summary & Architectural Scope

This document serves as the authoritative, low-level technical specification and implementation blueprint to bridge all remaining gaps in the Autonomous Bug Bounty Harness v2.1.2.

### 1.1 Current System Baseline

| Core Domain | Implementation Status | Completed Modules / Components |
|---|---|---|
| **Phase 0: Core Foundation** | ✅ 100% COMPLETE | `core/types.py`, `core/config.py`, `core/event_bus.py`, `pyproject.toml` |
| **Phase 1: Compliance & Egress** | ✅ 100% COMPLETE | `compliance/scope_importer.py`, `compliance/scope_gate.py`, `compliance/egress_proxy.py`, `compliance/header_injector.py`, `compliance/oob_engine.py` |
| **Phase 2: Memory & Knowledge** | ✅ 100% COMPLETE | `scripts/ingest_awesome_redteam.py`, `scripts/ingest_cl4r1tas.py`, mempalace database schema & API |
| **Phase 3: Routing, Triage & Sessions** | ✅ 100% COMPLETE | `budget/token_tracker.py`, `budget/model_router.py`, `triage/noise_filter.py`, `triage/state_machine.py`, `sessions/session_manager.py` |
| **Phase 4A: Specialist Swarm** | ✅ 100% COMPLETE | `agents/specialist_base.py`, `agents/dual_session_tester.py`, 16 specialist category agents (`agents/specialists/`) |
| **Phase 4B: External Tool Adaptation** | 🟡 80% PARTIAL | `adhd/src/frames.ts` (Done); `adhd/src/engine.ts`, `claude-bug-bounty/*`, `jsleak/main.go` pending |
| **Phase 5: Orchestration & UI** | ❌ 0% NOT STARTED | `reporting/taxonomy.py`, `orchestrator/admiral.py`, `orchestrator/cli_tunnel.py`, `main.py`, T3MP3ST server/docs integration |
| **Phase 6: Validation & Testing** | ❌ 0% NOT STARTED | `tests/test_scope_gate.py`, `tests/test_osint_exemption.py`, `tests/test_taxonomy.py`, `tests/test_mock_e2e.py` |
| **Phase 7: Qwen3.8-27B LOCAL_HEAVY** | 🟡 10% SPEC DONE | `HarnessConfig` extension, `ModelRouter` LOCAL_HEAVY tier, `TokenTracker` GPU-hour metrics, T3MP3ST gauges |

---

## 2. Phase 4B Specification: External Tool & Engine Adaptation

To enforce strict token accounting, false-positive (FP) pattern filtering, and scope compliance across external CLI tools (`adhd`, `claude-bug-bounty`, `jsleak`), each tool must be adapted to integrate with the harness control plane (`:8001`), memory service (`:8000`), and compliance egress proxy (`:8080`).

```
                               ┌───────────────────────────────────┐
                               │       External Tool Layer         │
                               │  adhd | claude-bug-bounty | jsleak│
                               └─┬───────────────┬───────────────┬─┘
                                 │ HTTP POST     │ HTTP Proxy    │ REST Query
                                 │ Token/Route   │ 127.0.0.1:8080│ 127.0.0.1:8000
                                 ▼               ▼               ▼
                       ┌────────────────┐ ┌─────────────┐ ┌─────────────┐
                       │ OpAdmiral      │ │ ScopeGate / │ │ MemPalace   │
                       │ (:8001)        │ │ Egress Proxy│ │ Memory      │
                       └────────────────┘ └─────────────┘ └─────────────┘
```

### 2.1 Step 4.6 — `adhd/src/engine.ts` Tweak

**File Location:** [`adhd/src/engine.ts`](file:///home/souhail/Desktop/Desktop/Ult_harness/adhd/src/engine.ts)

#### Requirements
1. **Token Ingestion Callback:** Upon completion of a frame run inside `run()`, construct a payload with prompt and completion token counts and POST to `http://127.0.0.1:8001/api/tokens/record`.
2. **FP Anti-Pattern Query:** Before returning generated attack ideas, execute an HTTP POST to `http://127.0.0.1:8000/search` querying table `fp_patterns` for vector matches against candidate strategies. Filter out strategy items exceeding similarity score threshold `0.85`.

#### Code Specification
```typescript
// adhd/src/engine.ts additions

interface TokenRecordPayload {
  agent_id: string;
  task_type: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

async function recordTokens(agentId: string, taskType: string, model: string, inputTokens: number, outputTokens: number): Promise<void> {
  const url = process.env.HARNESS_API_URL || 'http://127.0.0.1:8001';
  try {
    await fetch(`${url}/api/tokens/record`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_id: agentId,
        task_type: taskType,
        model: model,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        cost_usd: 0.0
      })
    });
  } catch (err) {
    console.warn('[ADHD] Failed to report token metrics:', err);
  }
}

async function filterFPPatterns(ideas: string[]): Promise<string[]> {
  const mempalaceUrl = process.env.MEMPALACE_URL || 'http://127.0.0.1:8000';
  const cleanIdeas: string[] = [];
  
  for (const idea of ideas) {
    try {
      const res = await fetch(`${mempalaceUrl}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: idea, table: 'fp_patterns', limit: 3 })
      });
      const data = await res.json();
      const highestScore = data.results?.[0]?.score || 0;
      if (highestScore < 0.85) {
        cleanIdeas.push(idea);
      } else {
        console.log(`[ADHD] Dropped FP strategy match (${highestScore}): ${idea}`);
      }
    } catch {
      cleanIdeas.push(idea); // Graceful fallback
    }
  }
  return cleanIdeas;
}
```

---

### 2.2 Steps 4.7–4.11 — `claude-bug-bounty` Integration

**Files:** `claude-bug-bounty/agent.py`, `engine.py`, `brain.py`, `memory/*.py`, `tools/scope_checker.py`

#### Requirements & Specifications
- **Step 4.7 (`agent.py`):** Intercept all direct Anthropic/OpenAI API client calls. Wrap calls to route through `POST http://127.0.0.1:8001/api/v1/llm/route` with `{ "task_type": "source_vuln_scan", "prompt": ... }`.
- **Step 4.8 (`engine.py`):** Inject environment variables on module initialization:
  ```python
  import os
  os.environ["HTTP_PROXY"] = os.getenv("EGRESS_PROXY_URL", "http://127.0.0.1:8080")
  os.environ["HTTPS_PROXY"] = os.getenv("EGRESS_PROXY_URL", "http://127.0.0.1:8080")
  ```
- **Step 4.9 (`brain.py`):** When building agent prompts, query `http://127.0.0.1:8000/search` table `cl4r1tas_prompts` with target domain/vulnerability category, prepending matching system prompt directives.
- **Step 4.10 (`memory/*`):** Replace local JSON/SQLite calls in `audit_log.py`, `pattern_db.py`, and `rotation.py` with HTTP calls to MemPalace REST endpoints (`/record_token_usage`, `/search_fp_patterns`, `/store_rotation`).
- **Step 4.11 (`tools/scope_checker.py`):** Deprecate legacy scope checker:
  ```python
  import warnings
  from compliance.scope_gate import ScopeGate
  
  warnings.warn("ScopeChecker is deprecated. Delegate to compliance.scope_gate.ScopeGate", DeprecationWarning, stacklevel=2)
  ```

---

### 2.3 Step 4.12 — `jsleak/main.go` Proxy & Output Fixes

**File Location:** [`jsleak/main.go`](file:///home/souhail/Desktop/Desktop/Ult_harness/jsleak/main.go)

#### Requirements
1. Configure `http.Client` to respect `HTTP_PROXY` environment variable.
2. Add `-json` flag to emit structured JSON lines matching `{ "url": "...", "pattern": "...", "secret": "..." }`.

#### Go Code Modification
```go
// jsleak/main.go updates
var jsonOutput bool
flag.BoolVar(&jsonOutput, "json", false, "Output results as single-line JSON objects")

// Transport setup with HTTP_PROXY support
proxyURL, err := http.ProxyFromEnvironment(&http.Request{})
transport := &http.Transport{
    Proxy: http.ProxyFromEnvironment,
    TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
}
client := &http.Client{
    Transport: transport,
    Timeout:   15 * time.Second,
}
```

---

## 3. Phase 5 Specification: Orchestration, Reporting & War Room UI

Phase 5 builds the operational brain (`orchestrator/admiral.py`), reporting taxonomy generator (`reporting/taxonomy.py`), CLI entry point (`main.py`), and connects the Node/TypeScript war room (`T3MP3ST`).

```
┌────────────────────────────────────────────────────────────────────────┐
│                          T3MP3ST War Room                              │
│                    (Node/TS Server on port 3333)                        │
└──────────────────┬─────────────────────────────────▲───────────────────┘
                   │ REST API Calls                  │ WebSocket Events
                   │ (GET /status, POST /confirm)    │ (ws://localhost:8001/ws)
                   ▼                                 │
┌────────────────────────────────────────────────────┴───────────────────┐
│                      OpAdmiral Control Plane                           │
│                     (FastAPI App on port 8001)                         │
├─────────────────┬───────────────────┬──────────────────┬───────────────┤
│ EventBus        │ TokenTracker      │ ModelRouter      │ ScopeGate     │
│ (In-Memory async)│ (Cost & GPU-hours)│ (4-Tier Routing) │ (Policy)      │
└────────┬────────┴─────────┬─────────┴────────┬─────────┴───────┬───────┘
         │                  │                  │                 │
         ▼                  ▼                  ▼                 ▼
   Specialists         MemPalace         Ollama / Cloud     mitmproxy Egress
   (16 Agents)         (:8000)           llm-server         (:8080)
```

---

### 3.1 Step 5.2 — `reporting/taxonomy.py` Design

**File Location:** `/home/souhail/Desktop/Desktop/Ult_harness/reporting/taxonomy.py`

#### Data Mapping Tables & Architecture
`TaxonomyMapper` converts internal findings into standardized Bugcrowd VRT, CWE IDs, CVSS 3.1 vector strings, and markdown report templates tailored for Bugcrowd, HackerOne, and YesWeHack.

```python
# reporting/taxonomy.py
import logging
from typing import Dict, Any, Optional
from core.types import VulnCategory, Platform, Task

logger = logging.getLogger(__name__)

VRT_MAPPINGS: Dict[VulnCategory, Dict[str, str]] = {
    VulnCategory.SQLI: {"category": "Server-Side Injection", "variant": "SQL Injection (SQLi)", "cwe": 89, "cvss_base": "9.8"},
    VulnCategory.XSS: {"category": "Cross-Site Scripting (XSS)", "variant": "Stored XSS", "cwe": 79, "cvss_base": "7.2"},
    VulnCategory.SSRF: {"category": "Server-Side Request Forgery (SSRF)", "variant": "Internal Infrastructure SSRF", "cwe": 918, "cvss_base": "8.6"},
    VulnCategory.IDOR: {"category": "Broken Authorization", "variant": "Insecure Direct Object Reference (IDOR)", "cwe": 639, "cvss_base": "7.5"},
    VulnCategory.LFI: {"category": "File Inclusion", "variant": "Local File Inclusion (LFI)", "cwe": 98, "cvss_base": "7.5"},
    VulnCategory.RCE: {"category": "Server-Side Injection", "variant": "Remote Code Execution (RCE)", "cwe": 94, "cvss_base": "9.8"},
    VulnCategory.XXE: {"category": "Server-Side Injection", "variant": "XML External Entity (XXE)", "cwe": 611, "cvss_base": "8.2"},
    VulnCategory.JWT: {"category": "Broken Authentication", "variant": "Weak JWT Signature / Alg None", "cwe": 347, "cvss_base": "7.5"},
    VulnCategory.OPEN_REDIRECT: {"category": "Unvalidated Redirects and Forwards", "variant": "Open Redirect", "cwe": 601, "cvss_base": "6.1"},
    VulnCategory.PROTOTYPE_POLLUTION: {"category": "Server-Side Injection", "variant": "Prototype Pollution", "cwe": 1321, "cvss_base": "7.5"},
    VulnCategory.CSTI: {"category": "Cross-Site Scripting (XSS)", "variant": "Client-Side Template Injection (CSTI)", "cwe": 94, "cvss_base": "6.5"},
    VulnCategory.MASS_ASSIGNMENT: {"category": "Broken Authorization", "variant": "Mass Assignment / Parameter Binding", "cwe": 915, "cvss_base": "6.5"},
    VulnCategory.HEADER_INJECTION: {"category": "Server-Side Injection", "variant": "HTTP Header Injection", "cwe": 113, "cvss_base": "6.1"},
    VulnCategory.BAC: {"category": "Broken Authorization", "variant": "Broken Access Control", "cwe": 284, "cvss_base": "8.1"},
    VulnCategory.AI_JAILBREAK: {"category": "AI/LLM Vulnerabilities", "variant": "Direct Prompt Injection / Jailbreak", "cwe": 1427, "cvss_base": "7.5"},
    VulnCategory.BUSINESS_LOGIC: {"category": "Business Logic Flaws", "variant": "Logic Bypass", "cwe": 840, "cvss_base": "7.5"},
}

class TaxonomyMapper:
    def get_vrt(self, category: VulnCategory) -> str:
        data = VRT_MAPPINGS.get(category, {})
        return f"{data.get('category', 'Other')} -> {data.get('variant', 'Generic')}"

    def get_cwe(self, category: VulnCategory) -> int:
        return VRT_MAPPINGS.get(category, {}).get("cwe", 200)

    def get_cvss_vector(self, category: VulnCategory, impact_level: str = "HIGH") -> str:
        # Returns CVSS 3.1 Vector string
        if category in (VulnCategory.SQLI, VulnCategory.RCE):
            return "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        elif category == VulnCategory.SSRF:
            return "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N"
        return "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:L/A:N"

    def generate_report(self, task: Task, finding_data: Dict[str, Any], platform: Platform) -> str:
        vrt = self.get_vrt(task.vuln_category)
        cwe = self.get_cwe(task.vuln_category)
        cvss = self.get_cvss_vector(task.vuln_category)
        
        template = f"""# [VULNERABILITY REPORT] {task.vuln_category.value.upper()} on {task.target_endpoint}

## Summary
A vulnerability of type **{vrt}** (CWE-{cwe}) was identified at target endpoint `{task.target_endpoint}`.

- **Platform Target:** {platform.value}
- **CVSS 3.1 Vector:** `{cvss}`
- **Verification Status:** Confirmed via Autonomous Harness

## Proof of Concept
```http
{finding_data.get('poc_request', 'N/A')}
```

### Response Evidence
```http
{finding_data.get('poc_response', 'N/A')}
```

## Impact
{finding_data.get('impact_description', 'Unauthorized access or manipulation of server state.')}

## Remediation Guidance
Ensure strict input validation, parameter binding, and access control checks on `{task.target_endpoint}`.
"""
        return template
```

---

### 3.2 Step 5.4 — `orchestrator/admiral.py` Technical Design

**File Location:** `/home/souhail/Desktop/Desktop/Ult_harness/orchestrator/admiral.py`

`OpAdmiral` is a FastAPI application running on port **8001**. It manages the WebSocket event stream, REST endpoints for token tracking and findings triage, specialist task dispatching, and integrates core singletons.

#### REST API Endpoints Specification

| Method | Endpoint | Request Body | Response Body | Description |
|---|---|---|---|---|
| `POST` | `/api/tokens/record` | `{"agent_id": str, "task_type": str, "model": str, "input_tokens": int, "output_tokens": int}` | `{"status": "ok", "remaining": int}` | Ingests token usage from agents/adhd |
| `POST` | `/api/triage/callback` | `{"specialist_id": str, "endpoint": str, "category": str, "evidence": dict}` | `{"finding_id": str, "status": str}` | Ingests scanner hits and creates findings |
| `POST` | `/api/v1/llm/route` | `{"task_type": str, "prompt": str}` | `{"text": str, "model": str, "tier": str}` | ModelRouter proxy endpoint for external tools |
| `GET` | `/api/v1/status` | None | `{"wings": dict, "budget": dict, "active_tasks": int}` | Status summary for T3MP3ST UI |
| `GET` | `/api/v1/findings` | None | `[{"id": str, "category": str, "status": str, "poc": str}]` | List all findings |
| `POST` | `/api/v1/findings/{id}/confirm` | None | `{"id": str, "status": "confirmed"}` | Operator confirms finding |
| `POST` | `/api/v1/findings/{id}/reject` | `{"reason": str}` | `{"id": str, "status": "false_positive"}` | Operator rejects finding with FP reason |
| `WS` | `/ws` | WebSocket Protocol | Bidirectional JSON events | Real-time event stream to T3MP3ST |

#### Code Implementation Blueprint
```python
# orchestrator/admiral.py
import asyncio
import logging
from typing import Dict, List, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import HarnessConfig
from core.event_bus import InMemoryEventBus
from core.types import Task, VulnStatus, VulnCategory, OrchestrationEvent
from budget.token_tracker import TokenTracker
from budget.model_router import ModelRouter, ModelTier
from sessions.session_manager import SessionManager
from compliance.scope_gate import ScopeGate

logger = logging.getLogger(__name__)

app = FastAPI(title="OpAdmiral Control Plane", version="2.1.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State Container
class AdmiralState:
    config: HarnessConfig
    event_bus: InMemoryEventBus
    token_tracker: TokenTracker
    model_router: ModelRouter
    session_manager: SessionManager
    scope_gate: ScopeGate
    active_websockets: List[WebSocket] = []
    findings: Dict[str, Dict[str, Any]] = {}

state = AdmiralState()

@app.on_event("startup")
async def startup_event():
    state.config = HarnessConfig.load_from_env()
    state.event_bus = InMemoryEventBus()
    state.token_tracker = TokenTracker(hard_cap=1000000)
    state.model_router = ModelRouter(state.config, state.token_tracker)
    state.session_manager = SessionManager(state.config)
    state.scope_gate = ScopeGate()
    logger.info("[ADMIRAL] OpAdmiral initialized on port %d", state.config.api_port)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.active_websockets.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming WebSocket commands from operator
    except WebSocketDisconnect:
        state.active_websockets.remove(websocket)

async def broadcast_event(event: OrchestrationEvent):
    payload = {
        "event_type": event.event_type,
        "correlation_id": event.correlation_id,
        "source": event.source_component,
        "payload": event.payload
    }
    for ws in state.active_websockets:
        try:
            await ws.send_json(payload)
        except Exception:
            pass

class TokenRecordRequest(BaseModel):
    agent_id: str
    task_type: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float = 0.0

@app.post("/api/tokens/record")
async def record_tokens(req: TokenRecordRequest):
    tier = ModelTier.LOCAL
    if "70b" in req.model or "groq" in req.model:
        tier = ModelTier.PAID_FREE
    elif "gpt" in req.model or "claude" in req.model:
        tier = ModelTier.PAID_PREMIUM
    
    state.token_tracker.record_usage(req.agent_id, req.input_tokens, req.output_tokens, req.model, tier)
    return {"status": "ok", "remaining": state.token_tracker.get_budget(req.agent_id).remaining}

class FindingCallback(BaseModel):
    specialist_id: str
    endpoint: str
    category: str
    evidence: Dict[str, Any]

@app.post("/api/triage/callback")
async def triage_callback(cb: FindingCallback):
    finding_id = f"find-{len(state.findings)+1:04d}"
    finding = {
        "id": finding_id,
        "specialist_id": cb.specialist_id,
        "endpoint": cb.endpoint,
        "category": cb.category,
        "evidence": cb.evidence,
        "status": VulnStatus.IDENTIFIED.value
    }
    state.findings[finding_id] = finding
    
    event = OrchestrationEvent(
        event_type="finding_identified",
        correlation_id=finding_id,
        source_component=cb.specialist_id,
        payload=finding
    )
    await broadcast_event(event)
    return {"finding_id": finding_id, "status": "recorded"}

@app.get("/api/v1/status")
async def get_status():
    return {
        "wings": {"active_specialists": 16, "status": "hunting"},
        "budget": {
            "tokens_used": state.token_tracker.total_tokens_used,
            "cost_usd": state.token_tracker.total_cost_usd,
            "gpu_hours": getattr(state.token_tracker, "local_heavy_gpu_hours", 0.0)
        },
        "findings_count": len(state.findings)
    }

@app.get("/api/v1/findings")
async def get_findings():
    return list(state.findings.values())

@app.post("/api/v1/findings/{finding_id}/confirm")
async def confirm_finding(finding_id: str):
    if finding_id not in state.findings:
        raise HTTPException(status_code=404, detail="Finding not found")
    state.findings[finding_id]["status"] = VulnStatus.CONFIRMED.value
    return state.findings[finding_id]

class RejectRequest(BaseModel):
    reason: str

@app.post("/api/v1/findings/{finding_id}/reject")
async def reject_finding(finding_id: str, req: RejectRequest):
    if finding_id not in state.findings:
        raise HTTPException(status_code=404, detail="Finding not found")
    state.findings[finding_id]["status"] = VulnStatus.FALSE_POSITIVE.value
    state.findings[finding_id]["fp_reason"] = req.reason
    return state.findings[finding_id]
```

---

### 3.3 Step 5.6 — `main.py` Entry Point Design

**File Location:** `/home/souhail/Desktop/Desktop/Ult_harness/main.py`

`main.py` is the unified CLI entry point supporting three primary commands:
1. `python main.py init --platform hackerone --program acme-corp`: Parses scope, generates workspace directory, and invokes `header_injector.py`.
2. `python main.py run --program acme-corp [--dry-run]`: Spawns the services sequence in order: Egress Proxy → MemPalace → OpAdmiral → Session Loop → Specialists.
3. `python main.py stop`: Gracefully terminates all background subprocesses and saves session state.

```python
# main.py
import argparse
import sys
import os
import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def init_program(platform: str, program: str):
    logging.info("[MAIN] Initializing workspace for program '%s' on platform '%s'...", program, platform)
    os.makedirs(f"workspace/{program}", exist_ok=True)
    subprocess.run([sys.executable, "compliance/header_injector.py", "--platform", platform, "--program", program], check=True)
    logging.info("[MAIN] Initialization complete. workspace/%s/platform_profile.json generated.", program)

def run_harness(program: str, dry_run: bool):
    logging.info("[MAIN] Starting Autonomous Bug Bounty Harness v2.1.2 (Dry Run: %s)", dry_run)
    env = os.environ.copy()
    if dry_run:
        env["HARNESS_DRY_RUN"] = "true"

    # Boot Sequence
    processes = []
    try:
        logging.info("[1/4] Launching Compliance Egress Proxy on :8080...")
        processes.append(subprocess.Popen(["mitmdump", "-s", "compliance/egress_proxy.py", "-p", "8080"], env=env))
        
        logging.info("[2/4] Starting OpAdmiral Control Plane on :8001...")
        processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "orchestrator.admiral:app", "--port", "8001"], env=env))
        
        time.sleep(2)
        logging.info("[3/4] Initializing Specialist Swarm (16 Vulnerability Agents)...")
        # Initialize specialists
        
        logging.info("[4/4] Harness fully operational. War room accessible at http://localhost:3333")
        processes[-1].wait()
    except KeyboardInterrupt:
        logging.info("[MAIN] Shutting down harness components...")
        for p in processes:
            p.terminate()

def main():
    parser = argparse.ArgumentParser(description="Autonomous Bug Bounty Harness v2.1.2 Entry Point")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize workspace & scope")
    init_parser.add_argument("--platform", required=True, choices=["hackerone", "bugcrowd", "yeswehack", "intigriti", "immunefi"])
    init_parser.add_argument("--program", required=True, help="Program handle")

    run_parser = subparsers.add_parser("run", help="Start the hunt")
    run_parser.add_argument("--program", required=True)
    run_parser.add_argument("--dry-run", action="store_true", help="Execute without sending outbound network traffic")

    args = parser.parse_args()
    if args.command == "init":
        init_program(args.platform, args.program)
    elif args.command == "run":
        run_harness(args.program, args.dry_run)

if __name__ == "__main__":
    main()
```

---

## 4. Phase 6 Specification: Validation & Dry-Run Test Suite

Phase 6 provides end-to-end automated verification of scope compliance, OSINT header stripping, reporting taxonomy mappings, and zero-socket dry-run isolation.

### 4.1 Test Module Matrix

| Test Module File | Focus & Test Cases | Assertion Strategy |
|---|---|---|
| `tests/test_scope_gate.py` | Exact domain, wildcard (`*.example.com`), CIDR ranges (`10.0.0.0/8`), Regex rules, DNS rebinding (`127.0.0.1`, `169.254.169.254`, `::1`), WebSocket `ws://` protocols | Assert `ScopeGate.is_in_scope()` returns `True` for valid targets and `False` + blocks for out-of-scope / private IP attempts |
| `tests/test_osint_exemption.py` | OSINT domain exemptions (e.g. `github.com`, `twitter.com`), header stripping (`X-OSINT-Recon`), target scope boundary checking | Assert `X-OSINT-Recon` header is present for OSINT tool calls, stripped before forwarding, and dropped if non-OSINT |
| `tests/test_taxonomy.py` | VRT mapping, CWE assignment, CVSS 3.1 vector calculation, markdown report generation across platforms | Assert exact match against VRT schemas and CVSS 3.1 severity scores |
| `tests/test_mock_e2e.py` | Complete hunt execution in `--dry-run` mode | Intercept socket requests; assert zero outbound packets transmitted and log records `WOULD_SEND` |

---

### 4.2 Step 6.2 — `tests/test_scope_gate.py` Implementation Spec

```python
# tests/test_scope_gate.py
import pytest
from core.types import ScopeRule, ScopeMatchType, TargetScope, Platform
from compliance.scope_gate import ScopeGate

@pytest.fixture
def setup_scope_gate():
    scope = TargetScope(
        program_handle="acme-corp",
        platform=Platform.HACKERONE,
        in_scope=[
            ScopeRule(pattern="api.acme.com", match_type=ScopeMatchType.EXACT),
            ScopeRule(pattern="*.acme.com", match_type=ScopeMatchType.WILDCARD),
            ScopeRule(pattern="192.168.1.0/24", match_type=ScopeMatchType.CIDR),
            ScopeRule(pattern=r"^app-\d+\.acme\.com$", match_type=ScopeMatchType.REGEX),
        ],
        out_of_scope=[
            ScopeRule(pattern="internal.acme.com", match_type=ScopeMatchType.EXACT)
        ]
    )
    return ScopeGate(scope)

def test_exact_domain_match(setup_scope_gate):
    assert setup_scope_gate.is_in_scope("api.acme.com") is True

def test_wildcard_match(setup_scope_gate):
    assert setup_scope_gate.is_in_scope("sub.acme.com") is True

def test_out_of_scope_override(setup_scope_gate):
    assert setup_scope_gate.is_in_scope("internal.acme.com") is False

def test_dns_rebinding_protection(setup_scope_gate):
    # Attempting to resolve local/internal IP addresses must be BLOCKED
    assert setup_scope_gate.is_ip_allowed("127.0.0.1") is False
    assert setup_scope_gate.is_ip_allowed("169.254.169.254") is False
    assert setup_scope_gate.is_ip_allowed("::1") is False

def test_cidr_matching(setup_scope_gate):
    assert setup_scope_gate.is_in_scope("192.168.1.50") is True
    assert setup_scope_gate.is_in_scope("192.168.2.50") is False

def test_websocket_scheme(setup_scope_gate):
    assert setup_scope_gate.is_in_scope("ws://api.acme.com/socket") is True
```

---

## 5. Phase 7 Specification: Qwen3.8-27B LOCAL_HEAVY FastMTP Integration

Phase 7 incorporates Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP served via `llama-server` as a `LOCAL_HEAVY` reasoning backend for deep offensive tasks, complementing Groq 70B and reducing API costs.

### 5.1 Hardware Deployment Profiles

```
Workstation Deployment (Profile E)
┌─────────────────────────────────────────────────────────────┐
│ Operator Workstation (24–48 GB VRAM: RTX 4090 / A6000)      │
│  - llama-server --model Q4_K_P.gguf (17.92 GB)              │
│  - --spec-draft-model FastMTP-32K.gguf (903 MB)             │
│  - Endpoint: http://127.0.0.1:8090                           │
└─────────────────────────────────────────────────────────────┘

Cloud GPU Bursting (Profile F)
┌──────────────────────────────┐        VPN / HTTPS         ┌──────────────────────────────┐
│ Local Laptop                 │ ─────────────────────────► │ Cloud GPU (RunPod / Vast.ai) │
│ - Harness Control Plane      │                            │ - RTX 4090 / L40S ($0.35/hr) │
│ - Egress Proxy (:8080)       │                            │ - llama-server on :8090      │
└──────────────────────────────┘                            └──────────────────────────────┘
```

---

### 5.2 Step 7.2 — `core/config.py` Extension

Add configuration parameters to `HarnessConfig`:

```python
# core/config.py additions
@dataclass
class HarnessConfig:
    # Existing fields...
    local_heavy_enabled: bool = False
    local_heavy_url: str = "http://127.0.0.1:8090"
    local_heavy_hourly_cost: float = 0.35  # Cloud GPU rate per hour ($)

    @classmethod
    def load_from_env(cls) -> "HarnessConfig":
        # Load env vars...
        cfg.local_heavy_enabled = os.getenv("HARNESS_LOCAL_HEAVY_ENABLED", "false").lower() == "true"
        cfg.local_heavy_url = os.getenv("HARNESS_LOCAL_HEAVY_URL", "http://127.0.0.1:8090")
        cfg.local_heavy_hourly_cost = float(os.getenv("HARNESS_LOCAL_HEAVY_HOURLY_COST", "0.35"))
        return cfg
```

---

### 5.3 Step 7.3 — `budget/model_router.py` LOCAL_HEAVY Extension

Update tier enums and task allocation table in `budget/model_router.py`:

```python
# budget/model_router.py additions

class ModelTier(str, Enum):
    LOCAL_LIGHT = "LOCAL_LIGHT"  # Laptop 3-8B (Ollama)
    LOCAL_HEAVY = "LOCAL_HEAVY"  # Qwen3.8-27B Aggressive FastMTP (llama-server)
    PAID_FREE = "PAID_FREE"      # Groq 70B
    PAID_PREMIUM = "PAID_PREMIUM" # GPT-4o / Claude Sonnet

# Revised routing assignments for heavy offensive reasoning tasks
MODEL_ROUTING_TABLE.update({
    "ideation_deep":        {"tier": "LOCAL_HEAVY", "model": "qwen3.8-27b-aggressive-q4-local"},
    "payload_polyglot":     {"tier": "LOCAL_HEAVY", "model": "qwen3.8-27b-aggressive-q4-local"},
    "ai_jailbreak_confirm": {"tier": "LOCAL_HEAVY", "model": "qwen3.8-27b-aggressive-q4-local"},
    "chain_analysis":       {"tier": "LOCAL_HEAVY", "model": "qwen3.8-27b-aggressive-q4-local"},
})

# Fallback chain prioritizing LOCAL_HEAVY -> PAID_FREE -> PAID_PREMIUM
FALLBACK_CHAIN[ModelTier.LOCAL_HEAVY] = [ModelTier.PAID_FREE, ModelTier.PAID_PREMIUM]
```

---

### 5.4 Step 7.4 & 7.6 — TokenTracker & Compliance Passthrough

1. **TokenTracker Metrics:** Track LOCAL_HEAVY invocation count and compute estimated session cost using `(local_heavy_invocations * average_latency_sec / 3600) * local_heavy_hourly_cost`.
2. **Egress Proxy Exemption Rule:** `compliance/egress_proxy.py` must bypass scope enforcement for outbound traffic directed to `local_heavy_url` (e.g. `http://127.0.0.1:8090` or cloud IP), treating LLM inference calls as internal infrastructure while forcing all target application traffic through `ScopeGate`.

---

## 6. Implementation Sequence & Execution Roadmap

To complete the harness assembly without regression, follow this strict step-by-step execution sequence:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        EXECUTION SEQUENCE                              │
├────────────────────────────────────────────────────────────────────────┤
│ Step 1: Complete Phase 4B Tool Adaptations                             │
│   ├── Modify adhd/src/engine.ts (Tokens & FP search)                   │
│   ├── Modify claude-bug-bounty (agent, engine, brain, memory)          │
│   └── Modify jsleak/main.go (Proxy & JSON output)                      │
│                                                                        │
│ Step 2: Implement Phase 5 Orchestration & Reporting                    │
│   ├── Write reporting/taxonomy.py (VRT/CWE/CVSS & templates)           │
│   ├── Write orchestrator/admiral.py (FastAPI REST & WebSocket)         │
│   ├── Write main.py (CLI commands: init, run, stop)                    │
│   └── Update T3MP3ST server.ts & docs (Gauges, Badges, Modals)         │
│                                                                        │
│ Step 3: Implement Phase 6 Test Suite & Dry-Run Validation              │
│   ├── Write tests/test_scope_gate.py                                   │
│   ├── Write tests/test_osint_exemption.py                              │
│   ├── Write tests/test_taxonomy.py                                     │
│   └── Write tests/test_mock_e2e.py                                     │
│                                                                        │
│ Step 4: Implement Phase 7 Qwen3.8-27B LOCAL_HEAVY Integration         │
│   ├── Extend core/config.py & budget/model_router.py                   │
│   ├── Update budget/token_tracker.py (GPU-hour metrics)                │
│   └── Configure egress proxy loopback exemptions                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 6.1 Verification & Gate Check Commands

Execute these verification commands sequentially to validate each completed phase:

```bash
# 1. Verify Phase 4 Specialist & Tool Imports
python3 -c "
from agents.specialist_base import ISpecialist, OOBMixin
from agents.specialists.sqli_specialist import SQLiSpecialist
print('Phase 4 Specialist Base PASS')
"

# 2. Verify Phase 5 Orchestration Server
python3 -m uvicorn orchestrator.admiral:app --port 8001 &
ADMIRAL_PID=$!
sleep 2
curl -s http://127.0.0.1:8001/api/v1/status | python3 -m json.tool
kill $ADMIRAL_PID
echo "Phase 5 OpAdmiral PASS"

# 3. Execute Phase 6 Test Suite
python3 -m pytest tests/ -v

# 4. Verify Phase 7 ModelRouter & LOCAL_HEAVY Config
python3 -c "
from budget.model_router import ModelRouter, ModelTier
from core.config import HarnessConfig
cfg = HarnessConfig(local_heavy_enabled=True)
router = ModelRouter(cfg)
print('Phase 7 LOCAL_HEAVY Router PASS')
"
```

---

## 7. Document Revision History

| Version | Date | Description of Changes | Author |
|---|---|---|---|
| **2.1.0** | 2026-09-01 | Initial architecture & component design | Lead Security Architect |
| **2.1.1** | 2026-09-04 | Added specialist swarm details & token budget rules | Lead Systems Engineer |
| **2.1.2** | 2026-09-06 | Incorporated Qwen3.8-27B FastMTP integration, 4-tier model router, complete gap-bridging spec for Phases 4B, 5, 6, and 7 | Lead AI & Security Architect |
