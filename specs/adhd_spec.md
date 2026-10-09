# Bug Bounty Harness Integration Specification: adhd (Parallel Divergent Ideation)

## 1. System Overview
`adhd` is a cognitive reasoning framework for AI agents designed to solve the problem of **premature convergence** (anchoring bias) in autoregressive LLMs. 

Instead of generating solutions in a linear chain-of-thought (which anchor on initial outputs and ignore edge cases), `adhd` spawns multiple, isolated reasoning subprocesses (frames) under divergent cognitive perspectives (e.g., security-researcher, inversion, economic-incentive, etc.) with zero shared context, and runs a separate critic pass to score, prune, and consolidate findings.

---

## 2. Architectural Analysis

### Tech Stack
- **Core Logic**: TypeScript / Node.js
- **Distribution**: npm package (`adhd-agent`), CLI, and custom agent skills integrations (`SKILL.md`).
- **Reasoning Architecture**: 
  - **Generator Phase**: Spawns $N$ isolated model calls under distinct "ideation frames" (shifting prompts to force specific perspectives).
  - **Critic / Consolidation Phase**: Consumes all outputs, applies clustering algorithms, identifies logical traps, and outputs a refined strategy.

### File Structure & Components
- [`src/`](file:///home/souhail/Desktop/Desktop/Ult_harness/adhd/src/): Contains the core TypeScript source files for managing framing and evaluation.
- [`skills/adhd/SKILL.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/adhd/skills/adhd/SKILL.md): Declares the skill integration guidelines for AI agents, teaching them when and how to trigger parallel ideation.
- [`bench/`](file:///home/souhail/Desktop/Desktop/Ult_harness/adhd/bench/): Code and scripts used to evaluate the framework against single-shot baselines (measuring metrics like novelty, breadth, and trap detection).

---

## 3. Role in the Unified Harness
In the combined harness, `adhd` functions as the **Cognitive Brain & Planner**. 
- It is not an offensive scanning tool itself; it sits inside the orchestrator's decision-making loop.
- When an AI agent encounters a complex security barrier (like a custom authentication protocol, a strict WAF, or an exotic business logic endpoint), `adhd` splits the agent's logic into parallel investigative units to brainstorm bypasses and identify false-positive traps.

---

## 4. Optimal Bug Bounty Use Cases
- **Creative WAF Bypass Construction**: When standard payloads are blocked, `adhd` splits the search space into different coding techniques (e.g., encoding tricks, protocol anomalies, parameter fragmentation) to devise novel bypass methods.
- **Complex Exploit Chain Design**: Strategizing how to chain multiple low-impact vulnerabilities (e.g., CORS misconfig + CSRF + open redirect) by assigning different frames to look for specific target vulnerabilities.
- **False-Positive Filtration**: Reviewing scanner logs through the "critic" lens to flag why a particular warning is likely a false positive before triggering heavy, noisy active scanning scripts that could trigger target security responses.
- **Business Logic Vulnerability Mapping**: Analyzing target web workflows (like shopping cart checkouts or password reset streams) to identify edge cases and state race conditions.

---

## 5. Harness Merging & Combination Strategy
To merge `adhd` with the other components in the workspace:
1. **With `claude-bug-bounty` or `T3MP3ST`**: Integrate `adhd` directly into the agent planning loop (e.g., in `agent.py` or `orchestrator.ts`). When the orchestrator decides to attack a specific endpoint, instead of letting a single model write the exploit, invoke the `adhd` loop (via CLI `adhd` or as a module). This will run parallel LLM runs under different attack archetypes (e.g., XSS attacker, IDOR specialist, SQLi tester), yielding a robust list of payload candidates.
2. **With `Awesome-Redteam`**: Use `Awesome-Redteam` cheatsheets as the primary reference data for `adhd`'s generator frames, ensuring each reasoning process is seeded with relevant, expert-curated bypass methods.
3. **With `mempalace`**: Let each of the parallel `adhd` generator processes execute independent lookups to `mempalace` to search for target details. This prevents the primary worker from polluting the search space of the secondary workers, preserving divergence.
4. **With `CL4R1T4S`**: When testing target applications containing integrated AI assistants, the `adhd` loop can use different system prompts from `CL4R1T4S` to plan jailbreak sequences from multiple angles.
