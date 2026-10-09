# Bug Bounty Harness Integration Specification: Awesome-Redteam

## 1. System Overview
`Awesome-Redteam` is a comprehensive offensive security knowledge base. It catalogs cheat sheets, payload checklists, OSINT tips, bypass instructions, post-exploitation scripts, and command-line structures for red teaming and pen-testing. 

Rather than an active executable binary, it functions as a **structured dictionary of offensive tactics** that can be consumed by human operators or parsed by AI agents to construct exploitation payloads.

---

## 2. Architectural Analysis

### Tech Stack
- **Format**: Markdown (.md) documents, images, and scripting snippets.
- **Organizational Structure**:
  - `cheatsheets/`: Core checklists for common vulnerability classes (SQL Injection, Cross-Site Scripting (XSS), 403 Bypass, SSRF, Java Deserialization, XXE).
  - `tips/`: Tactical recommendations for network scanning, target profiling, GitHub dorks, domain enumeration, and default credential lookup.
  - `scripts/`: Custom exploit scripts and utilities.

---

## 3. Role in the Unified Harness
In the combined harness, `Awesome-Redteam` functions as the **Offensive Reference Library & Payload Database**.
- It provides the specialized payloads, bypass patterns, and exploitation steps that the scanning engines (`claude-bug-bounty`, `T3MP3ST`, `BugTraceAI`) use to mutate inputs.
- It supplies default credential lists and query strings for the recon phases.

---

## 4. Optimal Bug Bounty Use Cases
- **WAF & 403 Bypass Generation**: The scanning agent uses the 403 bypass checklist (covering techniques like header overrides `X-Forwarded-For: 127.0.0.1`, URL normalization bypasses `..;/`, and path modifications) to mutate blocked requests.
- **CMS/OA Attack Sequence Construction**: Pulling exploit paths and POC templates for popular Content Management Systems and Office Automation suites identified during domain fingerprinting.
- **Java Deserialization Exploit Payload Mapping**: Looking up gadget chains (like CommonsCollections or Jackson) and payload generators (ysoserial arguments) when encountering Java serialized request objects.
- **Github Dorking**: Querying the Github dork cheatsheet to construct query strings for scraping secret tokens or configuration files related to the target.

---

## 5. Harness Merging & Combination Strategy
To merge `Awesome-Redteam` with the other components in the workspace:
1. **With `mempalace`**: Ingest the entire markdown structure of `Awesome-Redteam` into `mempalace` using `mempalace mine`. Configure a specific wing (`redteam_docs`) and room (`payloads`). When an agent (like `agent.py` in `claude-bug-bounty`) encounters a specific tech stack or a WAF block, it queries the `mempalace` MCP server to get exact payload templates.
2. **With `jsleak`**: Cross-reference regex definitions stored in the `Awesome-Redteam` regex cheat sheets to expand the YAML pattern databases used by `jsleak` for secrets scanning.
3. **With `adhd`**: During the planning phase of the `adhd` loop, inject segments of the `Awesome-Redteam` tips database into the system prompts. This teaches the different reasoning frames how an experienced human red teamer would bypass specific security controls, increasing the novelty of the brainstormed strategies.
