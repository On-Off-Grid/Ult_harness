# 🔧 STORM-HUNT: Repository Surgery Blueprint

---

## 1. Source-to-Destination Map

### From Source B — T3MP3ST (`/home/souhail/Desktop/Desktop/T3MP3ST`)

| Source Abs Path | Purpose | Destination Abs Path | Action |
|---|---|---|---|
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/index.ts` | Library entry point, module re-exports | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/index.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/cli.ts` | CLI command parser | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/cli.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/config/index.ts` | Settings loader, API key management, model registry | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/config/settings.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/llm/index.ts` | LLM backbone factory (OpenRouter, Anthropic, Ollama, local) | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/llm/backbone.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/types/index.ts` | Core type definitions (Finding, Target, Severity, KillChain) | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/types/index.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/operators/index.ts` | Operator agent class, archetype profiles, kill-chain mapping | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/index.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/mission/index.ts` | MissionControl, TaskQueue, Rules of Engagement | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/mission.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/mission/adjudicate.ts` | Task adjudication and routing logic | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/adjudicate.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/orchestration/orchestrator.ts` | Swarm orchestration and context packs | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/orchestrator.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/orchestration/context-pack.ts` | Context pack builder for multi-agent coordination | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/context-pack.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/orchestration/prompts.ts` | Orchestration prompt templates | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/prompts.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/orchestration/types.ts` | Orchestration type definitions | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/types.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/evidence/index.ts` | EvidenceVault, CVSS scoring, credential redaction | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/vault.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/evidence/gate.ts` | Live provenance verification gate | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/gate.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/index.ts` | Arsenal tool registry, tool executor, scope containment | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/executor.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/catalog.ts` | Tool catalog definitions | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/catalog.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/adapter-tools.ts` | External tool adapter wrappers | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/adapters.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/parsers.ts` | Tool output parsers | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/parsers.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/approval.ts` | Dangerous-tool approval gates | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/approval.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/opsec/index.ts` | OpsecController, detection risk tracker | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/opsec.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/target/index.ts` | TargetEnvironment, target creation helpers | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/config/target.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/comms/index.ts` | Inter-operator communication channels | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/comms.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/agent/index.ts` | AgentLoop, ReAct loop executor | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/agent-loop.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/agent/local-agents.ts` | Local CLI agent connectors (Claude Code, Codex) | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/llm/local-agents.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/prompts/index.ts` | Operator system prompts and doctrine preamble | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/prompts.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/analysis/index.ts` | AnalysisEngine for finding correlation | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/analysis.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/benchmark/index.ts` | Benchmark scoring utilities | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/benchmark.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/integrations/bounty.ts` | Bug bounty platform integration helpers | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/config/bounty-platforms.ts` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/pack/board.ts` | Pack board for swarm coordination | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/pack-board.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/pack/health.ts` | Pack health monitoring | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/pack-health.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/pack/types.ts` | Pack type definitions | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/pack-types.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/redact.ts` | Credential and secret redaction | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/redact.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/src/resources/index.ts` | Resource pack library | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/resources.ts` | copy |
| `/home/souhail/Desktop/Desktop/T3MP3ST/package.json` | Node project manifest | `/home/souhail/Desktop/Desktop/STORM-HUNT/package.json` | adapt |
| `/home/souhail/Desktop/Desktop/T3MP3ST/tsconfig.json` | TypeScript configuration | `/home/souhail/Desktop/Desktop/STORM-HUNT/tsconfig.json` | adapt |

### From Source A — Pi-Hunt Harness (`/home/souhail/Desktop/Desktop/bbp/harness`)

| Source Abs Path | Purpose | Destination Abs Path | Action |
|---|---|---|---|
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/ssrf-hunter.md` | SSRF specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/ssrf-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/idor-logic-hunter.md` | IDOR/BOLA specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/idor-logic-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/oauth-hunter.md` | OAuth/ATO specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/oauth-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/rce-hunter.md` | RCE specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/rce-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/sqli-hunter.md` | SQLi specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/sqli-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/xss-hunter.md` | XSS specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/xss-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/cache-poison-hunter.md` | Cache poisoning specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/cache-poison-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/race-condition-hunter.md` | Race condition specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/race-condition-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/request-smuggling-hunter.md` | HTTP smuggling specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/request-smuggling-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/injection-hunter.md` | Generic injection specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/injection-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/path-traversal-hunter.md` | Path traversal specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/path-traversal-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/llm-hunter.md` | LLM/prompt-injection specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/llm-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/cve-misconfig-hunter.md` | CVE/misconfig specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/cve-misconfig-hunter.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/strict-triager.md` | Strict triage validation prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/strict-triager.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/recon.md` | Recon specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/recon.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/security-analyzer.md` | Security analyzer prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/security-analyzer.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/hypothesis-redteam.md` | Hypothesis-driven red team prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/hypothesis-redteam.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/deep-research.md` | Deep research specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/deep-research.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/payload-researcher.md` | Payload research specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/payload-researcher.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/bypass-innovator.md` | WAF/filter bypass specialist prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/bypass-innovator.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/cmd-optimizer/optimize.ts` | SecLists command augmentation engine | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/optimizer.ts` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/cmd-optimizer/index.ts` | Command optimizer pi extension wrapper | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/optimizer-hook.ts` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/index.ts` | Subagent spawn runner, concurrency limiter | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/concurrency.ts` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/ensemble.ts` | Ensemble + Swarm task builders | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/ensemble.ts` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/disconfirm.ts` | Reflexive disconfirmation gate | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/disconfirm.ts` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/mcp-profiles.ts` | Per-agent MCP server profiles | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/mcp-profiles.ts` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/agents.ts` | Agent discovery and config loader | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/agent-discovery.ts` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/rag/pihunt_rag/store.py` | SQLite-backed vector store | `/home/souhail/Desktop/Desktop/STORM-HUNT/rag/pihunt_rag/store.py` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/rag/pihunt_rag/embedder.py` | Embedding backend (model2vec + ngram fallback) | `/home/souhail/Desktop/Desktop/STORM-HUNT/rag/pihunt_rag/embedder.py` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/rag/pihunt_rag/ingest.py` | Ingestion pipeline (techniques, findings, memory) | `/home/souhail/Desktop/Desktop/STORM-HUNT/rag/pihunt_rag/ingest.py` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/rag/pihunt_rag/cli.py` | RAG CLI interface | `/home/souhail/Desktop/Desktop/STORM-HUNT/rag/pihunt_rag/cli.py` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/rag/techniques/` | Curated technique YAML files | `/home/souhail/Desktop/Desktop/STORM-HUNT/rag/techniques/` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/rag/requirements.txt` | Python RAG dependencies | `/home/souhail/Desktop/Desktop/STORM-HUNT/rag/requirements.txt` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/rag/install-rag.sh` | RAG installation script | `/home/souhail/Desktop/Desktop/STORM-HUNT/rag/install-rag.sh` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/mcp-servers/pihunt-rag-mcp/` | RAG MCP server (Node stdio JSON-RPC) | `/home/souhail/Desktop/Desktop/STORM-HUNT/mcp-servers/rag-mcp/` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/mcp-servers/browser-live/` | Browser automation MCP server | `/home/souhail/Desktop/Desktop/STORM-HUNT/mcp-servers/browser-live/` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/mcp-servers/burp-mcp-proxy/` | Burp Suite MCP proxy bridge | `/home/souhail/Desktop/Desktop/STORM-HUNT/mcp-servers/burp-mcp-proxy/` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/steering/bugbounty-autoflow.md` | Coordinator workflow rules | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/steering/bugbounty-autoflow.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/steering/continuous-learning.md` | Learning loop steering rules | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/steering/continuous-learning.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/prompts/build.md` | Coordinator brain prompt | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/steering/coordinator-brain.md` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/skills/` | 9 skill directories (auth-attack-patterns, chain-patterns, etc.) | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/skills/` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/recon/` | Bash recon engine, schedulers, curators | `/home/souhail/Desktop/Desktop/STORM-HUNT/bin/recon/` | copy |
| `/home/souhail/Desktop/Desktop/bbp/harness/bin/pi-hunt` | Pi-hunt CLI launcher | `/home/souhail/Desktop/Desktop/STORM-HUNT/bin/storm-hunt` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/bin/pi-tier` | Cost-tier toggle script | `/home/souhail/Desktop/Desktop/STORM-HUNT/bin/storm-tier` | adapt |
| `/home/souhail/Desktop/Desktop/bbp/harness/extras.sh` | Recon toolchain installer (httpx, katana, nuclei, etc.) | `/home/souhail/Desktop/Desktop/STORM-HUNT/bin/install-recon-tools.sh` | adapt |

---

## 2. Shared Structure Layout

```
/home/souhail/Desktop/Desktop/STORM-HUNT/
├── package.json                          # Merged Node manifest (T3MP3ST deps + pi extensions deps)
├── tsconfig.json                         # TypeScript project config
├── .env.example                          # Environment variable template
├── .gitignore                            # Combined ignore patterns
│
├── src/
│   ├── index.ts                          # Library entry point, module re-exports
│   ├── cli.ts                            # CLI command parser and entrypoint
│   │
│   ├── types/
│   │   └── index.ts                      # Core type definitions (Finding, Target, Severity, etc.)
│   │
│   ├── config/
│   │   ├── settings.ts                   # Global settings loader, API key management
│   │   ├── target.ts                     # Target environment builder
│   │   ├── bounty-platforms.ts           # Platform integration helpers (H1, Bugcrowd, YWH, Intigriti)
│   │   └── profile-loader.ts            # [NEW] profile.json parser and validator
│   │
│   ├── db/
│   │   ├── schema.ts                     # [NEW] SQLite table definitions (token_ledger, report_state, etc.)
│   │   ├── logger.ts                     # [NEW] Token logging middleware
│   │   ├── report-state.ts              # [NEW] Report lifecycle state machine with transition enforcement
│   │   ├── metrics.ts                    # [NEW] Aggregate metric query runner
│   │   └── migrations.ts                # [NEW] Schema migration runner
│   │
│   ├── llm/
│   │   ├── backbone.ts                   # LLM provider factory (OpenRouter, Anthropic, Ollama, local)
│   │   ├── local-agents.ts              # Local CLI agent connectors (Claude Code, Codex, Hermes)
│   │   └── cost-router.ts              # [NEW] Model-tier routing policy enforcement
│   │
│   ├── orchestrator/
│   │   ├── orchestrator.ts              # Swarm orchestration and context pack dispatch
│   │   ├── mission.ts                    # MissionControl, TaskQueue, Rules of Engagement
│   │   ├── adjudicate.ts               # Task adjudication and routing
│   │   ├── agent-loop.ts               # ReAct loop executor
│   │   ├── concurrency.ts              # Subagent spawn runner, RAM gate, fan-out limits
│   │   ├── ensemble.ts                  # Ensemble (multi-angle) and Swarm (matrix) task builders
│   │   ├── agent-discovery.ts          # Agent config discovery and loader
│   │   ├── mcp-profiles.ts             # Per-agent MCP server profile assignments
│   │   ├── comms.ts                     # Inter-operator communication channels
│   │   ├── context-pack.ts             # Context pack builder for multi-agent coordination
│   │   ├── prompts.ts                   # Orchestration prompt templates
│   │   ├── types.ts                     # Orchestration type definitions
│   │   ├── pack-board.ts               # Pack board for swarm coordination
│   │   ├── pack-health.ts              # Pack health monitoring
│   │   └── pack-types.ts              # Pack type definitions
│   │
│   ├── operators/
│   │   ├── index.ts                      # OperatorAgent class, archetype profiles, kill-chain mapping
│   │   ├── prompts.ts                    # Operator system prompt library and doctrine preamble
│   │   ├── resources.ts                 # Resource pack library
│   │   ├── specialists/                 # Pi-Hunt-derived specialist instruction prompts
│   │   │   ├── ssrf-hunter.md
│   │   │   ├── idor-logic-hunter.md
│   │   │   ├── oauth-hunter.md
│   │   │   ├── rce-hunter.md
│   │   │   ├── sqli-hunter.md
│   │   │   ├── xss-hunter.md
│   │   │   ├── cache-poison-hunter.md
│   │   │   ├── race-condition-hunter.md
│   │   │   ├── request-smuggling-hunter.md
│   │   │   ├── injection-hunter.md
│   │   │   ├── path-traversal-hunter.md
│   │   │   ├── llm-hunter.md
│   │   │   ├── cve-misconfig-hunter.md
│   │   │   ├── strict-triager.md
│   │   │   ├── recon.md
│   │   │   ├── security-analyzer.md
│   │   │   ├── hypothesis-redteam.md
│   │   │   ├── deep-research.md
│   │   │   ├── payload-researcher.md
│   │   │   └── bypass-innovator.md
│   │   └── skills/                      # Pi-Hunt-derived skill directories
│   │       ├── auth-attack-patterns/
│   │       ├── business-impact/
│   │       ├── chain-patterns/
│   │       ├── critical-endpoints/
│   │       ├── framework-exploits/
│   │       ├── recon-checklist/
│   │       ├── security-bounty-hunter/
│   │       ├── source-review/
│   │       └── writeup-intel/
│   │
│   ├── evidence/
│   │   ├── vault.ts                      # EvidenceVault, CVSS scoring, credential redaction
│   │   ├── gate.ts                       # Live provenance verification gate
│   │   ├── disconfirm.ts               # Reflexive disconfirmation gate
│   │   ├── opsec.ts                     # OpsecController, detection risk tracker
│   │   ├── analysis.ts                  # AnalysisEngine for finding correlation
│   │   ├── benchmark.ts                # Benchmark scoring utilities
│   │   └── redact.ts                    # Credential and secret redaction
│   │
│   ├── arsenal/
│   │   ├── executor.ts                  # Arsenal tool registry, tool runner, scope containment
│   │   ├── catalog.ts                   # Tool catalog definitions
│   │   ├── adapters.ts                  # External tool adapter wrappers
│   │   ├── parsers.ts                   # Tool output parsers
│   │   ├── approval.ts                 # Dangerous-tool approval gates
│   │   ├── optimizer.ts                # SecLists command augmentation engine
│   │   └── optimizer-hook.ts           # Optimizer integration hook
│   │
│   └── steering/
│       ├── bugbounty-autoflow.md        # Coordinator workflow rules
│       ├── continuous-learning.md       # Learning loop steering rules
│       └── coordinator-brain.md        # Coordinator brain prompt
│
├── rag/
│   ├── install-rag.sh                   # RAG venv + model + index installer
│   ├── requirements.txt                # Python dependencies
│   ├── techniques/                     # Curated technique YAML files
│   └── pihunt_rag/
│       ├── __init__.py
│       ├── store.py                     # SQLite-backed vector store (platform-aware)
│       ├── embedder.py                 # Embedding backend
│       ├── ingest.py                    # Ingestion pipeline
│       └── cli.py                       # RAG CLI interface
│
├── mcp-servers/
│   ├── rag-mcp/                        # RAG MCP server (Node stdio JSON-RPC)
│   ├── browser-live/                   # Browser automation MCP server
│   └── burp-mcp-proxy/               # Burp Suite MCP proxy bridge
│
├── bin/
│   ├── storm-hunt                      # Main CLI launcher script
│   ├── storm-tier                      # Cost-tier toggle script
│   ├── install-recon-tools.sh         # Recon toolchain installer
│   └── recon/                          # Bash recon engine, schedulers, curators
│       ├── recon-engine.sh
│       ├── recon-scheduler.sh
│       ├── recon-reg.sh
│       ├── ct-monitor.sh
│       ├── wordlist-curator.sh
│       ├── vulnscan.sh
│       └── payload-curator.sh
│
├── profiles/                           # Per-program onboarding profiles
│   └── example-profile.json           # [NEW] Template profile.json
│
└── reports/                            # Per-program output directory (gitignored)
    └── .gitkeep
