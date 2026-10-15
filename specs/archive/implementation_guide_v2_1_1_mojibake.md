# Bug Bounty Harness â€” Step-by-Step Implementation Guide

**Companion to:** [`bug_bounty_harness_design_v2_1.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/bug_bounty_harness_design_v2_1.md)  
**Purpose:** Exact, step-by-step instructions for each implementation phase so you and the AI agent share clear vision.  
**How to use:** Work through phases **in order**. Each step has a checkbox. Hand each step (or group of steps) to the AI agent as a task prompt.

---

## Workspace Root

```
/home/souhail/Desktop/Desktop/Ult_harness/
```

---

## Pre-Flight: Environment Setup

Before starting any phase, ensure these tools are installed and working.

- [ ] **Step 0.1** â€” Verify Python â‰¥ 3.10
  ```bash
  python3 --version  # expect 3.10+
  ```

- [ ] **Step 0.2** â€” Verify Node.js â‰¥ 18
  ```bash
  node --version  # expect v18+
  ```

- [ ] **Step 0.3** â€” Verify Go â‰¥ 1.21
  ```bash
  go version  # expect go1.21+
  ```

- [ ] **Step 0.4** â€” Verify Ollama is installed and GPU-detected
  ```bash
  ollama --version
  ollama run qwen2.5-coder:7b "hello" --verbose 2>&1 | grep gpu
  ```

- [ ] **Step 0.5** â€” Verify mitmproxy is available
  ```bash
  mitmdump --version  # expect 10+
  ```

- [ ] **Step 0.6** â€” Verify NVIDIA drivers + CUDA
  ```bash
  nvidia-smi  # should show RTX 4050, CUDA 12.4
  ```

---

## Phase 0: Core Types & Package Foundation

**Goal:** Create the shared Python package skeleton that every later module imports from.  
**Duration estimate:** 30â€“45 minutes  
**Dependencies:** None (first phase)

### Folder Tree After Phase 0

```
Ult_harness/
â”œâ”€â”€ core/
â”‚   â”œâ”€â”€ __init__.py              â† NEW (empty, makes core a package)
â”‚   â”œâ”€â”€ types.py                 â† NEW (all dataclasses + enums)
â”‚   â”œâ”€â”€ config.py                â† NEW (HarnessConfig loader)
â”‚   â””â”€â”€ event_bus.py             â† NEW (IEventBus + InMemoryEventBus)
â”œâ”€â”€ pyproject.toml               â† NEW (root Python package config)
â”‚
â”œâ”€â”€ Agent-Reach/                 (existing, untouched)
â”œâ”€â”€ Awesome-Redteam/             (existing, untouched)

â”œâ”€â”€ CL4R1T4S/                    (existing, untouched)
â”œâ”€â”€ T3MP3ST/                     (existing, untouched)
â”œâ”€â”€ adhd/                        (existing, untouched)
â”œâ”€â”€ claude-bug-bounty/           (existing, untouched)
â”œâ”€â”€ jsleak/                      (existing, untouched)
â””â”€â”€ mempalace/                   (existing, untouched)
```

### Steps

- [ ] **Step 0.1** â€” Create `pyproject.toml`
  - **File:** `/home/souhail/Desktop/Desktop/Ult_harness/pyproject.toml`
  - **Action:** WRITE new file
  - **Content:** Copy the spec from v2.1.1 Â§4.3 exactly. Key points:
    - `name = "ult_harness"`, `version = "2.1.1"`
    - `requires-python = ">=3.10"`
    - Dependencies: `fastapi`, `uvicorn`, `pydantic`, `requests`, `aiohttp`, `mitmproxy`, `chromadb`, `pyyaml`, `cvss`
    - Package find includes only: `core*`, `compliance*`, `budget*`, `triage*`, `reporting*`, `sessions*`, `agents*`, `orchestrator*`
  - **Verify:**
    ```bash
    cd /home/souhail/Desktop/Desktop/Ult_harness
    pip install -e . --dry-run  # should resolve without errors
    ```

- [ ] **Step 0.2** â€” Create `core/__init__.py`
  - **File:** `core/__init__.py`
  - **Action:** WRITE empty file (just makes `core` a Python package)

- [ ] **Step 0.3** â€” Create `core/types.py`
  - **File:** `core/types.py`
  - **Action:** WRITE new file
  - **Content:** Full skeleton from v2.1.1 Â§4.0. Must define these types:

    | Type | Kind | Key Fields |
    |---|---|---|
    | `Platform` | `str, Enum` | `HACKERONE`, `BUGCROWD`, `YESWEHACK`, `INTIGRITI`, `IMMUNEFI` |
    | `ScopeMatchType` | `str, Enum` | `EXACT`, `WILDCARD`, `CIDR`, `REGEX` |
    | `VulnCategory` | `str, Enum` | All 16 specialist categories |
    | `VulnStatus` | `str, Enum` | `IDENTIFIED`, `VALIDATING`, `CONFIRMED`, `FALSE_POSITIVE`, `CHAINED`, `OUT_OF_SCOPE` |
    | `ScopeRule` | `dataclass` | `pattern`, `match_type`, `description` |
    | `TargetScope` | `dataclass` | `program_handle`, `platform`, `in_scope[]`, `out_of_scope[]`, `rate_limit_rps`, `max_concurrent` |
    | `PlatformHeaders` | `dataclass` | `headers{}`, `user_agent`, `for_platform()` classmethod |
    | `MultiSessionContext` | `dataclass` | `user_a_headers`, `user_b_headers`, `admin_headers`, `unauth_headers` |
    | `TokenBudget` | `dataclass` | `warning_threshold`, `hard_cap`, `tokens_used`, `cost_usd`, `remaining` property |
    | `Task` | `dataclass` | `task_id`, `wing_id`, `specialist_id`, `correlation_id`, `target_endpoint`, `vuln_category`, `status` |
    | `OrchestrationEvent` | `dataclass` | `event_type`, `correlation_id`, `source_component`, `timestamp`, `payload` |

  - **Verify:**
    ```bash
    python3 -c "from core.types import Platform, TargetScope, Task; print('OK')"
    ```

- [ ] **Step 0.4** â€” Create `core/config.py`
  - **File:** `core/config.py`
  - **Action:** WRITE new file
  - **Content:** `HarnessConfig` dataclass from v2.1.1 Â§4.2
  - **Critical ports:**
    - `api_port = 8001` (admiral)
    - `mempalace_url = http://127.0.0.1:8000`
    - `egress_proxy_port = 8080`
    - `war_room_port = 3333`
  - **Verify:**
    ```bash
    python3 -c "from core.config import HarnessConfig; c = HarnessConfig.load_from_env(); print(f'API:{c.api_port}')"
    # expect: API:8001
    ```

- [ ] **Step 0.5** â€” Create `core/event_bus.py`
  - **File:** `core/event_bus.py`
  - **Action:** WRITE new file
  - **Content:** `IEventBus` abstract class + `InMemoryEventBus` from v2.1.1 Â§4.1
  - **Interface contract:**
    - `async publish(topic: str, event: OrchestrationEvent) -> None`
    - `subscribe(topic: str, callback) -> str` (returns subscription_id)
    - `unsubscribe(subscription_id: str) -> None`
  - **Verify:**
    ```bash
    python3 -c "
    import asyncio
    from core.event_bus import InMemoryEventBus
    from core.types import OrchestrationEvent
    bus = InMemoryEventBus()
    results = []
    async def handler(e): results.append(e.event_type)
    bus.subscribe('test', handler)
    asyncio.run(bus.publish('test', OrchestrationEvent(event_type='ping', correlation_id='x', source_component='test')))
    assert results == ['ping'], f'Expected [\"ping\"], got {results}'
    print('EventBus OK')
    "
    ```

- [ ] **Step 0.6** â€” Install the package in development mode
  ```bash
  cd /home/souhail/Desktop/Desktop/Ult_harness
  pip install -e .
  ```

### Phase 0 âœ… Gate Check
```bash
python3 -c "
from core.types import Platform, VulnCategory, Task, OrchestrationEvent
from core.config import HarnessConfig
from core.event_bus import InMemoryEventBus
print(f'Types: {len(VulnCategory)} categories')
print(f'Config: port {HarnessConfig.load_from_env().api_port}')
print(f'EventBus: {type(InMemoryEventBus()).__name__}')
print('Phase 0 PASSED')
"
```

---

## Phase 1: Layer 0 Platform Compliance & Egress Proxy

**Goal:** Build the compliance layer that prevents ALL out-of-scope traffic before any scanner runs.  
**Duration estimate:** 2â€“3 hours  
**Dependencies:** Phase 0 (imports from `core.types`)

### Folder Tree After Phase 1

```
Ult_harness/
â”œâ”€â”€ core/                        (from Phase 0)
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ types.py
â”‚   â”œâ”€â”€ config.py
â”‚   â””â”€â”€ event_bus.py
â”œâ”€â”€ compliance/                  â† NEW DIRECTORY
â”‚   â”œâ”€â”€ __init__.py              â† NEW
â”‚   â”œâ”€â”€ scope_gate.py            â† NEW (the policy engine)
â”‚   â”œâ”€â”€ egress_proxy.py          â† NEW (mitmproxy addon script)
â”‚   â”œâ”€â”€ header_injector.py       â† NEW (reads/generates platform headers)
â”‚   â”œâ”€â”€ scope_importer.py        â† NEW (H1 CSV, Bugcrowd JSON parsers)
â”‚   â””â”€â”€ oob_engine.py            â† NEW (Interactsh client)
â”œâ”€â”€ pyproject.toml               (from Phase 0)
â”‚
â”œâ”€â”€ (all 9 existing sub-folders, untouched)
```

### Steps

- [ ] **Step 1.1** â€” Create `compliance/__init__.py`
  - **Action:** WRITE empty file

- [ ] **Step 1.2** â€” Write `compliance/scope_gate.py`
  - **Action:** WRITE new file
  - **Purpose:** The core policy engine that decides ALLOW/DENY for every outbound request
  - **Must implement:**
    - `ScopeGate` class initialized with a `TargetScope` object
    - `is_in_scope(url: str) -> bool` method
    - Support for `ScopeMatchType.EXACT` (string compare), `WILDCARD` (fnmatch), `CIDR` (ipaddress module), `REGEX` (re module)
    - DNS Rebinding protection: block `127.0.0.1`, `169.254.169.254`, `::1`, `[::ffff:*]`, `0.0.0.0`, `localhost`, `metadata.google.internal`
    - WebSocket scheme support: `ws://` and `wss://` URLs are checked after converting to `http://` / `https://`
    - OSINT domain allowlist: configurable list of domains that are ALWAYS allowed (e.g., `api.twitter.com`, `api.github.com`, `oauth.reddit.com`)
    - Third-party exclusion: always block `stripe.com`, `okta.com`, `auth0.com`, `*.sentry.io`
  - **Input:** `core.types.TargetScope` from `scope_importer.py`
  - **Output:** Boolean ALLOW/DENY per URL
  - **Verify:**
    ```bash
    python3 -c "
    from compliance.scope_gate import ScopeGate
    from core.types import TargetScope, ScopeRule, ScopeMatchType, Platform
    scope = TargetScope(
        program_handle='test', platform=Platform.HACKERONE,
        in_scope=[ScopeRule(pattern='*.example.com', match_type=ScopeMatchType.WILDCARD)]
    )
    gate = ScopeGate(scope)
    assert gate.is_in_scope('https://app.example.com/api') == True
    assert gate.is_in_scope('https://evil.com') == False
    assert gate.is_in_scope('http://127.0.0.1') == False  # DNS rebinding blocked
    assert gate.is_in_scope('https://api.twitter.com') == True  # OSINT allowed
    print('ScopeGate OK')
    "
    ```

- [ ] **Step 1.3** â€” Write `compliance/egress_proxy.py`
  - **Action:** WRITE new file
  - **Purpose:** mitmproxy addon script that plugs `ScopeGate` into live HTTP traffic
  - **Must implement:**
    - `request(flow)` hook that calls `ScopeGate.is_in_scope(flow.request.pretty_url)`
    - If DENIED: set `flow.response = http.Response.make(403, b"Out of scope", {"Content-Type": "text/plain"})`
    - If `--dry-run` mode (read from env `HARNESS_DRY_RUN`): log `[DRY-RUN WOULD ALLOW]` or `[DRY-RUN WOULD DROP]` but return mock `200`/`403` without killing the flow
    - Strip `X-Harness-Traffic` header from ALL outbound requests
    - OSINT defense-in-depth: if destination is NOT in OSINT allowlist but header IS present â†’ drop + log security warning
    - Log all decisions as JSON Lines to `./workspace/<wing_id>/logs/egress_proxy.jsonl`
    - Passive CDN allowlist: `fonts.googleapis.com`, `cdn.jsdelivr.net`, etc. â†’ log as passive, don't drop
  - **Will be launched by `main.py` as:** `subprocess.Popen(["mitmdump", "-s", "compliance/egress_proxy.py", "-p", "8080"])`
  - **Verify:**
    ```bash
    # Start the proxy in dry-run mode
    HARNESS_DRY_RUN=true mitmdump -s compliance/egress_proxy.py -p 8080 &
    sleep 2
    # Test against an in-scope URL (assuming *.example.com scope)
    curl -x http://127.0.0.1:8080 http://example.com/ 2>&1
    # Check logs
    kill %1
    ```

- [ ] **Step 1.4** â€” Write `compliance/scope_importer.py`
  - **Action:** WRITE new file
  - **Content:** Copy from v2.1.1 Â§4.4. Implements:
    - `ScopeImporter.parse_hackerone_csv(file_path, program_handle) -> TargetScope`
    - `ScopeImporter.parse_bugcrowd_json(file_path, program_handle) -> TargetScope`
    - Future: `parse_yeswehack()`, `parse_intigriti()` stubs
  - **Verify:**
    ```bash
    # Create a test CSV
    echo 'asset_identifier,asset_type,eligible_for_bounty
    *.example.com,URL,true
    staging.internal.com,URL,false' > /tmp/test_scope.csv

    python3 -c "
    from compliance.scope_importer import ScopeImporter
    scope = ScopeImporter.parse_hackerone_csv('/tmp/test_scope.csv', 'test-prog')
    print(f'In-scope: {len(scope.in_scope)}, Out-of-scope: {len(scope.out_of_scope)}')
    assert len(scope.in_scope) == 1
    print('ScopeImporter OK')
    "
    ```

- [ ] **Step 1.5** â€” Write `compliance/header_injector.py`
  - **Action:** WRITE new file
  - **Purpose:** Reads `platform_profile.json`, generates a flat headers file for Go tools, and provides a Python API for other modules
  - **Must implement:**
    - `HeaderInjector.from_profile(profile_path: str)` â€” loads `platform_profile.json`
    - `get_headers() -> Dict[str, str]` â€” returns the merged headers dict
    - `export_headers_file(output_path: str)` â€” writes a `key: value` text file that Go tools can read via `HARNESS_HEADERS_FILE`
    - Rate limiter: `async with rate_limit():` context manager that enforces `rate_limit_rps` from profile

- [ ] **Step 1.6** â€” Write `compliance/oob_engine.py`
  - **Action:** WRITE new file
  - **Purpose:** Wrapper around Interactsh client for OOB callback detection
  - **Must implement:**
    - `OOBEngine(mode: str)` â€” `"public"` uses `oast.me` / `oast.fun`; `"selfhosted"` uses configured URL
    - `generate_payload() -> str` â€” returns a unique Interactsh URL for embedding in payloads
    - `async poll_callbacks() -> List[OOBCallback]` â€” polls for DNS/HTTP/SMTP interactions
    - `close()` â€” deregisters the Interactsh session
  - **Dependencies:** `interactsh-py` (add to `pyproject.toml` dependencies if not yet listed)

### Phase 1 âœ… Gate Check
```bash
python3 -c "
from compliance.scope_gate import ScopeGate
from compliance.scope_importer import ScopeImporter
from compliance.header_injector import HeaderInjector
from compliance.oob_engine import OOBEngine
print('All compliance modules import successfully')
print('Phase 1 PASSED')
"
```

---

## Phase 2: Memory Storage & Reference Ingestion

**Goal:** Extend mempalace with harness-specific tables and ingest static reference data.  
**Duration estimate:** 1.5â€“2 hours  
**Dependencies:** Phase 0 (types), Phase 1 (scope types)



### Folder Tree After Phase 2

```
Ult_harness/
â”œâ”€â”€ core/                        (from Phase 0)
â”œâ”€â”€ compliance/                  (from Phase 1)
â”œâ”€â”€ scripts/                     â† NEW DIRECTORY
â”‚   â”œâ”€â”€ ingest_awesome_redteam.py â† NEW
â”‚   â””â”€â”€ ingest_cl4r1tas.py        â† NEW
â”œâ”€â”€ pyproject.toml
â”‚
â”œâ”€â”€ mempalace/                   (MODIFIED)
â”‚   â””â”€â”€ mempalace/
â”‚       â”œâ”€â”€ backends/
â”‚       â”‚   â”œâ”€â”€ sqlite_exact.py  â† TWEAKED (new tables added)
â”‚       â”‚   â””â”€â”€ chroma.py        (untouched)
â”‚       â”œâ”€â”€ mcp_server.py        â† TWEAKED (new endpoints)
â”‚       â””â”€â”€ cli.py               â† TWEAKED (new commands)
â”‚
â”œâ”€â”€ (other existing sub-folders)
```

### Steps

- [ ] **Step 2.1** â€” Tweak `mempalace/mempalace/backends/sqlite_exact.py`
  - **Action:** TWEAK existing file
  - **What to add:** New table creation SQL in the schema init method. Add these tables:
    - `scopes` â€” stores parsed `TargetScope` rules per program
    - `oob_callbacks` â€” stores Interactsh OOB interaction records
    - `taxonomy_mappings` â€” VRT â†’ CWE â†’ CVSS lookup cache
    - `dual_session_tests` â€” results of IDOR/BAC 4-session matrix tests
    - `token_usage` â€” per-agent, per-task token consumption log
    - `noise_filter_log` â€” records of issues auto-dropped by noise filter
    - `false_positive_patterns` â€” learned FP patterns to prevent re-testing
  - **Do NOT:** Remove or modify existing tables / methods
  - **Verify:**
    ```bash
    python3 -c "
    import sqlite3, tempfile, os
    from mempalace.mempalace.backends.sqlite_exact import SQLiteExactBackend
    db = SQLiteExactBackend(os.path.join(tempfile.mkdtemp(), 'test.db'))
    print('mempalace schema updated OK')
    "
    ```

- [ ] **Step 2.2** â€” Tweak `mempalace/mempalace/mcp_server.py`
  - **Action:** TWEAK existing file
  - **What to add:**
    - `search_fp_patterns(vuln_category: str, endpoint_pattern: str) -> List[FPPattern]` â€” returns known false positive patterns
    - `record_token_usage(agent_id: str, task_id: str, tokens: int, cost_usd: float)` â€” logs token consumption
    - `get_token_summary(wing_id: str) -> Dict` â€” returns aggregate token usage per agent
  - **Do NOT:** Remove or modify existing MCP tools

- [ ] **Step 2.3** â€” Tweak `mempalace/mempalace/cli.py`
  - **Action:** TWEAK existing file
  - **What to add:** CLI subcommands:
    - `mempalace fp-patterns --category sqli`
    - `mempalace token-report --wing <id>`
    - `mempalace scope-check --url <url> --program <handle>`

- [ ] **Step 2.4** â€” Write `scripts/ingest_awesome_redteam.py`
  - **File:** `scripts/ingest_awesome_redteam.py`
  - **Action:** WRITE new file
  - **Purpose:** Parses Markdown files in `Awesome-Redteam/cheatsheets/` and `tips/` and loads them into mempalace
  - **Verify:**
    ```bash
    python3 scripts/ingest_awesome_redteam.py --dry-run
    ```

- [ ] **Step 2.5** â€” Write `scripts/ingest_cl4r1tas.py`
  - **File:** `scripts/ingest_cl4r1tas.py`
  - **Action:** WRITE new file
  - **Purpose:** Loads CL4R1T4S system prompts into mempalace as reference material

### Phase 2 âœ… Gate Check
```bash
python3 -c "
from mempalace.mempalace.backends.sqlite_exact import SQLiteExactBackend
print('mempalace imports OK')
"
python3 scripts/ingest_awesome_redteam.py --dry-run
python3 scripts/ingest_cl4r1tas.py --dry-run
echo "Phase 2 PASSED"
```

---

## Phase 3: Budget Routing, Triage & Session Management

**Goal:** Build the cost control, finding triage, and multi-session authentication layers.  
**Duration estimate:** 2â€“3 hours  
**Dependencies:** Phase 0 (types, config), Phase 2 (mempalace token_usage table)

### Folder Tree After Phase 3

```
Ult_harness/
â”œâ”€â”€ core/                        (from Phase 0)
â”œâ”€â”€ compliance/                  (from Phase 1)
â”œâ”€â”€ scripts/                     (from Phase 2)
â”œâ”€â”€ budget/                      â† NEW DIRECTORY
â”‚   â”œâ”€â”€ __init__.py              â† NEW
â”‚   â”œâ”€â”€ token_tracker.py         â† NEW
â”‚   â””â”€â”€ model_router.py          â† NEW
â”œâ”€â”€ triage/                      â† NEW DIRECTORY
â”‚   â”œâ”€â”€ __init__.py              â† NEW
â”‚   â”œâ”€â”€ noise_filter.py          â† NEW
â”‚   â””â”€â”€ state_machine.py         â† NEW
â”œâ”€â”€ sessions/                    â† NEW DIRECTORY
â”‚   â”œâ”€â”€ __init__.py              â† NEW
â”‚   â””â”€â”€ session_manager.py       â† NEW
â”œâ”€â”€ pyproject.toml
â”‚
â”œâ”€â”€ (existing sub-folders, mempalace tweaked in Phase 2)
```

### Steps

- [ ] **Step 3.1** â€” Create `budget/__init__.py`

- [ ] **Step 3.2** â€” Write `budget/token_tracker.py`
  - **Must implement:**
    - `TokenTracker` class holding `Dict[str, TokenBudget]` keyed by agent_id
    - `record_usage(agent_id, task_id, input_tokens, output_tokens, model)` â†’ updates counters, logs to mempalace
    - `get_agent_budget(agent_id) -> TokenBudget`
    - `get_wing_summary(wing_id) -> Dict`
    - `is_budget_exhausted(agent_id) -> bool`
    - Cost table: model â†’ price/token
  - **Emits:** `budget_warning` event when `tokens_used > warning_threshold`
  - **Emits:** `budget_exhausted` event when hard cap hit

- [ ] **Step 3.3** â€” Write `budget/model_router.py`
  - **Must implement:**
    - `ModelRouter(config, tracker)` with `async route(prompt, task_tier) -> LLMResponse`
    - **Tiers:** `LOCAL` (Ollama $0) â†’ `PAID_FREE` (Groq $0) â†’ `PAID_PREMIUM` (OpenAI/Anthropic $$)
    - **Startup health check:** `GET /api/tags` on Ollama; if down, promote LOCAL â†’ PAID_FREE + warn
    - **Fallback chain:** LOCAL â†’ PAID_FREE â†’ PAID_PREMIUM â†’ `NoBudgetError`

- [ ] **Step 3.4** â€” Create `triage/__init__.py`

- [ ] **Step 3.5** â€” Write `triage/noise_filter.py`
  - **Auto-drops:** missing headers, SPF/DMARC, self-XSS, rate-limit absence, cookie flags
  - **Returns:** `FilterResult(passed, reason, original_finding)`
  - **Logs:** all filtered findings to mempalace `noise_filter_log`

- [ ] **Step 3.6** â€” Write `triage/state_machine.py`
  - **States:** `IDENTIFIED â†’ VALIDATING â†’ CONFIRMED / FALSE_POSITIVE / CHAINED / OUT_OF_SCOPE`
  - `async transition(task, new_status, evidence)` publishes events to `EventBus`

- [ ] **Step 3.7** â€” Create `sessions/__init__.py`

- [ ] **Step 3.8** â€” Write `sessions/session_manager.py`
  - **Content from v2.1.1 Â§4.5** with `_token_refresh_loop()` (25-min interval)
  - **Verify:**
    ```bash
    python3 -c "from sessions.session_manager import SessionManager; print('OK')"
    ```

### Phase 3 âœ… Gate Check
```bash
python3 -c "
from budget.token_tracker import TokenTracker
from budget.model_router import ModelRouter
from triage.noise_filter import NoiseFilter
from triage.state_machine import TriageStateMachine
from sessions.session_manager import SessionManager
print('Phase 3 PASSED')
"
```

---

## Phase 4: Specialist Swarm & Engine Adaptation

**Goal:** Build the 16 specialist agents AND adapt the existing TypeScript/Go/Python tools.  
**Duration estimate:** 4â€“6 hours (largest phase)  
**Dependencies:** Phase 0â€“3 (all foundation layers)

### Folder Tree After Phase 4

```
Ult_harness/
â”œâ”€â”€ core/                        (from Phase 0)
â”œâ”€â”€ compliance/                  (from Phase 1)
â”œâ”€â”€ scripts/                     (from Phase 2)
â”œâ”€â”€ budget/                      (from Phase 3)
â”œâ”€â”€ triage/                      (from Phase 3)
â”œâ”€â”€ sessions/                    (from Phase 3)
â”œâ”€â”€ agents/                      â† NEW DIRECTORY
â”‚   â”œâ”€â”€ __init__.py              â† NEW
â”‚   â”œâ”€â”€ specialist_base.py       â† NEW (base class)
â”‚   â”œâ”€â”€ dual_session_tester.py   â† NEW (IDOR/BAC matrix)
â”‚   â””â”€â”€ specialists/             â† NEW DIRECTORY
â”‚       â”œâ”€â”€ __init__.py          â† NEW
â”‚       â”œâ”€â”€ sqli_specialist.py   â† NEW
â”‚       â”œâ”€â”€ xss_specialist.py    â† NEW
â”‚       â”œâ”€â”€ ssrf_specialist.py   â† NEW (OOB mixin)
â”‚       â”œâ”€â”€ idor_specialist.py   â† NEW (dual-session)
â”‚       â”œâ”€â”€ lfi_specialist.py    â† NEW
â”‚       â”œâ”€â”€ rce_specialist.py    â† NEW (OOB mixin)
â”‚       â”œâ”€â”€ xxe_specialist.py    â† NEW (OOB mixin)
â”‚       â”œâ”€â”€ jwt_specialist.py    â† NEW
â”‚       â”œâ”€â”€ open_redirect_specialist.py  â† NEW
â”‚       â”œâ”€â”€ prototype_pollution_specialist.py â† NEW
â”‚       â”œâ”€â”€ csti_specialist.py   â† NEW
â”‚       â”œâ”€â”€ mass_assignment_specialist.py â† NEW
â”‚       â”œâ”€â”€ header_injection_specialist.py â† NEW
â”‚       â”œâ”€â”€ bac_specialist.py    â† NEW (dual-session)
â”‚       â”œâ”€â”€ ai_jailbreak_specialist.py  â† NEW (CL4R1T4S)
â”‚       â””â”€â”€ business_logic_specialist.py â† NEW
â”œâ”€â”€ pyproject.toml
â”‚
â”œâ”€â”€ adhd/                        (TWEAKED: frames.ts, engine.ts)
â”œâ”€â”€ claude-bug-bounty/           (TWEAKED: agent.py, engine.py, brain.py, memory/*)
â”œâ”€â”€ jsleak/                      (TWEAKED: main.go)

â”œâ”€â”€ (other existing sub-folders)
```

### Steps â€” Part A: New Agent Code

- [ ] **Step 4.1** â€” Create `agents/__init__.py` and `agents/specialists/__init__.py`

- [ ] **Step 4.2** â€” Write `agents/specialist_base.py`
  - **Must implement:**
    - `class ISpecialist(ABC)` with:
      - `category: VulnCategory` (abstract property)
      - `async scan(target, scope, session_ctx) -> List[Finding]`
      - Auto `TokenTracker` integration per LLM call
      - Auto mempalace FP check before reporting findings
      - Structured JSON logging via `correlation_id`
    - `class OOBMixin`: adds `oob_engine` + `embed_oob_payload()` for SSRF/RCE/XXE
    - `class DualSessionMixin`: adds `session_ctx` access for IDOR/BAC

- [ ] **Step 4.3** â€” Write `agents/dual_session_tester.py`
  - **4-session matrix:** User A â†’ A's resource âœ… | User B â†’ A's resource âŒ (IDOR) | Admin â†’ A's resource âœ… | No auth â†’ A's resource âŒ (BAC)

- [ ] **Step 4.4** â€” Write all 16 specialists in `agents/specialists/`
  - Each extends `ISpecialist`, overrides `scan()`
  - OOB specialists (SSRF, RCE, XXE) also extend `OOBMixin`
  - Auth specialists (IDOR, BAC) also extend `DualSessionMixin`
  - AI Jailbreak loads CL4R1T4S from mempalace

### Steps â€” Part B: Tweak Existing Tools

- [ ] **Step 4.5** â€” Tweak `adhd/src/frames.ts`
  - **Add:** 6 security frames + HTTP POST token callback to `:8001/api/tokens/record`
  - **Do NOT:** Remove existing frames or modify core logic

- [ ] **Step 4.6** â€” Tweak `adhd/src/engine.ts`
  - **Add:** FP anti-pattern query to mempalace at `http://127.0.0.1:8000/search` before returning strategy

- [ ] **Step 4.7** â€” Tweak `claude-bug-bounty/agent.py`
  - **Route** LLM calls through `ModelRouter` at `http://127.0.0.1:8001/api/v1/llm/route`

- [ ] **Step 4.8** â€” Tweak `claude-bug-bounty/engine.py`
  - **Set** `HTTP_PROXY=http://127.0.0.1:8080` before outbound requests

- [ ] **Step 4.9** â€” Tweak `claude-bug-bounty/brain.py`
  - **Integrate** CL4R1T4S prompts from mempalace into prompt builder

- [ ] **Step 4.10** â€” Tweak `claude-bug-bounty/memory/` modules
  - `audit_log.py`, `pattern_db.py`, `rotation.py` â†’ redirect storage to mempalace

- [ ] **Step 4.11** â€” Deprecate `claude-bug-bounty/tools/scope_checker.py`
  - Add deprecation notice, redirect to `compliance.scope_gate`

- [ ] **Step 4.12** â€” Tweak `jsleak/main.go`
  - **Add:** `HTTP_PROXY` env var support + `-json` output flag
  - **If needed:** `go mod init github.com/user/jsleak`



### Phase 4 âœ… Gate Check
```bash
python3 -c "
from agents.specialist_base import ISpecialist, OOBMixin
from agents.specialists.sqli_specialist import SQLiSpecialist
from agents.specialists.ssrf_specialist import SSRFSpecialist
print('Phase 4 PASSED')
"
```

---

## Phase 5: Reporting, Orchestration & UI Consolidation

**Goal:** Build the central brain, report generator, and connect the War Room UI.  
**Duration estimate:** 3â€“4 hours  
**Dependencies:** Phase 0â€“4 (everything)

### Folder Tree After Phase 5

```
Ult_harness/
â”œâ”€â”€ core/                        (Phase 0)
â”œâ”€â”€ compliance/                  (Phase 1)
â”œâ”€â”€ scripts/                     (Phase 2)
â”œâ”€â”€ budget/                      (Phase 3)
â”œâ”€â”€ triage/                      (Phase 3)
â”œâ”€â”€ sessions/                    (Phase 3)
â”œâ”€â”€ agents/                      (Phase 4)
â”œâ”€â”€ reporting/                   â† NEW DIRECTORY
â”‚   â”œâ”€â”€ __init__.py              â† NEW
â”‚   â””â”€â”€ taxonomy.py              â† NEW
â”œâ”€â”€ orchestrator/                â† NEW DIRECTORY
â”‚   â”œâ”€â”€ __init__.py              â† NEW
â”‚   â”œâ”€â”€ admiral.py               â† NEW (the central brain)
â”‚   â””â”€â”€ cli_tunnel.py            â† NEW
â”œâ”€â”€ main.py                      â† NEW (entry point)
â”œâ”€â”€ pyproject.toml
â”‚
â”œâ”€â”€ T3MP3ST/                     (TWEAKED: server.ts, docs/index.html)
â”œâ”€â”€ (all other sub-folders)
```

### Steps

- [ ] **Step 5.1** â€” Create `reporting/__init__.py`

- [ ] **Step 5.2** â€” Write `reporting/taxonomy.py`
  - `TaxonomyMapper` with: `get_vrt()`, `get_cwe()`, `get_cvss_vector()`, `generate_report(finding, platform) -> str`
  - Platform-specific Markdown templates (H1, Bugcrowd, YWH)

- [ ] **Step 5.3** â€” Create `orchestrator/__init__.py`

- [ ] **Step 5.4** â€” Write `orchestrator/admiral.py` (**THE BRAIN**)
  - **FastAPI on port `8001`** with routes:
    - `POST /api/tokens/record` â€” token usage from adhd/agents
    - `POST /api/triage/callback` â€” fuzzer/scanner hits from claude-bug-bounty
    - `GET /api/v1/status` â€” wing status, active specialists, budget
    - `GET /api/v1/findings` â€” all findings with triage status
    - `POST /api/v1/findings/{id}/confirm` â€” operator confirms
    - `POST /api/v1/findings/{id}/reject` â€” operator rejects (FP + reason)
    - `WebSocket /ws` â€” bidirectional event stream for T3MP3ST
  - **On startup:** init EventBus, TokenTracker, ModelRouter, SessionManager, ScopeGate
  - **Dispatches** Tasks to specialists, enforces budget, forwards events to WS

- [ ] **Step 5.5** â€” Write `orchestrator/cli_tunnel.py`
  - Keyless local CLI session interceptor

- [ ] **Step 5.6** â€” Write `main.py`
  - `python main.py init --platform hackerone --program acme-corp` â†’ generates `workspace/acme-corp/platform_profile.json`
  - `python main.py run --program acme-corp [--dry-run]` â†’ boots all services:
    1. Spawn `mitmdump` (egress proxy `:8080`)
    2. Start mempalace if not running (`:8000`)
    3. Start OpAdmiral FastAPI (`:8001`)
    4. Bootstrap sessions
    5. Init TokenTracker + ModelRouter (Ollama health check)
    6. Load scope via ScopeImporter
    7. Ready for dispatch
  - `python main.py stop` â†’ graceful shutdown

- [ ] **Step 5.7** â€” Tweak `T3MP3ST/src/server.ts`
  - REST client fetching from `http://127.0.0.1:8001/api/v1/*`
  - WS client connecting to `ws://127.0.0.1:8001/ws`
  - Wire confirm/reject buttons to `POST /api/v1/findings/{id}/confirm|reject`

- [ ] **Step 5.8** â€” Tweak `T3MP3ST/docs/index.html`
  - Token budget gauge, OOB badges, confirm/reject modal with FP reason input

### Phase 5 âœ… Gate Check
```bash
python3 -m uvicorn orchestrator.admiral:app --port 8001 &
sleep 2
curl -s http://127.0.0.1:8001/api/v1/status | python3 -m json.tool
kill %1
echo "Phase 5 PASSED"
```

---

## Phase 6: Validation & Dry-Run Test Harness

**Goal:** Write tests that verify compliance, taxonomy, and dry-run mode work correctly.  
**Duration estimate:** 1.5â€“2 hours  
**Dependencies:** Phase 0â€“5 (everything)

### Folder Tree After Phase 6 (FINAL)

```
Ult_harness/
â”œâ”€â”€ core/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ types.py
â”‚   â”œâ”€â”€ config.py
â”‚   â””â”€â”€ event_bus.py
â”œâ”€â”€ compliance/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ scope_gate.py
â”‚   â”œâ”€â”€ egress_proxy.py
â”‚   â”œâ”€â”€ header_injector.py
â”‚   â”œâ”€â”€ scope_importer.py
â”‚   â””â”€â”€ oob_engine.py
â”œâ”€â”€ budget/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ token_tracker.py
â”‚   â””â”€â”€ model_router.py
â”œâ”€â”€ triage/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ noise_filter.py
â”‚   â””â”€â”€ state_machine.py
â”œâ”€â”€ reporting/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â””â”€â”€ taxonomy.py
â”œâ”€â”€ sessions/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â””â”€â”€ session_manager.py
â”œâ”€â”€ agents/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ specialist_base.py
â”‚   â”œâ”€â”€ dual_session_tester.py
â”‚   â””â”€â”€ specialists/
â”‚       â”œâ”€â”€ __init__.py
â”‚       â””â”€â”€ (16 specialist files)
â”œâ”€â”€ orchestrator/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ admiral.py
â”‚   â””â”€â”€ cli_tunnel.py
â”œâ”€â”€ tests/                       â† NEW DIRECTORY
â”‚   â”œâ”€â”€ __init__.py              â† NEW
â”‚   â”œâ”€â”€ test_scope_gate.py       â† NEW
â”‚   â”œâ”€â”€ test_osint_exemption.py  â† NEW
â”‚   â”œâ”€â”€ test_taxonomy.py         â† NEW
â”‚   â””â”€â”€ test_mock_e2e.py         â† NEW
â”œâ”€â”€ scripts/
â”‚   â”œâ”€â”€ ingest_awesome_redteam.py
â”‚   â””â”€â”€ ingest_cl4r1tas.py
â”œâ”€â”€ pyproject.toml
â”œâ”€â”€ main.py
â”‚
â”œâ”€â”€ Agent-Reach/                 (tweaked)
â”œâ”€â”€ Awesome-Redteam/             (untouched)

â”œâ”€â”€ CL4R1T4S/                    (untouched)
â”œâ”€â”€ T3MP3ST/                     (tweaked)
â”œâ”€â”€ adhd/                        (tweaked)
â”œâ”€â”€ claude-bug-bounty/           (tweaked)
â”œâ”€â”€ jsleak/                      (tweaked)
â””â”€â”€ mempalace/                   (tweaked)
```

### Steps

- [ ] **Step 6.1** â€” Create `tests/__init__.py`

- [ ] **Step 6.2** â€” Write `tests/test_scope_gate.py`
  - Tests: exact match, wildcard, out-of-scope, DNS rebinding (127.0.0.1, 169.254.169.254, ::1, localhost), CIDR, regex, ws:// scheme, third-party exclusions

- [ ] **Step 6.3** â€” Write `tests/test_osint_exemption.py`
  - Tests: OSINT domain allowed, non-OSINT + osint header â†’ dropped, header stripped, in-scope + osint header â†’ header stripped

- [ ] **Step 6.4** â€” Write `tests/test_taxonomy.py`
  - Tests: CWE mapping, VRT mapping, CVSS vector generation, H1/BC/YWH report format

- [ ] **Step 6.5** â€” Write `tests/test_mock_e2e.py`
  - Tests: dry-run allow/drop logs, no external traffic, full mock pipeline

### Phase 6 âœ… Gate Check
```bash
cd /home/souhail/Desktop/Desktop/Ult_harness
python3 -m pytest tests/ -v
echo "Phase 6 PASSED â€” HARNESS ASSEMBLY COMPLETE"
```

---

## Quick Reference: What to Tell the AI Agent

When handing a phase to the AI agent, use this template:

```
Implement Phase [N] of the Bug Bounty Harness per the implementation guide at:
/home/souhail/Desktop/Desktop/Ult_harness/implementation_guide.md

Architecture spec is at:
/home/souhail/Desktop/Desktop/Ult_harness/bug_bounty_harness_design_v2_1.md

Start with Step [N.1] and work through all steps in order.
Run the Phase [N] Gate Check before marking complete.
```

---

## Phase Dependency Graph

```
Phase 0 â”€â”€â–º Phase 1
         â”€â”€â–º Phase 2
         â”€â”€â–º Phase 3
                     â”€â”€â–º Phase 4 (needs 1 + 2 + 3)
                              â”€â”€â–º Phase 5 (needs 0â€“4)
                                       â”€â”€â–º Phase 6 (needs 0â€“5)
```

---

## Total Estimated Duration

| Phase | Effort | Cumulative |
|---|---|---|
| Pre-Flight | 15 min | 15 min |
| Phase 0 | 30â€“45 min | ~1 hr |
| Phase 1 | 2â€“3 hrs | ~4 hrs |
| Phase 2 | 1.5â€“2 hrs | ~6 hrs |
| Phase 3 | 2â€“3 hrs | ~9 hrs |
| Phase 4 | 4â€“6 hrs | ~14 hrs |
| Phase 5 | 3â€“4 hrs | ~18 hrs |
| Phase 6 | 1.5â€“2 hrs | **~20 hrs total** |
