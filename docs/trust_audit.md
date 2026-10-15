# S2 Trust Audit — Control-Plane Verification

**Date:** 2026-10-15
**Scope:** the ~3,350-line Python control plane (38 files) — treated as *unverified* until proven, per `specs/assembly_plan_v3.md` Phase S2 ("Classify, don't assume").
**Method:** a 104-test pytest smoke/unit suite (`tests/test_s2_*.py`) written against the *intended* behavior, then run against the as-shipped code. Every RED was either fixed in place (same interface) or given a disposition. Verdicts below reflect the code **after** the S2 fixes.

## How to run

```bash
cd Ult_harness
python3 -m pytest tests/ -q
# → 104 passed
```

No venv required: the control plane's only third-party imports are `aiohttp` + `mitmproxy` (both system-installed). Tests use no network (the one health-check test targets a closed localhost port) and never touch the real `./workspace` or operator env.

## Verdicts (S2.1 – S2.9)

| # | Package | Verdict | Tests | Notes |
|---|---|---|---|---|
| S2.1 | `core/` (types, config, event_bus) | ✅ GREEN | 5 | pub/sub round-trip, unsubscribe, unknown-topic no-op; env config parse; budget math |
| S2.2 | `compliance/scope_gate.py` (+ importer) | ✅ GREEN | 16 | wildcard/exact/regex/CIDR; explicit-deny precedence; DNS-rebinding + third-party hard blocks **override in-scope rules**; OSINT hard-allow; default deny; H1 CSV + Bugcrowd JSON import |
| S2.3 | `compliance/egress_proxy.py` | ✅ GREEN | 10 | **20-line fixture replayed end-to-end** (reconstructed `*.example.com` scope): every recorded WOULD ALLOW/DROP reproduced; OSINT-header-abuse drop; passive-CDN pass-through; jsonl log write |
| S2.4 | `compliance/header_injector.py` + `oob_engine.py` | ✅ GREEN | 9 | `from_profile` file loader, UA auto-injection, flat `key: value` export for Go tools, rate-limit ctx; OOB payload shape/uniqueness, poll/close skeleton |
| S2.5 | `budget/model_router.py` + `token_tracker.py` | ✅ GREEN | 18 | routing table (38 tasks) verified incl. fallback chains + `NoBudgetError`; Ollama-unreachable promotion; ledger cost math; warning/exhausted events fire exactly once; wing summary. ⚠️ see findings F5/F6 |
| S2.6 | `triage/noise_filter.py` + `state_machine.py` | ✅ GREEN | 19 | known-FP drops (headers, self-XSS, rate-limit); both-keyword required; legal transitions only; FP-reason enforced; terminal states; event emission; history/counts |
| S2.7 | `sessions/session_manager.py` + `dual_session_tester.py` | ✅ GREEN | 13 | bootstrap/refresh/shutdown network-free (stubbed `_login`); token re-apply; matrix persona order + header merge (stubbed session); `analyze_results` IDOR/BAC rules. ⚠️ see finding F4 |
| S2.8 | `agents/` (16 specialists + base + mixins) | ✅ GREEN | 7 | all 16 import, instantiate, unique `VulnCategory`, `scan` signature intact; OOB/DualSession wiring. Plan wording ("frontmatter / model field / tool refs") targets markdown agent specs — the faithful Python equivalent is import+instantiate+category+signature, verified here |
| S2.9 | `scripts/ingest_*.py` | ✅ GREEN (after fix) | 7 | dry-run on sample corpus works **with neither chromadb nor mempalace importable**; exit 0 on missing root; top-level import deferral locked in. ⚠️ see findings F1–F3 |

**Gate S2: PASS** — `pytest -q` is green; no RED without a disposition.

## Bugs found & fixed in S2 (all in this commit)

