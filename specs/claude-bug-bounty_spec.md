# Bug Bounty Harness Integration Specification: claude-bug-bounty (BugHunter)

## 1. System Overview
`claude-bug-bounty` (commercially referred to as **BugHunter**) is an AI-powered bug bounty hunting framework designed to automate the entire lifecycle of a bug bounty engagement: from initial domain discovery to active vulnerability hunting, proof-of-concept validation, and reporting. 

It can operate either as a plugin for **Claude Code** or as a standalone CLI (`bughunter`) that leverages local or remote LLM providers (Ollama, Groq, DeepSeek, OpenAI, etc.).

---

## 2. Architectural Analysis

### Tech Stack
- **Core Logic**: Python 3.9+
- **Agent Orchestration**: LangGraph (for graph-based state, checkpoints, and parallel subgraphs) with a custom Python ReAct (Reason-Action-Observation) loop fallback.
- **LLM Integration**: `langchain-ollama`, native `ollama` client library, and API endpoints for Groq, DeepSeek, Anthropic, and OpenAI.
- **Underlying Scanning Subsystem**: Wrapper scripts driving standard offensive security tools:
  - Active scanners & fuzzers: `nmap`, `httpx`, `nuclei`, `ffuf`, `amass`, `subfinder` (via Homebrew).
  - Web & parameters collectors: `gau` (Go URL gatherer), `dalfox` (XSS scanner), `subjack` (Subdomain takeover).

### File Structure & Components
- [`agent.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/claude-bug-bounty/agent.py): Implements the primary LangGraph or custom ReAct agent loop. Manages short-term working memory, finding logs, and session persistence.
- [`engine.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/claude-bug-bounty/engine.py): Serves as the standalone CLI gateway. Exposes high-level commands (`recon`, `hunt`, `validate`, `report`, `chain`, `triage`, `chat`).
- [`brain.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/claude-bug-bounty/brain.py): Handles model priority logic, provider detection, and prompt building.
- [`tools/`](file:///home/souhail/Desktop/Desktop/Ult_harness/claude-bug-bounty/tools/): Folder containing individual security wrapper scripts:
  - `param_discovery.sh`: Parameter mapping.
  - `zendesk_idor_test.py`: Target-specific logic (e.g. Zendesk).
  - `multipart_mutator.py`: Payload generation.
  - `wordlist_engine.sh`: Custom wordlist generator.
- `install_tools.sh` & `install.sh`: Automation scripts to install system binaries and set up local execution environments.

### Data Flow & Memory
1. **Divergence / Recon Phase**: Shell scripts run OSINT and scanning, writing output to files in the `recon/` folder.
2. **Analysis / Reasoning**: The LLM reads structured findings, updates its `working_memory` (compressed every 5 steps to save context token space), and appends verified findings to `findings_log`.
3. **Validation (7-Question Gate)**: The agent runs targeted exploits and queries the target to verify findings against a strict threshold (eliminating false positives).
4. **Persistence**: State is dumped to a JSON session file to allow resuming scans.

---

## 3. Role in the Unified Harness
In the combined harness, `claude-bug-bounty` acts as the **Core Execution Agent & Orchestrator**. 
- It wraps standard security binaries (subfinder, nuclei, etc.).
- It provides the user interface for running scans, triaging findings, and generating formatted vulnerability reports (HackerOne/Bugcrowd formats).
- It consumes output from recon steps to plan targeted exploit runs.

---

## 4. Optimal Bug Bounty Use Cases
- **Autonomous Target Scanning**: Initiating an automated assessment of a newly targeted root domain (`bughunter hunt target.com`) where the agent runs sub-domain discovery, selects high-value HTTP ports, and executes targeted checks.
- **Exploit Chain Modeling**: Combining a low-severity Open Redirect with a CSRF vulnerability to demonstrate a full account takeover via the `bughunter chain` logic.
- **Report Ingestion & Formatting**: Feeding raw, unstructured vulnerability logs into `bughunter report` to produce markdown/HTML reports ready for submission, mapping findings to CVSS scores and remediation steps.
- **Offline / Low-Cost Assessments**: Running locally via Ollama (`qwen2.5:14b`) to inspect sensitive source code or internal corporate assets without exfiltrating data to external LLM providers.

---

## 5. Harness Merging & Combination Strategy
To merge `claude-bug-bounty` with the other components in the workspace:
1. **With `jsleak`**: Modify the Python tools folder inside `claude-bug-bounty` to introduce a Go wrapper tool that calls `jsleak`. When `bughunter recon` gathers JavaScript endpoints, it should pipe them into `jsleak` to extract keys, API tokens, and secondary paths, which are fed back to the core agent as raw observations.
2. **With `mempalace`**: Replace the basic JSON session file persistence in `agent.py` with `mempalace`'s ChromaDB/SQLite semantic vector memory. This will allow the hunting agent to query past target findings, historical parameters, and exploit templates semantically, bypassing context limits.
3. **With `adhd`**: Wire the parallel reasoning frame logic of `adhd` into `agent.py`. Instead of a single ReAct loop, when a complex vulnerability is discovered (e.g. an IDOR or SSRF), spawn multiple parallel frames (e.g. one attacking authorization bypass, one trying parameter pollution) and let `adhd`'s critic choose the best path.
4. **With `Awesome-Redteam`**: Ingest the cheatsheets and tip markdown files from `Awesome-Redteam` into the agent's system prompt context or local memory. This gives the agent a rich, offline library of WAF bypasses and custom payloads to pull from when writing exploit code.
5. **With `CL4R1T4S`**: When testing target applications that feature integrated AI assistants or chatbots, the agent can pull safety bypasses and system prompt extraction templates from `CL4R1T4S` to test for Prompt Injection and AI Jailbreak bugs.