```

---

## 3. Component Placement Rules

| Capability | Destination Path | Canonical Owner |
|---|---|---|
| Kill-chain coordination | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/` | T3MP3ST-derived |
| Evidence collection and opsec controls | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/` | T3MP3ST-derived |
| Specialist operator prompts | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/` | Pi-Hunt-derived |
| Command optimizer | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/optimizer.ts` | Pi-Hunt-derived |
| Subagent concurrency and RAM gate | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/concurrency.ts` | Pi-Hunt-derived |
| RAG knowledge server | `/home/souhail/Desktop/Desktop/STORM-HUNT/rag/` | Pi-Hunt-derived |
| Observability tables and report state | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/db/` | New layer |
| Platform-aware policy and scope rules | `/home/souhail/Desktop/Desktop/STORM-HUNT/src/config/profile-loader.ts` | New layer |

---

## 4. File-by-File Integration Notes

### T3MP3ST-Derived Files

| Current Abs Path | Destination Abs Path | Reason | Rename | Interface Changes |
|---|---|---|---|---|
| `.../T3MP3ST/src/config/index.ts` | `.../STORM-HUNT/src/config/settings.ts` | Disambiguate from profile loader | Yes → `settings.ts` | Yes — add `platform` field to settings type |
| `.../T3MP3ST/src/llm/index.ts` | `.../STORM-HUNT/src/llm/backbone.ts` | Clarify as LLM provider factory | Yes → `backbone.ts` | Yes — wrap every call with `db.logTokenSpend()` |
| `.../T3MP3ST/src/types/index.ts` | `.../STORM-HUNT/src/types/index.ts` | Central type definitions | No | Yes — add `platform`, `programId` to `Finding` and `Target` |
| `.../T3MP3ST/src/operators/index.ts` | `.../STORM-HUNT/src/operators/index.ts` | Operator runtime class | No | No |
| `.../T3MP3ST/src/mission/index.ts` | `.../STORM-HUNT/src/orchestrator/mission.ts` | Merge into orchestrator namespace | Yes → `mission.ts` | No |
| `.../T3MP3ST/src/evidence/index.ts` | `.../STORM-HUNT/src/evidence/vault.ts` | Clarify as vault module | Yes → `vault.ts` | Yes — emit state transition events to `db.report-state` |
| `.../T3MP3ST/src/arsenal/index.ts` | `.../STORM-HUNT/src/arsenal/executor.ts` | Clarify as tool executor | Yes → `executor.ts` | Yes — pipe commands through optimizer before execution |
| `.../T3MP3ST/src/opsec/index.ts` | `.../STORM-HUNT/src/evidence/opsec.ts` | Consolidate under evidence | Yes → `opsec.ts` | No |
| `.../T3MP3ST/src/target/index.ts` | `.../STORM-HUNT/src/config/target.ts` | Target is a config concern | Yes → `target.ts` | Yes — load scope from `profile.json` instead of hardcoded |
| `.../T3MP3ST/src/integrations/bounty.ts` | `.../STORM-HUNT/src/config/bounty-platforms.ts` | Platform config | Yes → `bounty-platforms.ts` | Yes — add `platform` enum and per-platform formatters |

### Pi-Hunt-Derived Files

| Current Abs Path | Destination Abs Path | Reason | Rename | Interface Changes |
|---|---|---|---|---|
| `.../harness/pi-agent/agents/*.md` | `.../STORM-HUNT/src/operators/specialists/*.md` | Central specialist prompts folder | No | No — prompts are static markdown |
| `.../harness/pi-agent/extensions/cmd-optimizer/optimize.ts` | `.../STORM-HUNT/src/arsenal/optimizer.ts` | Arsenal owns all tool augmentation | Yes → `optimizer.ts` | Yes — remove pi-specific imports, accept generic config |
| `.../harness/pi-agent/extensions/subagent/index.ts` | `.../STORM-HUNT/src/orchestrator/concurrency.ts` | Orchestrator owns all concurrency | Yes → `concurrency.ts` | Yes — strip pi TUI rendering, retain spawn/RAM logic |
| `.../harness/pi-agent/extensions/subagent/disconfirm.ts` | `.../STORM-HUNT/src/evidence/disconfirm.ts` | Evidence owns verdict validation | No | No — pure functions, no pi imports |
| `.../harness/pi-agent/extensions/subagent/ensemble.ts` | `.../STORM-HUNT/src/orchestrator/ensemble.ts` | Orchestrator owns task planning | No | No — pure functions |
| `.../harness/rag/pihunt_rag/store.py` | `.../STORM-HUNT/rag/pihunt_rag/store.py` | RAG subtree remains self-contained | No | Yes — add `platform` column to chunks table |
| `.../harness/steering/*.md` | `.../STORM-HUNT/src/steering/*.md` | Steering prompts for coordinator | No | No |
| `.../harness/skills/` | `.../STORM-HUNT/src/operators/skills/` | Skills support specialists | No | No |
| `.../harness/recon/` | `.../STORM-HUNT/bin/recon/` | CLI recon scripts belong in bin | No | Yes — update hardcoded paths from `__PIHUNT_HOME__` to `STORM_HUNT_HOME` |

---

## 5. Platform-Aware Separation

### Enforcement Mechanism

Every persistent record in STORM-HUNT carries these mandatory fields:

| Field | Type | Required | Purpose |
|---|---|---|---|
| `platform` | `TEXT NOT NULL` | Always | Isolates data per bug-bounty platform |
| `program_id` | `TEXT NOT NULL` | Always | Isolates data per program within a platform |
| `target_id` | `TEXT NOT NULL` | Always | Isolates data per asset being tested |
| `scope_id` | `TEXT` | Optional | Finer partition (e.g., subdomain or API gateway) |
| `asset_id` | `TEXT` | Optional | Specific endpoint path or function name |

### How Each Data Category Is Isolated

| Data Category | Isolation Mechanism |
|---|---|
| **Report state** | `report_state` table rows carry `(platform, program_id, target_id)`. All queries filter on these three columns. |
| **Token logs** | `token_ledger` table rows carry `(platform, program_id, target_id)`. Aggregation queries always `GROUP BY platform, program_id`. |
| **Lessons learned** | `rag_lessons` table rows carry `(platform, program_id, target_id)`. RAG vector store `chunks` table gains a `platform` column. Default search filters by `platform`. Cross-platform retrieval requires `generalized = 1`. |
| **Duplicate detection** | Dedup queries run `WHERE platform = ? AND program_id = ?`. A finding is only a duplicate within its own platform/program pair. |
| **Triage outcomes** | `state_transitions` table carries `(platform, program_id)`. Triager rejection rate is computed per platform/program. |
| **Scope profiles** | `profiles/` directory contains one `profile.json` per program. Each profile declares its `platform` field. The profile loader rejects any profile without a `platform` value. |

### Canonical Schema (Token Ledger)

```sql
CREATE TABLE token_ledger (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             TEXT    NOT NULL,
    timestamp          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    platform           TEXT    NOT NULL,
    program_id         TEXT    NOT NULL,
    target_id          TEXT    NOT NULL,
    scope_id           TEXT,
    agent_name         TEXT    NOT NULL,
    model_name         TEXT    NOT NULL,
    model_tier         TEXT    NOT NULL CHECK (model_tier IN ('local','mechanical','standard','flagship')),
    phase              TEXT    NOT NULL CHECK (phase IN ('recon','scan','exploit','triage','report')),
    prompt_type        TEXT    NOT NULL,
    tool_name          TEXT,
    input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens      INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL    NOT NULL DEFAULT 0.0,
    severity_class     TEXT    CHECK (severity_class IN ('none','low','medium','high','critical')),
    linked_finding_id  TEXT,
    yield              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_tl_platform_program ON token_ledger(platform, program_id);
CREATE INDEX idx_tl_agent            ON token_ledger(agent_name);
CREATE INDEX idx_tl_model            ON token_ledger(model_tier);
CREATE INDEX idx_tl_run              ON token_ledger(run_id);
```

---

## 6. Build Order

### Step 1: Create root skeleton

```bash
mkdir -p /home/souhail/Desktop/Desktop/STORM-HUNT
cd /home/souhail/Desktop/Desktop/STORM-HUNT

mkdir -p src/{types,config,db,llm,orchestrator,operators/specialists,operators/skills,evidence,arsenal,steering}
mkdir -p rag/pihunt_rag rag/techniques
mkdir -p mcp-servers/{rag-mcp,browser-live,burp-mcp-proxy}
mkdir -p bin/recon
mkdir -p profiles reports
touch reports/.gitkeep
```

**Creates:** The entire directory tree from Section 2.

### Step 2: Wire config and profiles

```bash
# T3MP3ST config
cp /home/souhail/Desktop/Desktop/T3MP3ST/src/config/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/config/settings.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/target/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/config/target.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/integrations/bounty.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/config/bounty-platforms.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/types/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/types/index.ts

# Project manifests
cp /home/souhail/Desktop/Desktop/T3MP3ST/package.json \
   /home/souhail/Desktop/Desktop/STORM-HUNT/package.json

cp /home/souhail/Desktop/Desktop/T3MP3ST/tsconfig.json \
   /home/souhail/Desktop/Desktop/STORM-HUNT/tsconfig.json

cp /home/souhail/Desktop/Desktop/T3MP3ST/.env.example \
   /home/souhail/Desktop/Desktop/STORM-HUNT/.env.example
```

**Creates/modifies:** `src/config/`, `src/types/`, `package.json`, `tsconfig.json`.
**Next:** Create `src/config/profile-loader.ts` (new file) to parse `profiles/*.json`.

### Step 3: Wire observability

Create new files:
- `/home/souhail/Desktop/Desktop/STORM-HUNT/src/db/schema.ts`
- `/home/souhail/Desktop/Desktop/STORM-HUNT/src/db/logger.ts`
- `/home/souhail/Desktop/Desktop/STORM-HUNT/src/db/report-state.ts`
- `/home/souhail/Desktop/Desktop/STORM-HUNT/src/db/metrics.ts`
- `/home/souhail/Desktop/Desktop/STORM-HUNT/src/db/migrations.ts`

**Creates:** `src/db/` — the entire observability layer. All new code.

### Step 4: Wire orchestration

```bash
# T3MP3ST orchestration core
cp /home/souhail/Desktop/Desktop/T3MP3ST/src/orchestration/orchestrator.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/orchestrator.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/orchestration/context-pack.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/context-pack.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/orchestration/prompts.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/prompts.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/orchestration/types.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/types.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/mission/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/mission.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/mission/adjudicate.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/adjudicate.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/agent/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/agent-loop.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/comms/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/comms.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/pack/board.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/pack-board.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/pack/health.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/pack-health.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/pack/types.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/pack-types.ts

# Pi-Hunt concurrency and ensemble
cp /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/concurrency.ts

cp /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/ensemble.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/ensemble.ts

cp /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/mcp-profiles.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/mcp-profiles.ts

cp /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/agents.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/orchestrator/agent-discovery.ts

# LLM backbone
cp /home/souhail/Desktop/Desktop/T3MP3ST/src/llm/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/llm/backbone.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/agent/local-agents.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/llm/local-agents.ts
```

**Creates/modifies:** `src/orchestrator/`, `src/llm/`.
**Next:** Create `src/llm/cost-router.ts` (new file) for model-tier routing policy.

### Step 5: Port specialists

```bash
# All 20 specialist markdown prompts
cp /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/ssrf-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/idor-logic-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/oauth-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/rce-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/sqli-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/xss-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/cache-poison-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/race-condition-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/request-smuggling-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/injection-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/path-traversal-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/llm-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/cve-misconfig-hunter.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/strict-triager.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/recon.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/security-analyzer.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/hypothesis-redteam.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/deep-research.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/payload-researcher.md \
   /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/agents/bypass-innovator.md \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/specialists/

# Operator runtime + prompts
cp /home/souhail/Desktop/Desktop/T3MP3ST/src/operators/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/index.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/prompts/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/prompts.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/resources/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/resources.ts

# Skills
cp -r /home/souhail/Desktop/Desktop/bbp/harness/skills/* \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/operators/skills/

# Steering
cp /home/souhail/Desktop/Desktop/bbp/harness/steering/*.md \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/steering/

cp /home/souhail/Desktop/Desktop/bbp/harness/prompts/build.md \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/steering/coordinator-brain.md

# Arsenal + optimizer
cp /home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/executor.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/catalog.ts \
   /home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/adapter-tools.ts \
   /home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/parsers.ts \
   /home/souhail/Desktop/Desktop/T3MP3ST/src/arsenal/approval.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/

cp /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/cmd-optimizer/optimize.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/optimizer.ts

cp /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/cmd-optimizer/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/arsenal/optimizer-hook.ts

# Evidence
cp /home/souhail/Desktop/Desktop/T3MP3ST/src/evidence/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/vault.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/evidence/gate.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/gate.ts

cp /home/souhail/Desktop/Desktop/bbp/harness/pi-agent/extensions/subagent/disconfirm.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/disconfirm.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/opsec/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/opsec.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/analysis/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/analysis.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/benchmark/index.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/benchmark.ts

cp /home/souhail/Desktop/Desktop/T3MP3ST/src/redact.ts \
   /home/souhail/Desktop/Desktop/STORM-HUNT/src/evidence/redact.ts
```

**Creates/modifies:** `src/operators/`, `src/arsenal/`, `src/evidence/`, `src/steering/`.

### Step 6: Integrate RAG

```bash
cp -r /home/souhail/Desktop/Desktop/bbp/harness/rag/pihunt_rag/* \
   /home/souhail/Desktop/Desktop/STORM-HUNT/rag/pihunt_rag/

cp -r /home/souhail/Desktop/Desktop/bbp/harness/rag/techniques/* \
   /home/souhail/Desktop/Desktop/STORM-HUNT/rag/techniques/

cp /home/souhail/Desktop/Desktop/bbp/harness/rag/requirements.txt \
   /home/souhail/Desktop/Desktop/STORM-HUNT/rag/requirements.txt

cp /home/souhail/Desktop/Desktop/bbp/harness/rag/install-rag.sh \
   /home/souhail/Desktop/Desktop/STORM-HUNT/rag/install-rag.sh

# MCP servers
cp -r /home/souhail/Desktop/Desktop/bbp/harness/mcp-servers/pihunt-rag-mcp/* \
   /home/souhail/Desktop/Desktop/STORM-HUNT/mcp-servers/rag-mcp/

cp -r /home/souhail/Desktop/Desktop/bbp/harness/mcp-servers/browser-live/* \
   /home/souhail/Desktop/Desktop/STORM-HUNT/mcp-servers/browser-live/

cp -r /home/souhail/Desktop/Desktop/bbp/harness/mcp-servers/burp-mcp-proxy/* \
   /home/souhail/Desktop/Desktop/STORM-HUNT/mcp-servers/burp-mcp-proxy/
```

**Creates/modifies:** `rag/`, `mcp-servers/`.
**Next:** Modify `rag/pihunt_rag/store.py` to add `platform` column to `chunks` table.

### Step 7: Add strict triage

Already placed in Step 5 (`strict-triager.md` → `src/operators/specialists/`).
Wire `src/evidence/disconfirm.ts` into the agent loop by adding a post-execution check in `src/orchestrator/concurrency.ts` that calls `classifyVerdict()` and `shouldDisconfirm()` before returning results.

**Modifies:** `src/orchestrator/concurrency.ts`.

### Step 8: Activate platform-aware routing and CLI

```bash
# Bin launchers
cp /home/souhail/Desktop/Desktop/bbp/harness/bin/pi-hunt \
   /home/souhail/Desktop/Desktop/STORM-HUNT/bin/storm-hunt

cp /home/souhail/Desktop/Desktop/bbp/harness/bin/pi-tier \
   /home/souhail/Desktop/Desktop/STORM-HUNT/bin/storm-tier

cp /home/souhail/Desktop/Desktop/bbp/harness/extras.sh \
   /home/souhail/Desktop/Desktop/STORM-HUNT/bin/install-recon-tools.sh

# Recon scripts
cp /home/souhail/Desktop/Desktop/bbp/harness/recon/*.sh \
   /home/souhail/Desktop/Desktop/STORM-HUNT/bin/recon/

chmod +x /home/souhail/Desktop/Desktop/STORM-HUNT/bin/storm-hunt
chmod +x /home/souhail/Desktop/Desktop/STORM-HUNT/bin/storm-tier
chmod +x /home/souhail/Desktop/Desktop/STORM-HUNT/bin/install-recon-tools.sh
chmod +x /home/souhail/Desktop/Desktop/STORM-HUNT/bin/recon/*.sh
```

**Creates/modifies:** `bin/`.
**Next:** Update all hardcoded `__PIHUNT_HOME__` tokens in bin scripts to `STORM_HUNT_HOME`.

---

## 7. Final Sanity Checklist

```
- [ ] All absolute paths under /home/souhail/Desktop/Desktop/STORM-HUNT resolve on disk
- [ ] No module has more than one canonical home
- [ ] Every persistent record schema includes platform + program_id + target_id
- [ ] RAG retrieval is scoped by platform field by default
- [ ] Orchestration logic lives exclusively under src/orchestrator/
- [ ] Specialist logic lives exclusively under src/operators/specialists/
- [ ] Observability logic lives exclusively under src/db/
- [ ] bin/ contains only CLI entrypoints, no business logic
- [ ] No source file from Pi-Hunt root appears under T3MP3ST-derived paths
- [ ] No source file from T3MP3ST root appears under Pi-Hunt-derived paths
- [ ] Project builds without errors from /home/souhail/Desktop/Desktop/STORM-HUNT root
- [ ] rag/pihunt_rag/store.py chunks table includes platform column
- [ ] src/config/profile-loader.ts rejects profiles without platform field
- [ ] src/db/report-state.ts enforces blocked transitions in code
- [ ] src/arsenal/executor.ts pipes commands through optimizer before execution
- [ ] src/llm/backbone.ts wraps every LLM call with token logging
- [ ] bin/storm-hunt replaces all __PIHUNT_HOME__ with STORM_HUNT_HOME
- [ ] profiles/example-profile.json exists and validates against profile-loader
```
