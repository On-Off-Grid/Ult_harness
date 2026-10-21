# tests/test_s2_scope_gate.py  — S2.2: compliance/scope_gate.py (+ scope_importer)
"""In-scope passes, out-of-scope rejected, plus scope-import from sample files."""
from __future__ import annotations

import json

import pytest

from core.types import Platform, ScopeRule, ScopeMatchType, TargetScope
from compliance.scope_gate import ScopeGate
from compliance.scope_importer import ScopeImporter


def _scope(in_rules, out_rules=()):
    return TargetScope(
        program_handle="acme",
        platform=Platform.HACKERONE,
        in_scope=[ScopeRule(p, m) for p, m in in_rules],
        out_of_scope=[ScopeRule(p, m) for p, m in out_rules],
    )


def test_wildcard_in_scope_passes():
    gate = ScopeGate(_scope([("*.example.com", ScopeMatchType.WILDCARD)]))
    assert gate.is_in_scope("https://www.example.com/page") is True
    assert gate.is_in_scope("https://app.example.com/api") is True


def test_wildcard_does_not_match_apex():
    # fnmatch('example.com', '*.example.com') is False — the apex is out of scope.
    gate = ScopeGate(_scope([("*.example.com", ScopeMatchType.WILDCARD)]))
    assert gate.is_in_scope("https://example.com/") is False


def test_exact_match():
    gate = ScopeGate(_scope([("api.example.com", ScopeMatchType.EXACT)]))
    assert gate.is_in_scope("https://api.example.com/x") is True
    assert gate.is_in_scope("https://api.example.com.evil.com/x") is False


def test_regex_match():
    gate = ScopeGate(_scope([("^api\\d+\\.example\\.com$", ScopeMatchType.REGEX)]))
    assert gate.is_in_scope("https://api1.example.com/") is True
    assert gate.is_in_scope("https://apiX.example.com/") is False


def test_cidr_match():
    # CIDR matching is exercised against a *public* range (RFC 5737 TEST-NET-1).
    # Note: RFC1918/metadata IPs (10.x, 192.168.x, 169.254.x) are hard-blocked
    # by the DNS-rebinding check at an earlier step, so they can never be
    # "allowed in scope" even if a CIDR rule would match them.
    gate = ScopeGate(_scope([("192.0.2.0/24", ScopeMatchType.CIDR)]))
    assert gate.is_in_scope("https://192.0.2.55/") is True
    assert gate.is_in_scope("https://192.0.3.55/") is False
    # …and the hard block wins over any CIDR rule:
    assert gate.is_in_scope("https://10.1.2.3/") is False


def test_internal_cidr_rules_cannot_override_hard_block():
    # Even an explicit in-scope CIDR for the loopback block must not allow 127.x
    gate = ScopeGate(_scope([("127.0.0.0/8", ScopeMatchType.CIDR)]))
    assert gate.is_in_scope("https://127.0.0.1/admin") is False


def test_out_of_scope_rule_precedes_in_scope():
    scope = _scope(
        in_rules=[("*.example.com", ScopeMatchType.WILDCARD)],
        out_rules=[("beta.example.com", ScopeMatchType.EXACT)],
    )
    gate = ScopeGate(scope)
    assert gate.is_in_scope("https://beta.example.com/") is False   # explicit deny wins
    assert gate.is_in_scope("https://www.example.com/") is True


def test_default_deny_when_nothing_matches():
    gate = ScopeGate(_scope([("*.example.com", ScopeMatchType.WILDCARD)]))
    assert gate.is_in_scope("https://evil.com/") is False


def test_empty_scope_denies_everything():
    gate = ScopeGate(_scope([]))
    assert gate.is_in_scope("https://anything.com/") is False


def test_dns_rebinding_hard_block():
    # Even if a scope rule *would* match, internal/metadata targets must be blocked.
    scope = _scope([("*", ScopeMatchType.WILDCARD)])
    gate = ScopeGate(scope)
    assert gate.is_in_scope("https://169.254.169.254/latest/meta-data/") is False
    assert gate.is_in_scope("https://localhost/admin") is False
    assert gate.is_in_scope("https://127.0.0.1/") is False
    assert gate.is_in_scope("https://10.0.0.5/") is False
    assert gate.is_in_scope("https://192.168.1.1/") is False


def test_third_party_hard_block():
    scope = _scope([("*", ScopeMatchType.WILDCARD)])
    gate = ScopeGate(scope)
    assert gate.is_in_scope("https://api.stripe.com/v1") is False
    assert gate.is_in_scope("https://okta.com/login") is False
    assert gate.is_in_scope("https://sentry.io/o/1") is False


def test_osint_allowlist_hard_allow():
    # OSINT allowlist is a hard allow even when not in the program scope.
    gate = ScopeGate(_scope([("*.example.com", ScopeMatchType.WILDCARD)]))
    assert gate.is_in_scope("https://api.github.com/repos/x") is True
    assert gate.is_in_scope("https://www.googleapis.com/...") is True


def test_websocket_scheme_treated_as_http():
    gate = ScopeGate(_scope([("*.example.com", ScopeMatchType.WILDCARD)]))
    assert gate.is_in_scope("wss://ws.example.com/socket") is True
    assert gate.is_in_scope("ws://ws.example.com/socket") is True


def test_hostless_url_rejected():
    gate = ScopeGate(_scope([("*", ScopeMatchType.WILDCARD)]))
    assert gate.is_in_scope("not a url") is False


# ── Scope import from sample program files ──────────────────────────────

