# Bug Bounty Harness Integration Specification: CL4R1T4S

## 1. System Overview
`CL4R1T4S` is an open-source database of extracted system prompts, safety guidelines, system instructions, and tool configurations from major commercial AI platforms and coding agents (including OpenAI, Google, Anthropic, xAI, Perplexity, Cursor, Windsurf, Devin, Manus, Replit, Vercel V0, Lovable, and others). 

It acts as a **reference registry** for researchers to study prompt designs, safety guards, and potential attack vectors on LLM-powered applications.

---

## 2. Architectural Analysis

### Structure
- **Format**: Text (.txt) and Markdown (.md) documents containing extracted prompt blocks.
- **Organizational Structure**: Divided into subdirectories by LLM provider or development environment:
  - `ANTHROPIC/`: Scaffolds for Claude models and the Claude Code CLI tool.
  - `OPENAI/`, `GOOGLE/`, `MISTRAL/`, `xAI/`: Core instructions for foundation models.
  - `CURSOR/`, `CLINE/`, `DEVIN/`, `BOLT/`, `MANUS/`, `REPLIT/`: Agent-specific workflows, loop limits, shell-access warnings, and tool schemas.

---

## 3. Role in the Unified Harness
In the combined harness, `CL4R1T4S` functions as the **AI Attack Registry & Agent Optimization Reference**.
- **AI Attack Vector**: It provides the exact instructions that govern corporate AI chatbots and integrations. Attackers use this to identify boundary conditions, logic bypasses, and prompt injection vectors on target applications that integrate AI features.
- **Agent Optimizer**: It provides a library of high-performance agent system prompts (like `Claude_Code_03-04-24.md` or `Cursor_2.0_Sys_Prompt.txt`) which the developer can copy to improve the tool-calling and code-editing capabilities of their own custom agents.

---

## 4. Optimal Bug Bounty Use Cases
- **Prompt Injection & Jailbreak Planning**: When auditing a target application that integrates a customer service AI assistant, the scanner agent maps the model's instructions (using similar profiles in CL4R1T4S) to create targeted prompt injection scripts to leak database fields, bypass payment screens, or bypass safety locks.
- **System Prompt Extraction (Indirect Injection)**: Executing specific instructions compiled in `CL4R1T4S` (e.g. Pliny-style leetspeak bypasses) to force target bots to output their system prompt, revealing hidden API endpoints and access rules.
- **Bypassing Sandbox Restrictions**: Studying agent safety prompt formats to find logical holes in agent sandboxing logic, enabling command execution or data extraction.

---

## 5. Harness Merging & Combination Strategy
To merge `CL4R1T4S` with the other components in the workspace:
1. **With `mempalace`**: Mine all the prompts in `CL4R1T4S` into `mempalace` under a dedicated `system_prompts` Wing. This enables semantic search: during target scanning, if the agent identifies an LLM target running a specific model (e.g. Grok or Gemini), it queries the memory database to pull the exact system prompt blueprint.
2. **With `claude-bug-bounty` & `T3MP3ST`**: If the scanning agents discover a chatbot or API endpoint that accepts natural language inputs on the target, they can automatically trigger a custom scanning phase. This phase queries `mempalace` for `CL4R1T4S` prompt formats to construct automated jailbreak tests, logging successful extraction responses as verified vulnerabilities.
3. **With `adhd`**: Use the system prompt definitions in `CL4R1T4S` to test new cognitive framing variations in the `adhd` loop, improving the agent's problem-solving capabilities.
