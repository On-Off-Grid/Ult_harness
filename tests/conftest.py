# tests/conftest.py
"""Shared fixtures for the S2 trust-audit smoke tests.

Design notes
------------
* mitmproxy 12 made ``http.Request`` / ``http.HTTPFlow`` constructors extremely
  strict (byte fields, mandatory conn objects). ``EgressProxy.request`` only
  touches ``flow.request.{host, pretty_url, method, headers}`` and sets
  ``flow.response``, so we drive it with a tiny duck-typed flow instead of
  fighting the real constructors. This keeps the S2.3 replay stable across
  mitmproxy versions.
* Every test that loads config/scope from the environment is isolated with a
  ``tmp_path`` workspace and a clean scope file, so tests never touch the real
  ``./workspace`` or the operator's env.
"""
from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import pytest


# ── Duck-typed mitmproxy flow ───────────────────────────────────────────
class _FakeHeaderMap:
    """dict-like header container supporting .get / .pop (what EgressProxy uses)."""

    def __init__(self, headers: dict[str, str]):
        self._d = dict(headers)

    def get(self, key: str, default=None):
        return self._d.get(key, default)

    def pop(self, key: str, default=None):
        return self._d.pop(key, default)

    def __getitem__(self, key):
        return self._d[key]


class _FakeRequest:
    def __init__(self, url: str, method: str = "GET", headers: dict[str, str] | None = None):
        self._u = urlparse(url)
        self.method = method
        self._headers = _FakeHeaderMap(headers or {})

    @property
    def pretty_url(self) -> str:
        return self._u.geturl()

    @property
    def host(self) -> str:
        return self._u.hostname or ""

    @property
    def headers(self):
        return self._headers


class _FakeResponse:
    def __init__(self, status: int):
        self.status = status


class FakeFlow:
    def __init__(self, url: str, method: str = "GET", headers: dict[str, str] | None = None):
        self.request = _FakeRequest(url, method, headers)
        self.response: _FakeResponse | None = None


@pytest.fixture
def make_flow():
    """Factory that returns a FakeFlow for a given URL (+ optional headers)."""
    def _make(url: str, method: str = "GET", headers: dict[str, str] | None = None) -> FakeFlow:
        return FakeFlow(url, method, headers)
    return _make


@pytest.fixture
def fake_response_make(monkeypatch):
    """Point ``egress_proxy.http.Response.make`` at a status-only fake.

    EgressProxy imports ``http`` from mitmproxy and calls
    ``http.Response.make(status, body, headers)``. We intercept it so the
    dry-run decision path doesn't build a real mitmproxy Response (which needs
    a full connection context)."""
    import compliance.egress_proxy as ep

    monkeypatch.setattr(
        ep.http.Response,
        "make",
        staticmethod(lambda status, body=None, headers=None: _FakeResponse(status)),
    )
    return _FakeResponse


@pytest.fixture
def scope_csv(tmp_path):
    """A HackerOne-style scope CSV exposing ``*.example.com`` (wildcard).

    This is the scope that produced the shipped fixture
    ``workspace/default-wing/logs/egress_proxy.jsonl``:
      - www.example.com / app.example.com -> ALLOW (match ``*.example.com``)
      - example.com                       -> DROP  (fnmatch misses the apex)
      - evil.com                          -> DROP  (not in scope)
    """
    path = tmp_path / "scope.csv"
    path.write_text(
        "asset_type,asset_identifier,eligible_for_bounty\n"
        "URL,*.example.com,true\n"
    )
    return path


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Isolated, deterministic harness environment.

    Sets a temp workspace, dry-run on, and clears any real API keys so a test
    can never accidentally call a live provider or read the operator's scope.
    Returns the workspace dir (as a string)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("HARNESS_DRY_RUN", "true")
    monkeypatch.setenv("HARNESS_WORKSPACE", str(ws))
    # Never let a real key leak into a test's router/config.
    for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
              "HARNESS_SCOPE_FILE", "HARNESS_SCOPE_FORMAT", "HARNESS_PROGRAM_HANDLE"):
        monkeypatch.delenv(k, raising=False)
    return str(ws)


@pytest.fixture
def run_async():
    """Run a coroutine on a fresh event loop (no pytest-asyncio dependency)."""
    def _run(coro):
        return asyncio.run(coro)
    return _run
