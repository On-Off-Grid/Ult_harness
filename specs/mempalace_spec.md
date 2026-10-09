# Bug Bounty Harness Integration Specification: mempalace

## 1. System Overview
`mempalace` is a local-first AI memory database that stores conversation logs, terminal transcripts, and codebases as verbatim text, retrieving them via semantic vector search. 

Rather than summarizing or paraphrasing inputs (which can lose critical syntactical security details), it indexes content using a structured, hierarchical layout (Wings, Rooms, and Drawers) and acts as an MCP server.

---

## 2. Architectural Analysis

### Tech Stack
- **Core Logic**: Python 3.9+
- **Database Engine**: Pluggable storage interface:
  - ChromaDB (default local embedded vector DB).
  - `sqlite_exact` (lexical/exact local match).
  - Milvus Lite, Qdrant REST server, pgvector (PostgreSQL).
- **Interface**: CLI and standard JSON-RPC over stdio (MCP protocol) for direct integration into AI agents.
- **Processing Options**: CPU-bound default embeddings or GPU-bound CUDA accelerated embeddings (`Dockerfile.gpu`).

### File Structure & Components
- [`mempalace/backends/base.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/mempalace/mempalace/backends/base.py): Base class defining the pluggable backend database interface.
- [`mempalace/backends/`](file:///home/souhail/Desktop/Desktop/Ult_harness/mempalace/mempalace/backends/): Database-specific connector engines.
- `mcp.json` & Docker configuration files: Settings to register the memory engine as an active MCP sidecar.

### Data Model Hierarchy
- **Wings (Projects)**: Top-level isolation boundaries. In bug bounty, each target company or scope division is assigned a unique Wing (e.g. `target_wing`).
- **Rooms (Topics)**: Subdivisions within a project (e.g. `subdomains`, `cves`, `auth_endpoints`).
- **Drawers (Entries)**: The raw text content (terminal outputs, HTTP raw requests, scanned code blocks).

---

## 3. Role in the Unified Harness
In the combined harness, `mempalace` acts as the **Long-Term Memory and Knowledge Base**. 
- It bridges the gap between active scan runs, resolving the LLM context window limitation by caching all past logs and findings.
- It enables target persistence: target information gathered on day 1 remains available and searchable on day 30.

---

## 4. Optimal Bug Bounty Use Cases
- **Persistent Target Mapping**: Storing subdomains, tech stacks, and response headers mined over weeks. When the agent initiates a new scan on a subdomain, it queries `mempalace` to retrieve its historical configuration.
- **Exploit & Payload Search**: Indexing red teaming books, CVE descriptions, and custom wordlists. During an active hunt, the agent asks `mempalace` for "bypass payloads for Apache Tomcat" to pull exact syntactic matches.
- **Command & Session Retention**: Saving all CLI tool execution outputs. If a scanner crashes mid-execution, the agent can query its memory to see what commands were already completed and resume from the failure point.

---

## 5. Harness Merging & Combination Strategy
To merge `mempalace` with the other components in the workspace:
1. **With `claude-bug-bounty` & `T3MP3ST`**: Modify the agent loops to talk to the `mempalace` MCP server. When executing commands, the agent writes raw responses (e.g. nmap XMLs, nuclei JSONs) to a target-specific Wing in `mempalace`. Before generating exploit code, the agent searches this Wing for related findings.
2. **With `Awesome-Redteam` & `CL4R1T4S`**: Run `mempalace mine` over the `Awesome-Redteam` cheatsheets and the `CL4R1T4S` system prompts. This turns these raw Markdown/text repositories into a semantic lookup engine that any scanning agent can query on-demand.
3. **With `Agent-Reach`**: As `Agent-Reach` scrapes Twitter/X, Reddit, or Github for threat intel, dump the filtered content into a global `threat_intel` Room in `mempalace` for the agents to reference during scan planning.
