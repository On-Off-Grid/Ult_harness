# compliance/scrub.py
"""S5.3 — pre-call secret scrubbing.

The hard data-lane rule: **no credentials / secrets / tokens in any LLM prompt.**
Before a prompt leaves the machine to a *cloud* provider (SAFE or RESTRICTED),
the router runs :func:`scrub`. If a secret pattern is detected the call is
refused and re-routed to LOCAL / LOCAL_HEAVY (self-hosted, never leaves the box).

Patterns are a conservative superset of the public secret scanners (truffleHog /
gitleaks / jsleak-style). They are intentionally *high-precision*: we only re-route
on strong signals to avoid blocking legitimate hunt traffic (a SQLi payload that
happens to contain the word "token" must not be scrubbed). The generic
"``api_key = <token>``" rule requires a long high-entropy-looking value, not just
the keyword.

This module is stdlib-only and import-safe (no network, no keys).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Pattern, Tuple

# (human_name, compiled_regex)
_SECRET_PATTERNS: List[Tuple[str, Pattern[str]]] = [
    # Provider / LLM API keys
    ("openai_key",        re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("openai_project_key",re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key",     re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("huggingface_key",   re.compile(r"\bhf_[A-Za-z0-9]{34,}\b")),
    ("groq_key",          re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("github_token",      re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github_fine_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("npm_token",         re.compile(r"//registry\.npmjs\.org/:[A-Za-z0-9_\-]{20,}")),
    # Cloud / infra
    ("aws_access_key",    re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key",    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack_token",       re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("telegram_bot",      re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_\-]{33}\b")),
    ("azure",             re.compile(r"\b[A-Za-z0-9_\-]{16,}\.AccessKey=[A-Za-z0-9+/=]{40,}")),
    # Payment / SaaS
    ("stripe_secret",     re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}\b")),
    ("twilio",            re.compile(r"\bSK[AC][0-9a-f]{32}\b")),
    ("sendgrid",          re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\b")),
    # Private key blocks
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # JWT (header.payload.signature, base64url)
    ("jwt",               re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    # Generic assignment of a long high-entropy-looking value to a secret-ish name.
    # High precision: requires 16+ mixed-case/digit chars OR an =/token/= style.
    ("generic_secret",    re.compile(
        r"""(?ix)
        \b(api[_-]?key|secret|access[_-]?token|auth[_-]?token|bearer|passwd|password|private[_-]?key)
        [\s"']{0,3}(=|:|is|was)\s*["']?
        ([A-Za-z0-9+/=_\-]{16,})
        """),
    ),
]


@dataclass
class ScrubResult:
    found: bool
    matches: List[str] = field(default_factory=list)   # human names of matched patterns

    @property
    def clean(self) -> bool:
        return not self.found


def scrub(text: str) -> ScrubResult:
    """Detect likely secrets in ``text``.

    Returns a :class:`ScrubResult` with ``found`` True and the matching pattern
    names. Never raises on odd input.
    """
    if not text:
        return ScrubResult(found=False)
    hits: List[str] = []
    for name, rx in _SECRET_PATTERNS:
        if rx.search(text):
            hits.append(name)
    return ScrubResult(found=bool(hits), matches=hits)


def scrub_to_local(prompt: str, is_local_target: bool) -> ScrubResult:
    """Decision helper for the router.

    The scrub hard-rule only forces a *re-route* when the prompt would go to a
    **cloud** provider. LOCAL / LOCAL_HEAVY targets are the safe sink for
    secret-bearing prompts (e.g. ``secret_detection``), so for a local target the
    result is reported but not a violation.
    """
    result = scrub(prompt)
    if result.found and not is_local_target:
        return result
    return ScrubResult(found=False)
