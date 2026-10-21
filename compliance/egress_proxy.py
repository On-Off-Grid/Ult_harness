# compliance/egress_proxy.py
"""
EgressProxy: mitmproxy addon enforcing ScopeGate on all outbound HTTP traffic.

Features:
- request(flow) hook calls ScopeGate.is_in_scope(flow.request.pretty_url).[cite:2]
- Out-of-scope → 403 "Out of scope" synthetic response.
- HARNESS_DRY_RUN=true → log WOULD ALLOW / WOULD DROP, return mock responses
  without sending packets externally.[cite:1]
- Strip X-Harness-Traffic header from all outbound requests.
- OSINT defense-in-depth:
  - OSINT allowlist domains always allowed.
  - Non-OSINT + X-Harness-Traffic: osint → dropped + security warning logged.[cite:1]
- Passive CDN allowlist logged as passive (e.g. fonts.googleapis.com, cdn.jsdelivr.net).[cite:1]
- Logs JSON Lines to ./workspace/<wing_id>/logs/egress_proxy.jsonl.[cite:1]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is importable when mitmdump loads this script,
# regardless of the working directory mitmdump was launched from.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from mitmproxy import http  # type: ignore

from core.config import HarnessConfig
from core.types import TargetScope, ScopeRule, ScopeMatchType, Platform
from compliance.scope_gate import ScopeGate
from compliance.scope_importer import ScopeImporter

# mitmproxy >= 11 removed `ctx.log`; use a standard logger so this works both
# inside a live `mitmdump` process and when the module is imported standalone
# (e.g. the S2 trust-audit smoke test).
logger = logging.getLogger("harness.egress_proxy")

# Passive CDNs to treat as non-target traffic.[cite:1]
_PASSIVE_CDNS = {
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
}

_OSINT_HEADER = "X-Harness-Traffic"


def _load_scope_from_env() -> ScopeGate:
    """
    Helper: construct a ScopeGate from environment variables.

    Expected env:
    - HARNESS_SCOPE_FILE: path to a scope file. Accepted formats:
      * the NORMALIZED workspace format ``workspace/<program>/scope.json``
        (``in_scope``/``out_of_scope`` lists — what `main.py init` writes and
        what a live `hunt` points the gate at);
      * H1 CSV (``.csv``);
      * Bugcrowd-shaped JSON (a JSON object whose rules live under ``targets``).
    - HARNESS_SCOPE_FORMAT: "hackerone_csv" | "bugcrowd_json" |
      "normalized_json" (inferred from the file when omitted)
    - HARNESS_WORKSPACE + HARNESS_PROGRAM_HANDLE: fallback location of the
      normalized scope.json when HARNESS_SCOPE_FILE is not set.

    The permissive ``*`` wildcard is a START-UP FALLBACK, not a policy: if no
    scope file can be located or parsed, the proxy logs a WARNING and allows
    everything so mitmdump can still start. A live hunt must point the gate
    at a real scope file (``main.py run``/``hunt`` do this) — the warning is
    the operator's signal that the gate is not enforcing program scope.
    """
    program_handle = os.getenv("HARNESS_PROGRAM_HANDLE", "default-program")
    scope_file = os.getenv("HARNESS_SCOPE_FILE")

    # Fallback: the live `hunt`/`run` boots the gate from the workspace
    # scope.json produced by `init` (HARNESS_SCOPE_FILE is authoritative when
    # set; this covers any boot path that forgets it).
    if not scope_file:
        ws = os.getenv("HARNESS_WORKSPACE", "")
        if ws:
            candidate = str(Path(ws) / program_handle / "scope.json")
            if os.path.exists(candidate):
                scope_file = candidate

    if not scope_file or not os.path.exists(scope_file):
        logger.warning(
            "EgressProxy: no scope file (HARNESS_SCOPE_FILE unset / missing "
            f"and no {os.getenv('HARNESS_WORKSPACE','')}/{program_handle}/scope.json) "
            "— falling back to a PERMISSIVE '*' wildcard. The scope gate is "
            "NOT enforcing program scope. Export the scope and re-run."
        )
        ts = TargetScope(
            program_handle=program_handle,
            platform=Platform.HACKERONE,
            in_scope=[ScopeRule(pattern="*", match_type=ScopeMatchType.WILDCARD)],
        )
        return ScopeGate(ts)

    scope_fmt = os.getenv("HARNESS_SCOPE_FORMAT") or \
        ScopeImporter.detect_format(scope_file)

    try:
        if scope_fmt == "bugcrowd_json":
            ts = ScopeImporter.parse_bugcrowd_json(scope_file, program_handle)
        elif scope_fmt == "normalized_json":
            ts = ScopeImporter.parse_workspace_json(scope_file, program_handle)
        else:
            ts = ScopeImporter.parse_hackerone_csv(scope_file, program_handle)
    except Exception as exc:
        # A malformed scope must fail CLOSED (permissive) with a loud log,
        # never crash the mitmdump addon and take the whole hunt's egress down.
        logger.warning(
            f"EgressProxy: failed to parse {scope_file} "
            f"(format={scope_fmt!r}: {exc.__class__.__name__}: {exc}) — "
            "falling back to a PERMISSIVE '*' wildcard"
        )
        ts = TargetScope(
            program_handle=program_handle,
            platform=Platform.HACKERONE,
            in_scope=[ScopeRule(pattern="*", match_type=ScopeMatchType.WILDCARD)],
        )
    logger.info(
        f"EgressProxy scope: {scope_file} (format={scope_fmt}, "
        f"{len(ts.in_scope)} in-scope / {len(ts.out_of_scope)} out-of-scope rule(s))"
    )
    return ScopeGate(ts)


class EgressProxy:
    def __init__(self):
        self.cfg = HarnessConfig.load_from_env()
        self.dry_run = self.cfg.dry_run
        self.scope_gate = _load_scope_from_env()
        self.wing_id = os.getenv("HARNESS_WING_ID", "default-wing")
        self.workspace_dir = self.cfg.workspace_dir
        self.log_path = os.path.join(
            self.workspace_dir,
            self.wing_id,
            "logs",
            "egress_proxy.jsonl",
        )
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        logger.info(
            f"EgressProxy initialized (dry_run={self.dry_run}) "
            f"log={self.log_path}"
        )

    def _log(self, flow: http.HTTPFlow, decision: str, reason: str, passive: bool = False):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "component": "egress_proxy",
            "correlation_id": flow.request.headers.get("X-Correlation-ID", ""),
            "level": "INFO",
            "msg": decision,
            "data": {
                "url": flow.request.pretty_url,
                "host": flow.request.host,
                "method": flow.request.method,
                "reason": reason,
                "passive": passive,
            },
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def request(self, flow: http.HTTPFlow) -> None:
        """
        mitmproxy hook: called before sending the request upstream.[cite:3][cite:4]
        """
        # Strip harness traffic header so targets never see it.[cite:1]
        osint_flag = flow.request.headers.pop(_OSINT_HEADER, None)

        host = flow.request.host or ""
        url = flow.request.pretty_url

        # Passive CDN classification: log as passive and allow through.
        if host in _PASSIVE_CDNS:
            self._log(flow, "[PASSIVE CDN]", "Passive resource", passive=True)
            return

        # OSINT defense-in-depth: if header claims osint but host is not allowlist → drop.[cite:1]
        if osint_flag == "osint" and not self.scope_gate._is_osint_domain(host):
            decision = "[DROP] OSINT header on non-OSINT domain"
            self._log(flow, decision, "osint_header_abuse")
            if self.dry_run:
                flow.response = http.Response.make(
                    403,
                    b"Dry-run: OSINT abuse detected",
                    {"Content-Type": "text/plain"},
                )
                return
            flow.response = http.Response.make(
                403,
                b"Out of scope (OSINT abuse)",
                {"Content-Type": "text/plain"},
            )
            return

        # Main scope decision
        allowed = self.scope_gate.is_in_scope(url)

        if self.dry_run:
            # Dry-run: simulate but do not send real traffic.[cite:1]
            decision = "[DRY-RUN WOULD ALLOW]" if allowed else "[DRY-RUN WOULD DROP]"
            reason = "dry_run_simulation"
            self._log(flow, decision, reason)
            # Return mock responses
            if allowed:
                flow.response = http.Response.make(
                    200,
                    b"Dry-run: allowed",
                    {"Content-Type": "text/plain"},
                )
            else:
                flow.response = http.Response.make(
                    403,
                    b"Dry-run: out of scope",
                    {"Content-Type": "text/plain"},
                )
            return

        if not allowed:
            decision = "[DROP] Out of scope"
            self._log(flow, decision, "scope_gate_denied")
            flow.response = http.Response.make(
                403,
                b"Out of scope",
                {"Content-Type": "text/plain"},
            )
            return

        # Allowed traffic — just log and let it pass
        decision = "[ALLOW] In scope"
        self._log(flow, decision, "scope_gate_allowed")


addons = [EgressProxy()]
