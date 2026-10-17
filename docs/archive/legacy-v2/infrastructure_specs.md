# Bug Bounty Harness — Infrastructure & Machine Specifications

**Version:** 2.1.1  
**Companion to:** [`bug_bounty_harness_design_v2_1.md`](file:///home/souhail/Desktop/Desktop/Ult_harness/bug_bounty_harness_design_v2_1.md)  
**Purpose:** Hardware, GPU, network, and deployment requirements for all harness components.

---

## 1. Component Resource Map

Every running process in the harness has distinct resource demands. This table is the ground truth for capacity planning.

| Component | Process | CPU | RAM | GPU VRAM | Disk | Network | Port |
|---|---|---|---|---|---|---|---|
| **Ollama (Local LLM)** | `ollama serve` | 2–4 cores | 4 GB (host overhead) | **See §2 GPU table** | 20–80 GB (model weights) | Loopback only | `11434` |
| **OpAdmiral Orchestrator** | `uvicorn orchestrator.admiral:app` | 2 cores | 1 GB | — | Negligible | Loopback + WS | `8001` |
| **mempalace** | `mempalace serve` / MCP stdio | 2 cores | 2 GB (ChromaDB embeddings) | — | 1–10 GB (vector DB + SQLite) | Loopback | `8000` |
| **Egress Proxy** | `mitmdump -s egress_proxy.py` | 1 core | 512 MB | — | 100 MB (flow logs) | **All outbound target traffic** | `8080` |
| **T3MP3ST War Room** | `node T3MP3ST/src/server.ts` | 1 core | 512 MB | — | Negligible | HTTP + WS | `3333` |
| **BugTraceAI-CLI Fuzzers** | Go binaries + FastAPI | 4–8 cores | 2–4 GB | — | 500 MB (scan artifacts) | Outbound via proxy | `8002` |
| **Playwright Validator** | Chromium headless | 2 cores | 1–2 GB per browser | — | 500 MB (browser binary) | Outbound via proxy | — |
| **jsleak** | Go binary | 1 core | 256 MB | — | Negligible | Outbound via proxy | — |
| **adhd Ideation** | Node.js | 1 core | 512 MB | — | Negligible | HTTP to Ollama/API | — |
| **Interactsh (self-hosted)** | Go binary | 1 core | 256 MB | — | 100 MB | **Inbound DNS/HTTP/SMTP** | `53,80,443,25` |
| **Docker Engine** | `dockerd` | 1 core | 1 GB overhead | — | 5 GB (images) | — | — |

---

## 2. GPU Requirements for Local LLMs

The harness's cost efficiency depends entirely on local model quality. Bigger models = better exploit reasoning, but require more VRAM.

### Model VRAM Matrix

| Model | Parameters | Quantization | VRAM Required | Speed (tok/s) | Harness Role |
|---|---|---|---|---|---|
| `qwen2.5-coder:7b` | 7B | Q4_K_M | **5 GB** | 40–60 | Payload mutation, code analysis |
| `qwen2.5:14b` | 14B | Q4_K_M | **9 GB** | 25–40 | Recon analysis, planning, triage reasoning |
| `llama3.1:8b` | 8B | Q4_K_M | **5.5 GB** | 35–55 | Fast validation, adhd ideation |
| `codellama:34b` | 34B | Q4_K_M | **20 GB** | 10–18 | Complex exploit chain reasoning |
| `llama3.1:70b` | 70B | Q4_K_M | **40 GB** | 5–10 | Deep analysis (requires high-end GPU) |
| `deepseek-coder-v2:16b` | 16B | Q4_K_M | **10 GB** | 20–35 | Code review, vulnerability pattern matching |
| `mistral:7b` | 7B | Q4_K_M | **5 GB** | 40–60 | Lightweight fallback |

> **Key insight**: You don't need to load all models simultaneously. Ollama swaps models on demand. Peak VRAM = the single largest model you plan to use.

### GPU Tier Recommendations

| GPU Tier | Cards | VRAM | Max Model | Concurrent Models | Price Range |
|---|---|---|---|---|---|
| **Entry** | RTX 3060 / RTX 4060 | 8–12 GB | `qwen2.5:14b` (Q4) | 1 | $250–$350 |
| **Mid** | RTX 3090 / RTX 4070 Ti Super | 16–24 GB | `codellama:34b` (Q4) | 1–2 small | $400–$800 |
| **High** | RTX 4090 / RTX A6000 | 24–48 GB | `llama3.1:70b` (Q4) | 2–3 | $1,200–$4,500 |
| **Multi-GPU** | 2× RTX 3090 / 2× RTX 4090 | 48–96 GB | `llama3.1:70b` (FP16) | 3–4 | $2,500–$5,000 |
| **Cloud GPU** | A100 80GB / H100 | 80–96 GB | Any model at full precision | All | $1.50–$3.50/hr |

> **CPU-only fallback**: Ollama can run models on CPU, but expect 1–3 tok/s for 14B models. Usable for planning/triage in a pinch, not for interactive fuzzing loops.

---

## 3. Deployment Profiles

### Profile A: Budget Laptop Hunter

**Use case**: Solo researcher, single target at a time, learning the platform.  
**Cost**: $0 additional hardware (use what you have).

| Resource | Minimum | Recommended |
|---|---|---|
| **CPU** | 4 cores (i5/Ryzen 5) | 6+ cores |
| **RAM** | 16 GB | 32 GB |
| **GPU** | Integrated / GTX 1660 (6 GB) | RTX 3060 (12 GB) |
| **Storage** | 50 GB free SSD | 100 GB free NVMe |
| **OS** | Ubuntu 22.04+ / WSL2 | Ubuntu 24.04 |
| **Network** | Any broadband | Stable connection with low latency |

**Configuration**:
- Ollama runs `qwen2.5-coder:7b` or `mistral:7b` (fits in 6 GB VRAM).
- Use `PAID_FREE` tier (Groq) for validation/chaining instead of larger local models.
- Run 1–2 specialists concurrently, not all 16.
- Playwright uses a single browser instance.
- Interactsh uses public `oast.me` (no self-hosted).
- Docker optional — can run components as bare processes.

**Budget estimate**: $0/month (Groq free tier) to $5/month (occasional GPT-4o validation).

```
┌─────────────────────────────────────────────┐
│           PROFILE A: LAPTOP LAYOUT          │
├─────────────────────────────────────────────┤
│                                             │
│  [ Ollama 7B ]  [ mempalace ]  [ Admiral ]  │
│       ↕              ↕             ↕        │
│  [ Egress Proxy ] ← ALL outbound traffic    │
│       ↕                                     │
│  [ 2 Specialists ]  [ Playwright ×1 ]       │
│       ↕                                     │
│  [ T3MP3ST War Room :3333 ]                 │
│                                             │
│  GPU: 6–12 GB  │  RAM: 16–32 GB            │
└─────────────────────────────────────────────┘
```

---

### Profile B: Dedicated Workstation

**Use case**: Active bug bounty hunter, 2–3 concurrent programs, daily hunting sessions.  
**Cost**: $800–$2,000 (GPU upgrade + RAM).

| Resource | Specification |
|---|---|
| **CPU** | 8+ cores (Ryzen 7 7700X / i7-13700K) |
| **RAM** | 64 GB DDR5 |
| **GPU** | RTX 4070 Ti Super (16 GB) or RTX 3090 (24 GB) |
| **Storage** | 500 GB NVMe SSD (OS + models) + 1 TB HDD (scan archives) |
| **OS** | Ubuntu 24.04 Server or Desktop |
| **Network** | 100 Mbps+ symmetric, static IP preferred |

**Configuration**:
- Ollama runs `qwen2.5:14b` as primary, `codellama:34b` for exploit chaining.
- 6–8 specialists run concurrently.
- Playwright runs 2–3 browser instances in parallel.
- Interactsh: public `oast.me` for live programs, optional self-hosted for lab testing.
- All services containerized via Docker Compose.

**Budget estimate**: $0–$10/month (Groq free tier + occasional paid validation).

```
┌─────────────────────────────────────────────────────┐
│           PROFILE B: WORKSTATION LAYOUT             │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────────────────────────────────┐       │
│  │ GPU: RTX 3090/4070Ti (16–24 GB VRAM)    │       │
│  │ Ollama: qwen2.5:14b + codellama:34b     │       │
│  └──────────────────────────────────────────┘       │
│       ↕                                             │
│  [ OpAdmiral :8001 ] ←→ [ mempalace :8000 ]        │
│       ↕                    ↕                        │
│  [ Egress Proxy :8080 ] ← ALL outbound             │
│       ↕                                             │
│  [ 6–8 Specialists ] [ BugTraceAI Fuzzers ]        │
│  [ Playwright ×3 ]   [ jsleak ]  [ adhd ]          │
│       ↕                                             │
│  [ T3MP3ST War Room :3333 ]                         │
│                                                     │
│  CPU: 8 cores  │  RAM: 64 GB  │  SSD: 500 GB       │
└─────────────────────────────────────────────────────┘
```

---

### Profile C: Production Server (Full Autonomous)

**Use case**: Running 24/7 against multiple programs, all 16 specialists active, self-hosted OOB.  
**Cost**: $3,000–$6,000 (dedicated hardware) or $150–$400/month (cloud).

| Resource | Specification |
|---|---|
| **CPU** | 16+ cores (Ryzen 9 7950X / Xeon w5-3435X) |
| **RAM** | 128 GB DDR5 ECC |
| **GPU** | RTX 4090 (24 GB) or 2× RTX 3090 (48 GB) or A6000 (48 GB) |
| **Storage** | 1 TB NVMe (OS + models) + 2 TB SSD (scan data + ChromaDB) |
| **OS** | Ubuntu 24.04 Server (headless) |
| **Network** | 1 Gbps symmetric, static public IP, registered domain (for self-hosted Interactsh) |
| **DNS** | Authoritative NS delegation to server IP (for `INTERACTSH_MODE=selfhosted`) |

**Configuration**:
- Ollama runs `llama3.1:70b` for deep analysis, `qwen2.5:14b` for routine tasks (swapped on demand).
- All 16 specialists active concurrently.
- Playwright runs 4–6 browser instances.
- Self-hosted Interactsh with registered OOB domain.
- Full Docker Compose deployment with health monitoring.

**Budget estimate**: $5–$15/month (paid validation for confirmed findings only).

```
┌───────────────────────────────────────────────────────────┐
│              PROFILE C: PRODUCTION SERVER                 │
├───────────────────────────────────────────────────────────┤
│                                                           │
│  ┌────────────────────────────────────────────────┐       │
│  │ GPU: RTX 4090 / 2×RTX 3090 (24–48 GB VRAM)   │       │
│  │ Ollama: llama3.1:70b ←→ qwen2.5:14b (swap)   │       │
│  └────────────────────────────────────────────────┘       │
│       ↕                                                   │
│  [ OpAdmiral :8001 ] ←→ [ mempalace :8000 ]              │
│       ↕                    ↕                              │
│  [ Egress Proxy :8080 ] ← ALL outbound                   │
│       ↕                                                   │
│  ┌────────────────────────────────────────────────┐       │
│  │ 16 SPECIALIST AGENTS (concurrent)             │       │
│  │ SQLi│XSS│SSRF│IDOR│LFI│RCE│XXE│JWT│OR│PP│    │       │
│  │ CSTI│MA│HI│BAC│AI_JB│BL                      │       │
│  └────────────────────────────────────────────────┘       │
│       ↕                                                   │
│  [ BugTraceAI Fuzzers ] [ Playwright ×6 ] [ jsleak ]     │
│  [ adhd ideation ]      [ Agent-Reach OSINT ]             │
│       ↕                                                   │
│  [ T3MP3ST War Room :3333 ]                               │
│  [ Interactsh (self-hosted) :53/:80/:443/:25 ]            │
│                                                           │
│  CPU: 16 cores │ RAM: 128 GB │ GPU: 24–48 GB │ 3TB SSD   │
└───────────────────────────────────────────────────────────┘
```

---

### Profile D: Cloud GPU Instances (On-Demand)

**Use case**: Burst capacity for large-scope programs, no upfront hardware cost.

| Provider | Instance | GPU | VRAM | vCPUs | RAM | Cost/hr |
|---|---|---|---|---|---|---|
| **RunPod** | 1× A100 | A100 | 80 GB | 12 | 120 GB | ~$1.60 |
| **Vast.ai** | 1× RTX 4090 | RTX 4090 | 24 GB | 16 | 64 GB | ~$0.35 |
| **Vast.ai** | 2× RTX 3090 | 2× RTX 3090 | 48 GB | 16 | 128 GB | ~$0.50 |
| **Lambda** | 1× A6000 | A6000 | 48 GB | 14 | 100 GB | ~$0.80 |
| **AWS** | g5.4xlarge | A10G | 24 GB | 16 | 64 GB | ~$1.00 |
| **GCP** | g2-standard-16 | L4 | 24 GB | 16 | 64 GB | ~$0.85 |

> **Strategy**: Spin up a cloud GPU instance for 4–8 hour intensive hunting sessions, then shut down. Use a persistent small VPS ($5–$20/month) for the Interactsh OOB listener so callbacks arriving after the session ends are still captured.

---

## 4. Storage Breakdown

| Data Category | Growth Rate | Retention | Profile A | Profile B | Profile C |
|---|---|---|---|---|---|
| **Ollama model weights** | Static (per model pull) | Permanent | 10 GB | 30 GB | 80 GB |
| **ChromaDB vector store** | ~50 MB per program target | Per-wing | 500 MB | 2 GB | 10 GB |
| **SQLite relational DB** | ~10 MB per program target | Per-wing | 100 MB | 500 MB | 2 GB |
| **Scan artifacts** (HAR, screenshots, logs) | ~200 MB per scan session | 90 days | 2 GB | 10 GB | 50 GB |
| **Playwright browser binary** | Static | Permanent | 500 MB | 500 MB | 500 MB |
| **Docker images** | Static (per build) | Permanent | 3 GB | 5 GB | 8 GB |
| **Structured logs** (JSON Lines) | ~20 MB per scan session | 30 days | 500 MB | 2 GB | 10 GB |
| **Total estimated** | | | **~17 GB** | **~50 GB** | **~160 GB** |

---

## 5. Network Requirements

### Outbound (Target Traffic)

| Requirement | Detail |
|---|---|
| **Bandwidth** | 10 Mbps minimum; 100 Mbps recommended for parallel fuzzing |
| **Latency** | < 200ms to target (higher latency slows Playwright validation) |
| **HTTP_PROXY** | All target traffic routes through `127.0.0.1:8080` (egress proxy) |
| **TLS Interception** | mitmproxy generates a local CA cert; Playwright and Go tools must trust it |
| **Rate Limiting** | Harness enforces; but ISP/VPN should not impose additional throttling |

### Inbound (Self-Hosted OOB Only)

| Requirement | Detail |
|---|---|
| **Static Public IP** | Required for Interactsh self-hosted DNS/HTTP listeners |
| **Open Ports** | `53/udp` (DNS), `80/tcp` (HTTP), `443/tcp` (HTTPS), `25/tcp` (SMTP) |
| **Domain** | Registered domain with NS records pointing to server IP |
| **Firewall** | Allow inbound on OOB ports; deny all other inbound except SSH |

> **Public OOB mode** (`INTERACTSH_MODE=public`): No inbound ports needed. All callbacks are polled from `oast.me`/`oast.fun` servers over outbound HTTPS.

### VPN Considerations

| Factor | Recommendation |
|---|---|
| **Residential IP** | Preferred — WAFs are less likely to block residential IPs |
| **VPN Provider** | Use a commercial VPN for IP rotation; avoid free VPNs (unstable) |
| **Split Tunneling** | Route target traffic through VPN; keep Ollama/mempalace/internal traffic on local network |
| **DNS Leaks** | Ensure DNS queries for target domains go through VPN, not local resolver |

---

## 6. Software Prerequisites

| Software | Version | Required By | Install Command |
|---|---|---|---|
| **Python** | ≥ 3.10 | Control-plane (core, compliance, agents, etc.) | `apt install python3.10` |
| **Node.js** | ≥ 18 LTS | T3MP3ST, adhd | `nvm install 18` |
| **Go** | ≥ 1.21 | jsleak, BugTraceAI-CLI fuzzers | `snap install go --classic` |
| **Docker** | ≥ 24.0 | Container deployment | `apt install docker.io` |
| **Docker Compose** | ≥ 2.20 | Multi-service orchestration | Bundled with Docker |
| **Ollama** | ≥ 0.3.0 | Local LLM inference | `curl -fsSL https://ollama.ai/install.sh \| sh` |
| **mitmproxy** | ≥ 10.0 | Egress proxy | `pip install mitmproxy` |
| **Playwright** | ≥ 1.40 | DOM validation + screenshots | `pip install playwright && playwright install chromium` |
| **Chromium** | Latest (via Playwright) | Headless browser for validation | Installed by Playwright |
| **NVIDIA Drivers** | ≥ 535 | GPU access for Ollama | `apt install nvidia-driver-535` |
| **CUDA Toolkit** | ≥ 12.1 | GPU compute for Ollama | `apt install nvidia-cuda-toolkit` |
| **NVIDIA Container Toolkit** | Latest | GPU in Docker containers | `apt install nvidia-container-toolkit` |

---

## 7. Quick-Start: Model Pull Commands

```bash
# Profile A (Laptop) — pick ONE primary model
ollama pull qwen2.5-coder:7b        # 4.7 GB — fast, good at code
ollama pull mistral:7b               # 4.1 GB — general purpose fallback

# Profile B (Workstation) — primary + chaining model
ollama pull qwen2.5:14b              # 8.9 GB — strong reasoning
ollama pull deepseek-coder-v2:16b    # 9.4 GB — code review
ollama pull codellama:34b            # 19 GB  — exploit chain reasoning (swap on demand)

# Profile C (Production) — full model arsenal
ollama pull qwen2.5:14b              # 8.9 GB — routine tasks
ollama pull llama3.1:70b             # 40 GB  — deep analysis (swap on demand)
ollama pull codellama:34b            # 19 GB  — exploit chains (swap on demand)

# Verify GPU detection
ollama run qwen2.5-coder:7b "Say hello" --verbose 2>&1 | grep "gpu"
```

---

## 8. Recommended Minimum Specs Summary

| | Profile A (Laptop) | Profile B (Workstation) | Profile C (Production) |
|---|---|---|---|
| **CPU** | 4 cores | 8 cores | 16 cores |
| **RAM** | 16 GB | 64 GB | 128 GB |
| **GPU VRAM** | 6–12 GB | 16–24 GB | 24–48 GB |
| **Storage** | 50 GB SSD | 500 GB NVMe | 1 TB NVMe + 2 TB SSD |
| **Network** | Broadband | 100 Mbps | 1 Gbps + static IP |
| **Concurrent Specialists** | 1–2 | 6–8 | All 16 |
| **Playwright Instances** | 1 | 2–3 | 4–6 |
| **Interactsh** | Public (`oast.me`) | Public | Self-hosted (own domain) |
| **Monthly Cost** | $0–$5 | $0–$10 | $5–$15 + infra |
| **Best For** | Learning, single targets | Active daily hunting | 24/7 autonomous multi-program |