| ID | File | Bug | Fix |
|---|---|---|---|
| **F1** | `compliance/egress_proxy.py` | mitmproxy 12.x removed `ctx.log`; module used `ctx.log.info` in `__init__` → **import failure** (the whole egress gate was unloadable) | stdlib `logging` logger (`harness.egress_proxy`); `ctx` import dropped |
| **F2** | `agents/dual_session_tester.py` | `NameError: Optional` — used but not imported | added to the `typing` import |
| **F3** | `scripts/ingest_*.py` (both) | top-level `from mempalace…` (+ `chromadb` transitively) → even `--dry-run` crashed on any machine without the mempalace checkout; and `ChromaBackend()` was constructed *before* the dry-run branch; `main()` built `MempalaceConfig()` even for dry-run | all three mempalace imports deferred into the non-dry-run paths; dry-run is now dependency-free (pure file scan + report) |
| **F4** | `sessions/session_manager.py` | `bootstrap_sessions` (called by `force_refresh`) **replaced** `self.context` with a new object. Callers holding the original reference (an orchestrator passing `ctx` to specialist scans) would keep using **stale tokens forever** — the "refresh on 401" contract was silently broken | mutate the existing context in place on re-bootstrap (object identity preserved; `MultiSessionContext` default `unauth_headers` now set once at creation) |
| **F5** | `budget/token_tracker.py` | routing table sends `chain_narrative` → `claude-sonnet-4-20250514`, which was **absent from `MODEL_COSTS`** → premium usage silently billed at $0 | added the dated alias at claude-sonnet-4 pricing; locked by invariant test `test_every_routed_model_has_a_cost_entry` (every routed model must have a cost entry) |
| **F6** | `budget/token_tracker.py` | `MODEL_COSTS` listed 4 premium keys (`gpt-4o`, `gpt-4o-mini`, `claude-sonnet-4`, `claude-haiku`) of which only `gpt-4o` was actually routed | cosmetic only (fail-safe is $0, which is what happens on the free tiers anyway); cleaned up in S5.4 router reimplementation — no code change in S2 |

## Findings (not bugs — dispositions / notes)

- **N1 — 3-tier vs 4-tier routing.** The plan's S2.5 wording (`LOCAL_LIGHT → LOCAL_HEAVY → PAID_FREE → PAID_PREMIUM`) describes the **new S5 structure**. The audited router is the older 3-tier (`LOCAL / PAID_FREE / PAID_PREMIUM`, 21/15/2 task split). It is correct *for what it is*; the light/heavy split + provider lanes (Groq primary, OpenRouter failover, GPU gateway, RESTRICTED-lane scrubbing) are the S5.4 reimplementation.
- **N2 — Declared deps ≠ actual deps.** `pyproject.toml` declares `fastapi`, `chromadb`, `cvss` but the control plane never imports them (only `aiohttp` + `mitmproxy`). `chromadb` is genuinely needed by the ingest scripts via mempalace; `fastapi`/`cvss` appear to be aspirational (S3/S4 will tell). Trim when S3 lands its real dep set.
- **N3 — `OOBEngine.poll_callbacks` is a skeleton** (returns `[]`; no Interactsh API integration). Fine for S2 (shape/contract verified); the real interaction correlation is S3/S4 scope. Same for the `interactsh_mode="selfhosted"` path.
- **N4 — `datetime.utcnow()` deprecation** (Python 3.13 warnings) in `egress_proxy`, `types`, `token_tracker`. Cosmetic; sweep in S3 housekeeping.
- **N5 — `DualSessionMixin` is a placeholder** (no state). The real IDOR/BAC logic lives in `DualSessionTester` which both IDOR/BAC specialists instantiate per-scan. Verified working; no change needed.
- **N6 — `ScopeImporter.parse_h1_csv` wildcard sniff** uses `"*. " in identifier` (stray space) alongside `startswith("*.")` — the startswith check is what actually fires; the `"*. "` form looks like a typo. Harmless (union of conditions) but worth cleaning in S3.
- **N7 — Live-run path of the egress proxy** (`if not allowed: 403` / allow-through) is exercised only via dry-run replay + code inspection; a live `mitmdump` E2E is the S4 gate.

## What the replay proved (S2.3 detail)

The only run-evidence in the repo is `workspace/default-wing/logs/egress_proxy.jsonl` (20 lines, 2026-08-10). It is **internally consistent with a single `*.example.com` wildcard scope**:

| host | recorded | replay |
|---|---|---|
| `www.example.com` / `app.example.com` | WOULD ALLOW | 200 ✓ |
| `example.com` (apex) | WOULD DROP | 403 ✓ (fnmatch `*.example.com` doesn't match the apex — correct behavior, not a bug) |
| `evil.com` | WOULD DROP | 403 ✓ |

All 20 lines reproduce 1:1 through the current `EgressProxy.request` decision path (driven with a duck-typed flow — mitmproxy 12's `HTTPFlow` constructor is too strict for fixtures, and the hook only needs `request.{host,pretty_url,method,headers}` + a settable `response`).

## Next (S3)

Per plan: build the missing core (`orchestrator/`, `reporting/`, `main.py`) carrying the never-implemented 4.6–4.12 component wiring (see `patches/local-tweaks.md` correction), then S4 E2E gate, S5 routing redesign (blocked on the 4 API keys), S6 docs + umbrella sync.
