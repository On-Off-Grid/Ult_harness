# Bug Bounty Harness Integration Specification: T3MP3ST

## 1. System Overview
`T3MP3ST` is a multi-agent offensive security framework designed to turn existing AI coding agents (such as Claude Code, Codex, or local offline LLMs) into autonomous zero-day hunters and pentesting systems. 

It manages the full offensive security kill chain (recon → exploit → report) via a browser-based "War Room" interface or a headless CLI. 

---

## 2. Architectural Analysis

### Tech Stack
- **Core Logic**: TypeScript / Node.js
- **Frontend Dashboard**: Web-based "War Room" UI (port `3333` default).
- **LLM Integration**: Keyless local agent redirection (intercepts shell tools of Claude Code/Codex) and direct API keys connectors (OpenRouter, xAI Grok, Venice, OpenAI, Anthropic, Ollama, LM Studio).
- **Static Code Analysis**: High-speed multi-language code ingestion using `web-tree-sitter` (Abstract Syntax Tree parsing).
- **Execution & Validation Engine**: Configurable local command executor (the Arsenal) with active user-approval security gates to restrict destructive actions.

### File Structure & Components
- [`src/server.ts`](file:///home/souhail/Desktop/Desktop/Ult_harness/T3MP3ST/src/server.ts): Express API server driving the Web UI.
- [`src/admiral/`](file:///home/souhail/Desktop/Desktop/Ult_harness/T3MP3ST/src/admiral/): Holds the Op Admiral orchestrator logic which controls the high-level scan planning.
- [`src/agent/`](file:///home/souhail/Desktop/Desktop/Ult_harness/T3MP3ST/src/agent/): Manages interfaces to local LLMs and terminal redirection.
- [`src/arsenal/`](file:///home/souhail/Desktop/Desktop/Ult_harness/T3MP3ST/src/arsenal/): Script tools execution block (subdomain takeover, post-exploitation, payload approval gates).
- [`src/recon/`](file:///home/souhail/Desktop/Desktop/Ult_harness/T3MP3ST/src/recon/): Ingests target source code, parses AST nodes using `web-tree-sitter`, and maps parameters (`param-split.ts`).
- [`src/validation/`](file:///home/souhail/Desktop/Desktop/Ult_harness/T3MP3ST/src/validation/): Proof-of-concept validators to confirm vulnerability status.
- [`src/evidence/`](file:///home/souhail/Desktop/Desktop/Ult_harness/T3MP3ST/src/evidence/): Secure vault for storing exploit proof, screenshots, and logs.

---

## 3. Role in the Unified Harness
In the combined harness, `T3MP3ST` acts as the **Central Command Console and Source Code Auditor**.
- It provides the primary Web War Room for visualizing target attacks, approvals, and logs.
- It acts as the coordinator between the human operator, the connected AI models, and the active command-line payloads.
- It provides high-speed white-box source code auditing utilizing syntactic AST parsers.

---

## 4. Optimal Bug Bounty Use Cases
- **White-Box Code Auditing & Vuln Ingestion**: Scanning target repositories (git checkouts) to extract functions, classes, and import trees, directing the agent to trace code-level vulnerabilities (like command injection sinks or path traversals).
- **War Room Dashboard Orchestration**: Monitoring ongoing multi-step exploit operations, allowing a human operator to preview and approve commands before execution.
- **Autonomous Capture-The-Flag (CTF) Exploitation**: Headless target exploitation (cybench/xben suites) where the agent maps input parameters, designs a payload, verifies file access, and extracts flag keys.
- **Damn Vulnerable DeFi Audits**: Crawling smart contracts to run local test networks and execute attack transactions (e.g. flash loan exploits).

---

## 5. Harness Merging & Combination Strategy
To merge `T3MP3ST` with the other components in the workspace:
1. **With `claude-bug-bounty` & `BugTraceAI`**: Merge `T3MP3ST`'s command engine with `claude-bug-bounty`'s execution engine. Let `T3MP3ST`'s Web UI act as the graphical frontend, running `claude-bug-bounty`'s `bughunter` script or `BugTraceAI-CLI`'s FastAPI endpoint in the background to handle the automated scanning pipeline.
2. **With `jsleak`**: Add `jsleak` to `T3MP3ST`'s `src/arsenal/adapter-tools.ts` library. When doing white-box or black-box recon, the agent can call `jsleak` directly to find secrets and links in Javascript files.
3. **With `mempalace`**: Standardize `T3MP3ST`'s memory logging by routing file analysis results to `mempalace`'s structured SQLite or ChromaDB backend, creating a semantic memory of the audited codebases.
4. **With `adhd`**: Wire the TS-based `adhd` parallel reasoning frames into `src/llm/` or `src/admiral/`. When the admiral identifies a complex code block to audit, it spawns parallel divergent code reviewer frames to bypass single-pass anchoring bias.
5. **With `CL4R1T4S` & `Awesome-Redteam`**: Load red teaming checklists from `Awesome-Redteam` and safety rules from `CL4R1T4S` into `T3MP3ST`'s system resources block (`src/resources/`), enabling the agents to pull payload templates on demand.
