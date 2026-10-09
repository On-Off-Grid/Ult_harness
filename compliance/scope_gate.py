# compliance/scope_gate.py
"""
ScopeGate: core ALLOW/DENY policy engine for outbound requests.

Supports:
- ScopeMatchType.EXACT: exact hostname/URL match
- ScopeMatchType.WILDCARD: fnmatch-style wildcard (e.g. *.example.com)
- ScopeMatchType.CIDR: IP/CIDR ranges (e.g. 10.0.0.0/8)
- ScopeMatchType.REGEX: regular-expression hostname/URL matches

Also enforces:
- DNS rebinding protection (localhost, metadata IPs and hosts)
- OSINT domain allowlist (Twitter, GitHub, Reddit, Google APIs, etc.)
- Third-party exclusion (Stripe, Okta, Auth0, Sentry)
- WebSocket scheme support (ws://, wss:// treated like http/https)
"""

from __future__ import annotations

import sys
from pathlib import Path

import ipaddress
import fnmatch
import re
from dataclasses import dataclass
from typing import List, Set
from urllib.parse import urlparse

from core.types import TargetScope, ScopeRule, ScopeMatchType


# Hard-coded DNS rebinding / internal targets to always block
_DNS_REBIND_HOSTS: Set[str] = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",        # AWS/GCP metadata
    "::1",
    "metadata.google.internal",
}

_DNS_REBIND_IPS: List[ipaddress._BaseNetwork] = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
]

# OSINT domains that are ALWAYS allowed (primary gate).[cite:1]
_OSINT_ALLOWLIST: Set[str] = {
    "api.twitter.com",
    "oauth.reddit.com",
    "api.github.com",
    "www.googleapis.com",
}

# Third-party services that must always be blocked.[cite:1][cite:2]
_THIRD_PARTY_BLOCKLIST: Set[str] = {
    "stripe.com",
    "api.stripe.com",
    "okta.com",
    "auth0.com",
    "sentry.io",
}


@dataclass
class ScopeGate:
    """
    ScopeGate evaluates whether a given URL is allowed to leave the harness.

    Ordering:
    1. DNS rebinding / internal protection (hard block)
    2. Third-party exclusion (hard block)
    3. OSINT allowlist (hard allow)
    4. Out-of-scope rules (explicit deny)
    5. In-scope rules (explicit allow)
    6. Default deny
    """

    target_scope: TargetScope

    def is_in_scope(self, url: str) -> bool:
        """
        Returns True if the URL should be allowed, False if it should be blocked.
        """
        normalized = self._normalize_scheme(url)
        parsed = urlparse(normalized)
        host = parsed.hostname or ""
        if not host:
            return False

        # 1) DNS rebinding / internal protection
        if self._is_dns_rebinding_target(host):
            return False

        # 2) Third-party exclusion
        if self._is_third_party(host):
            return False

        # 3) OSINT allowlist (defense-in-depth primary gate).[cite:1]
        if self._is_osint_domain(host):
            return True

        # 4) Explicit out-of-scope rules take precedence
        if self._matches_rules(parsed, self.target_scope.out_of_scope):
            return False

        # 5) Explicit in-scope rules
        if self._matches_rules(parsed, self.target_scope.in_scope):
            return True

        # 6) Default deny if nothing matches
        return False

    @staticmethod
    def _normalize_scheme(url: str) -> str:
        """
        Treat ws:// and wss:// as http:// and https:// for scope checks.[cite:2]
        """
        if url.startswith("ws://"):
            return "http://" + url[len("ws://") :]
        if url.startswith("wss://"):
            return "https://" + url[len("wss://") :]
        return url

    @staticmethod
    def _is_dns_rebinding_target(host: str) -> bool:
        """
        Returns True if host is localhost/metadata or in reserved IP ranges.
        """
        host_lower = host.lower()
        if host_lower in _DNS_REBIND_HOSTS:
            return True

        try:
            ip = ipaddress.ip_address(host_lower)
        except ValueError:
            return False

        for net in _DNS_REBIND_IPS:
            if ip in net:
                return True
        return False

    @staticmethod
    def _is_osint_domain(host: str) -> bool:
        return host.lower() in _OSINT_ALLOWLIST

    @staticmethod
    def _is_third_party(host: str) -> bool:
        host_lower = host.lower()
        if host_lower in _THIRD_PARTY_BLOCKLIST:
            return True
        # Handle subdomains like *.sentry.io
        if host_lower.endswith(".sentry.io"):
            return True
        return False

    @staticmethod
    def _matches_rules(parsed, rules: List[ScopeRule]) -> bool:
        url = parsed.geturl()
        host = parsed.hostname or ""
        for rule in rules:
            if ScopeGate._matches_rule(rule, host, url):
                return True
        return False

    @staticmethod
    def _matches_rule(rule: ScopeRule, host: str, url: str) -> bool:
        pattern = rule.pattern
        match_type = rule.match_type

        if match_type == ScopeMatchType.EXACT:
            # Compare against hostname and full URL
            return host == pattern or url == pattern

        if match_type == ScopeMatchType.WILDCARD:
            # fnmatch-style host wildcard
            return fnmatch.fnmatch(host, pattern)

        if match_type == ScopeMatchType.CIDR:
            try:
                network = ipaddress.ip_network(pattern, strict=False)
                ip = ipaddress.ip_address(host)
                return ip in network
            except ValueError:
                return False

        if match_type == ScopeMatchType.REGEX:
            return bool(re.search(pattern, host))

        return False
