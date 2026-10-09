# compliance/__init__.py
"""
Compliance package: Layer 0 platform scope enforcement and egress controls.
Phase 1 adds:
- scope_gate: core ALLOW/DENY policy engine
- egress_proxy: mitmproxy addon that enforces ScopeGate on live HTTP traffic
- header_injector: platform_profile.json → headers + rate-limit
- scope_importer: platform export parsers → TargetScope
- oob_engine: Interactsh OOB client wrapper
"""