def test_import_hackerone_csv(tmp_path):
    csv_file = tmp_path / "h1.csv"
    csv_file.write_text(
        "asset_type,asset_identifier,eligible_for_bounty\n"
        "URL,*.example.com,true\n"
        "URL,api.example.com,true\n"
        "URL,legacy.example.com,false\n"
    )
    ts = ScopeImporter.parse_hackerone_csv(str(csv_file), "acme")
    assert ts.platform is Platform.HACKERONE
    patterns_in = {r.pattern for r in ts.in_scope}
    patterns_out = {r.pattern for r in ts.out_of_scope}
    assert patterns_in == {"*.example.com", "api.example.com"}
    assert patterns_out == {"legacy.example.com"}
    # The wildcard one must be typed WILDCARD, the exact one EXACT.
    by = {r.pattern: r.match_type for r in ts.in_scope}
    assert by["*.example.com"] is ScopeMatchType.WILDCARD
    assert by["api.example.com"] is ScopeMatchType.EXACT


def test_import_bugcrowd_json(tmp_path):
    json_file = tmp_path / "bc.json"
    json_file.write_text(json.dumps({
        "targets": [
            {"name": "*.acme.com", "category": "URL", "in_scope": True},
            {"name": "dev.acme.com", "category": "URL", "in_scope": False},
        ]
    }))
    ts = ScopeImporter.parse_bugcrowd_json(str(json_file), "acme")
    patterns_in = {r.pattern for r in ts.in_scope}
    patterns_out = {r.pattern for r in ts.out_of_scope}
    assert patterns_in == {"*.acme.com"}
    assert patterns_out == {"dev.acme.com"}


# ── Normalized workspace scope (what `main.py init` writes and the live
#    egress gate is pointed at via HARNESS_SCOPE_FILE) ─────────────────────

def test_import_normalized_workspace_json(tmp_path):
    sj = tmp_path / "scope.json"
    sj.write_text(json.dumps({
        "program_handle": "acme",
        "platform": "intigriti",
        "in_scope": [
            {"pattern": "www.acme.com", "match_type": "exact", "description": ""},
            {"pattern": "*.acme.com", "match_type": "wildcard", "description": ""},
            {"pattern": "193.58.149.121/32", "match_type": "cidr", "description": "ip"},
        ],
        "out_of_scope": [
            {"pattern": "book.acme.com", "match_type": "exact", "description": ""},
        ],
        "rate_limit_rps": 10.0, "max_concurrent": 5,
    }))
    ts = ScopeImporter.parse_workspace_json(str(sj), "ignored-handle")
    assert ts.program_handle == "acme"                 # file wins over arg
    assert ts.platform is Platform.INTIGRITI
    assert {r.pattern for r in ts.in_scope} == {
        "www.acme.com", "*.acme.com", "193.58.149.121/32"}
    assert {r.pattern for r in ts.out_of_scope} == {"book.acme.com"}
    by = {r.pattern: r.match_type for r in ts.in_scope}
    assert by["www.acme.com"] is ScopeMatchType.EXACT
    assert by["*.acme.com"] is ScopeMatchType.WILDCARD
    assert by["193.58.149.121/32"] is ScopeMatchType.CIDR
    # A rule with a missing/odd match_type falls back to shape inference.
    sj.write_text(json.dumps({
        "program_handle": "acme", "platform": "intigriti",
        "in_scope": [{"pattern": "*.kwsdose.be"}],
        "out_of_scope": [],
    }))
    ts2 = ScopeImporter.parse_workspace_json(str(sj), "acme")
    assert ts2.in_scope[0].match_type is ScopeMatchType.WILDCARD


def test_import_normalized_workspace_rejects_non_scope(tmp_path):
    bad = tmp_path / "notscope.json"
    bad.write_text(json.dumps({"targets": [{"name": "x"}]}))
    with pytest.raises(ValueError):
        ScopeImporter.parse_workspace_json(str(bad), "acme")


def test_detect_format():
    # (handled by conftest-independent helpers on a real path) — exercise the
    # suffix + JSON-shape logic with a tmp file.
    import tempfile, os
    d = tempfile.mkdtemp()
    norm = os.path.join(d, "scope.json")
    with open(norm, "w") as f:
        json.dump({"in_scope": [], "out_of_scope": []}, f)
    bc = os.path.join(d, "bugcrowd.json")
    with open(bc, "w") as f:
        json.dump({"targets": []}, f)
    csvf = os.path.join(d, "h1.csv")
    with open(csvf, "w") as f:
        f.write("asset_type,asset_identifier\n")
    assert ScopeImporter.detect_format(norm) == "normalized_json"
    assert ScopeImporter.detect_format(bc) == "bugcrowd_json"
    assert ScopeImporter.detect_format(csvf) == "hackerone_csv"
    # An extensionless path falls back to the legacy default.
    assert ScopeImporter.detect_format(os.path.join(d, "scope")) == "hackerone_csv"


def test_osint_allowlist_covers_passive_recon_sources():
    # These passive recon sources must be hard-allowed even when absent from
    # the program scope — otherwise a correctly-enforced scope drops every
    # recon source and the recon phase returns nothing (verified live: the
    # cbb pipeline queries exactly these).
    gate = ScopeGate(_scope([("*.example.com", ScopeMatchType.WILDCARD)]))
    for host in ("crt.sh", "web.archive.org", "api.pdtm.sh", "github.com",
                 "raw.githubusercontent.com", "api.urlscan.io"):
        assert gate.is_in_scope(f"https://{host}/x") is True, host
