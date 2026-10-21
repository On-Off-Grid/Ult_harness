# tests/test_uzleuven_scope.py — UZ Leuven (Intigriti) scope pipeline
"""Simple end-to-end check that the fetched UZ Leuven scope survives the whole
pipeline: `build_scope_payload` (tier/type mapping) → `parse_bugcrowd_json`
(match-type inference) → `ScopeGate` (allow/deny) → `derive_targets`
(launchable hosts).

These assertions encode what the program page says as of 2026-10-19
(handle `uzleuven`, 30 in-scope / 20 out-of-scope; see
docs/examples/uzleuven_intigriti.md). The shapes that motivated this file
are UZ Leuven's real ones: a comma-listed `IpRange`, a Tier-3
`*.uzleuven.*` catch-all, an `Out Of Scope` tier, and out-of-scope globs
(`*dev.`, `*idp*`, `*stag*`, `*.contactallerg(y|ie).`) that must still deny
even though the broader in-scope wildcard would match them.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from core.types import Platform, ScopeMatchType, ScopeRule
from compliance.scope_gate import ScopeGate
from compliance.scope_importer import ScopeImporter
import orchestrator.hunt_launcher as hl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FETCH_SCRIPT = PROJECT_ROOT / "scripts" / "fetch_intigriti_scope.py"
FROZEN = PROJECT_ROOT / "tests" / "fixtures" / "uzleuven_program.json"

# UZ Leuven scope facts, read off the program page + Researcher API on 2026-10-19.
# The page lists 22 in-scope ASSETS (Tier 1: 11, Tier 2: 7, Tier 3: 4) — one of
# which is the 7-IP reverse-proxy list. The scope file expands that list into
# 7 /32 rules, so the gate sees 22 - 1 + 7 = 28 in-scope RULES.
IN_SCOPE = 28
OUT_OF_SCOPE = 20  # 12 "No Bounty" + 8 "Out Of Scope" tier assets


def _fetch_module():
    spec = importlib.util.spec_from_file_location("fetch_intigriti_scope", FETCH_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _uzleuven_program() -> dict:
    """Live GET when the operator's INTIGRITI_API_KEY is available (the whole
    point of this file); otherwise a frozen copy of the same API response."""
    try:
        mod = _fetch_module()
        return mod.fetch_program(mod._load_key(), "uzleuven")
    except BaseException:
        assert FROZEN.exists(), "no live API key and no frozen fixture"
        return json.loads(FROZEN.read_text(encoding="utf-8"))


def _payload() -> dict:
    return _fetch_module().build_scope_payload(_uzleuven_program(), "uzleuven")


def _gate(tmp_path) -> ScopeGate:
    """build_scope_payload → parse_bugcrowd_json — exactly what `init` runs."""
    scope_file = tmp_path / "uzleuven.json"
    scope_file.write_text(json.dumps(_payload(), ensure_ascii=False),
                          encoding="utf-8")
    ts = ScopeImporter.parse_bugcrowd_json(str(scope_file), "uzleuven")
    assert ts.platform is Platform.BUGCROWD  # bugcrowd-shaped, per `init --format`
    return ScopeGate(ts)


# ── fetch-layer mapping (the tier/type editorial calls) ───────────────────

def test_fetched_counts_match_program_page():
    payload = _payload()
    n_in = sum(1 for t in payload["targets"] if t["in_scope"])
    n_out = len(payload["targets"]) - n_in
    # Page: 22 in-scope assets / 20 out-of-scope. Rules: 28 in-scope (the
    # 7-IP list expands to 7 rules) / 20 out-of-scope.
    assert n_in == IN_SCOPE, f"expected {IN_SCOPE} in-scope rules, got {n_in}"
    assert n_out == OUT_OF_SCOPE, f"expected {OUT_OF_SCOPE} out-of-scope, got {n_out}"


def test_ip_range_expands_to_one_rule_per_ip():
    ips = [t for t in _payload()["targets"] if t["name"].startswith("193.58.149.")]
    assert len(ips) == 7
    assert all(t["name"].endswith("/32") for t in ips)
    assert all(t["in_scope"] for t in ips)


def test_regex_like_wildcard_is_rewritten():
    regexy = [t for t in _payload()["targets"] if "(" in t["name"]]
    assert len(regexy) == 1                      # *.contactallerg(y|ie).uzleuven.be
    assert regexy[0]["name"] == r".*\.contactallerg(y|ie)\.uzleuven\.be$"
    assert regexy[0]["in_scope"] is False


def test_out_of_scope_tier_is_not_in_scope():
    by_name = {t["name"]: t for t in _payload()["targets"]}
    for host in ("boekentoy.uzleuven.be", "jobs.uzleuven.be",
                 "uzleuven.atlassian.net", "vacatures.uzleuven.be"):
        assert by_name[host]["in_scope"] is False, f"{host} must be out of scope"


def test_payload_carries_roe_testing_requirements():
    # The UZ Leuven RoE requires researchers to send
    # `X-Intigriti-Username: {Username}`; the fetch layer must surface the
    # structured testing-requirements so `init` can merge them into the
    # platform profile / headers.txt automatically (no manual headers.txt
    # edit, and nothing program-specific downstream).
    tr = _payload().get("_testing_requirements")
    assert isinstance(tr, dict), "fetched payload must carry _testing_requirements"
    assert tr["requestHeader"] == "X-Intigriti-Username: {Username}"
    assert tr["userAgent"] is None
    assert tr["automatedTooling"] == 5
    assert tr["intigritiMe"] is True
    assert tr["safeHarbour"] is True


def test_payload_marker_makes_stale_caches_detectable():
    # `main.py hunt` refreshes cached fetches whose generator marker no
    # longer matches the fetch script — so a cache from an older schema
    # (no RoE metadata) is never served silently.
    mod = _fetch_module()
    assert mod.GEN_MARKER.startswith("Generated by scripts/fetch_intigriti_scope.py")
    first = _payload()["_comment"][0]
    assert first.startswith(mod.GEN_MARKER)


# ── import + gate: allow / deny behavior ─────────────────────────────────

def test_gate_allows_tier1_host(tmp_path):
    gate = _gate(tmp_path)
    assert gate.is_in_scope("https://www.uzleuven.be/") is True
    assert gate.is_in_scope("https://extranet.uzleuven.be/page") is True


def test_gate_allows_wildcard_hosts(tmp_path):
    gate = _gate(tmp_path)
    assert gate.is_in_scope("https://foo.kwsdose.be/x") is True
    assert gate.is_in_scope("https://a.playuzleuven.be/") is True
    # The Tier-3 catch-all covers every other uzleuven.be subdomain.
    assert gate.is_in_scope("https://anything.uzleuven.be/") is True


def test_gate_allows_reverse_proxy_ips(tmp_path):
    gate = _gate(tmp_path)
    assert gate.is_in_scope("https://193.58.149.121/") is True
    assert gate.is_in_scope("https://193.58.149.98/admin") is True
    # An IP that is NOT in the list stays blocked (default deny).
    assert gate.is_in_scope("https://193.58.149.200/") is False


def test_gate_denies_no_bounty_hosts_despite_catch_all(tmp_path):
    gate = _gate(tmp_path)
    # Exact out-of-scope hosts.
    assert gate.is_in_scope("https://files.uzleuven.be/") is False
    assert gate.is_in_scope("https://kumulus.uzleuven.be/") is False
    assert gate.is_in_scope("https://mijnacc.uzleuven.be/") is False
    assert gate.is_in_scope("https://ziekenhuisschool.be/") is False
    assert gate.is_in_scope("https://boekentoy.uzleuven.be/") is False
    # Glob out-of-scope hosts — these match the Tier-3 catch-all
    # *.uzleuven.*; only a working deny rule can keep them out (the pre-fix
    # bug: they were imported as inert EXACT rules).
    assert gate.is_in_scope("https://dev.uzleuven.be/") is False
    assert gate.is_in_scope("https://mydev.uzleuven.be/") is False
    assert gate.is_in_scope("https://idp.uzleuven.be/") is False
    assert gate.is_in_scope("https://idp2.uzleuven.be/") is False
    assert gate.is_in_scope("https://staging.uzleuven.be/") is False
    assert gate.is_in_scope("https://stage.uzleuven.be/") is False
    # The regex-alternation deny rule (fnmatch cannot express it).
    assert gate.is_in_scope("https://x.contactallergy.uzleuven.be/") is False
    assert gate.is_in_scope("https://x.contactallergie.uzleuven.be/") is False
    # Unrelated hosts: default deny.
    assert gate.is_in_scope("https://evil.com/") is False
    assert gate.is_in_scope("https://uzleuven.be.evil.com/") is False


def test_gate_matches_wildcard_case_insensitively(tmp_path):
    gate = _gate(tmp_path)
    assert gate.is_in_scope("https://FOO.KWSDOSE.be/x") is True


def test_invalid_regex_rule_never_crashes_gate(tmp_path):
    # A malformed regex (e.g. a raw `*dev.x` hand-typed into the scope file)
    # must be treated as no-match — never raise, never fail open.
    gate = _gate(tmp_path)
    gate.target_scope.in_scope.append(
        ScopeRule("*dev.uzleuven.be", ScopeMatchType.REGEX, "bad"))
    assert gate.is_in_scope("https://www.uzleuven.be/") is True
    assert gate.is_in_scope("https://dev.uzleuven.be/") is False  # still denied


# ── target derivation for `hunt` ──────────────────────────────────────────

def test_derive_targets_excludes_ips_and_splits_paths(tmp_path):
    scope = _gate(tmp_path).target_scope
    per, urls, wild = hl.derive_targets(scope, max_targets=3)
    # No launchable host may be a bare IP/CIDR.
    assert not any(p.replace(".", "").replace("/", "").isdigit()
                   for p in per + urls), f"IP leaked into targets: {per} / {urls}"
    # The first 3 in-scope exact-match hosts are the natural per-target
    # default (the 5 "Out Of Scope"-tier hosts correctly precede them in the
    # payload but sit in ts.out_of_scope, not ts.in_scope).
    assert per == ["autodiscover.uzleuven.be", "ecrf.uzleuven.be",
                   "extranet-asa.uzleuven.be"]
    # `random.uzleuven.be/random/` contributes its HOST (the gate scopes the
    # path); `w1.uzleuven.be` must not appear twice.
    assert "random.uzleuven.be" in urls
    assert per.count("w1.uzleuven.be") <= 1 and urls.count("w1.uzleuven.be") <= 1
    # Wildcards stay unexpanded.
    assert "*.kwsdose.be" in wild and "*.uzleuven.*" in wild
