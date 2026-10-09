# Bug Bounty Harness Integration Specification: Agent-Reach

## 1. System Overview
`Agent-Reach` is a diagnostic, installation, and routing manager designed to equip AI agents with real-time web search and platform-specific scraping capabilities (OSINT). 

Instead of wrapping APIs with heavy abstractions, it installs, configures, and diagnoses local CLI tools (like `twitter-cli`, `yt-dlp`, `mcporter`, etc.) and allows agents to run them directly or interface with them via Model Context Protocol (MCP).

---

## 2. Architectural Analysis

### Tech Stack
- **Core Logic**: Python 3.10+
- **Protocol**: Model Context Protocol (MCP) server stdio interface.
- **Scraping Backends & Platforms**:
  - Search engines: Exa search API.
  - Social & Forums: Twitter/X (via `twitter-cli` or `OpenCLI`), Reddit (via `rdt-cli`), RSS feeds, V2EX, Xueqiu.
  - Professional/Media: YouTube (via `yt-dlp`), Bilibili (`bili-cli`), LinkedIn (via Jina Reader), Facebook, Instagram, Xiaohongshu, Xiaoyuzhou podcast transcripts.
- **Credential Storage**: Safe local extraction of browser session state cookies using `OpenCLI` (reusing local Chrome login profiles) to bypass Cloudflare/WAF blockades on target social APIs.

### File Structure & Components
- [`agent_reach/core.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/Agent-Reach/agent_reach/core.py): Entry point defining the main orchestration class.
- [`agent_reach/doctor.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/Agent-Reach/agent_reach/doctor.py): Evaluates the functional health of all 15+ external scraping channels.
- [`agent_reach/channels/`](file:///home/souhail/Desktop/Desktop/Ult_harness/Agent-Reach/agent_reach/channels/): Sub-folder implementing individual platform scraping logic and validation probes (e.g. `reddit.py`, `twitter.py`, `github.py`, `web.py`, `rss.py`).
- [`agent_reach/integrations/mcp_server.py`](file:///home/souhail/Desktop/Desktop/Ult_harness/Agent-Reach/agent_reach/integrations/mcp_server.py): Defines the MCP server interface wrapping doctor capabilities.
- [`agent_reach/skill/SKILL.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/Agent-Reach/agent_reach/skill/SKILL.md): Agent instruction handbook that informs LLMs which CLI command to call depending on the user's information gathering request.

---

## 3. Role in the Unified Harness
In the combined harness, `Agent-Reach` serves as the **Intelligence & OSINT Data Pipeline**. 
- It does not actively scan target networks; instead, it scrapes forums, social networks, and codebases to gather external intelligence about targets, open source code vulnerabilities, and newly disclosed exploits.
- It operates as a background utility daemon that ensures the host machine has active session credentials and functional command-line crawlers.

---

## 4. Optimal Bug Bounty Use Cases
- **Vulnerability / Exploit OSINT**: Querying X/Twitter and Reddit in real-time when a scanner hits a specific software version (e.g. `Liferay 7.4`) to pull unindexed exploit code, bypass strings, or notes from security researchers.
- **Passive Subdomain & Endpoint Harvesting**: Scraping target Github repositories, public discussions, and pull requests to identify hardcoded endpoints, dev/test subdomains, and leaked API paths.
- **Credential Leak & Target Profiling**: Scraping profiles and threads on local media networks (V2EX, Xiaohongshu, etc.) to compile lists of target corporate domains, active usernames, and naming schemes for subsequent credential-stuffing campaigns.
- **Video Proof-of-Concept Parsing**: Extracting transcripts from YouTube or Bilibili video walkthroughs of security POCs to quickly rebuild exploit payloads.

---

## 5. Harness Merging & Combination Strategy
To merge `Agent-Reach` with the other components in the workspace:
1. **With `claude-bug-bounty` or `T3MP3ST`**: During the initialization phase of a scan, the orchestrator should run `agent-reach doctor` (via the command line or MCP) to verify which scraping channels are active. If an exploit fails or a target's tech stack is identified (e.g., a specific CMS), the orchestrator can call `twitter` or `reddit` search commands to look for relevant 0-days or CVE bypasses.
2. **With `mempalace`**: Pipe all scraped OSINT feeds (e.g. RSS alerts on specific vulnerability terms, tweets from security researchers) directly into `mempalace`'s structured rooms. When the scanner agent is targeting a specific platform, it searches this local memory store to pull historical tips and payloads.
3. **With `CL4R1T4S`**: Use `Agent-Reach`'s search capability to fetch the latest updates on jailbreaks or AI safety rules, matching them against local system prompts stored in `CL4R1T4S` to test targets that contain integrated AI agents.
