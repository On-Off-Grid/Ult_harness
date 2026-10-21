# compliance/oob_engine.py
"""
OOBEngine: Out-of-band interaction engine using Interactsh (S8.1).

Real Interactsh HTTP lifecycle:
  init()             -> POST   {api}/register     (collaborator + collision token)
  generate_payload() -> unique http://<rand>.<session>.<base>/ URL  (send side)
  poll_callbacks()   -> POST   {api}/polling      (DNS/HTTP/SMTP interactions)
  close()            -> DELETE {api}/deregister

Modes (``interactsh_mode`` in HarnessConfig):
- "public":     the public Interactsh service. The HTTP API and the callback
  wildcard both live on ``oast.pro`` (``interactsh.com`` is the web portal,
  not the API, so it is not used as the API base in public mode).
- "selfhosted": API base AND callback base domain both come from
  ``interactsh_url``.
- anything else (e.g. "off"): the engine is *disabled* — no network, payloads
  are still well-formed placeholders, ``poll_callbacks()`` returns [].

Injectability + fail-open (the S2/S4 invariants, applied to OOB):
- ``http`` is an injectable seam with the same shape as
  ``budget.providers.default_http`` — ``await http(method, url, headers,
  payload, timeout) -> (status, json_dict)`` — so the whole lifecycle is
  mock-testable with **no network**.
- A disabled, unregistered, or dead Interactsh NEVER breaks a hunt: register /
  poll / deregister failures log and degrade to placeholder behavior (empty
  callback list, still-valid payload URLs).

Receive side (S8.1): each ``generate_payload(context=...)`` registers the URL
plus its context (endpoint / category / correlation_id) with the session.
``match(callback)`` claims the registration a callback hit (at most once per
payload), so ``OpAdmiral.poll_oob()`` can attribute an interaction back to the
finding that fired it — confirming blind SSRF / RCE / XXE with no LLM in the
loop (the callback IS the proof).
"""

from __future__ import annotations

import json
import logging
import random
import re
import string
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from core.config import HarnessConfig

logger = logging.getLogger(__name__)

# Same http-seam shape as budget.providers.default_http.
HttpFn = Callable[..., Awaitable[Tuple[int, Dict[str, Any]]]]

# Public Interactsh: the HTTP API and the callback wildcard live on oast.pro.
PUBLIC_API_URL = "https://oast.pro"
PUBLIC_BASE_DOMAIN = "oast.pro"

# How often an UNREGISTERED public-mode session retries a fresh register. The
# public service keys anonymous sessions by the CLIENT IP (not the User-Agent),
# so a stale session left behind by a killed hunt keeps rejecting new registers
# with 400 "correlation-id provided already exists" until it expires
# server-side. Retrying on this cadence is the self-heal: it costs one small
# POST /register per interval, stays quiet on failure, and succeeds the moment
# the stale IP-keyed slot frees up. (Selfhosted mode has no such contention.)
REREGISTER_RETRY_SECONDS = 90.0


def _host_of(url: str) -> str:
    """Lowercase host (port stripped) from an http(s) URL; '' when unparseable."""
    m = re.match(r"https?://([^\s:/?#]+)", (url or "").strip())
    return m.group(1).lower() if m else ""


def _default_http(method: str, url: str, headers: Dict[str, str],
                  payload: Dict[str, Any], timeout: int = 15) -> "Awaitable[Tuple[int, Dict[str, Any]]]":
    """Real HTTP via aiohttp (imported lazily so the module is import-safe).

    Mirrors ``budget.providers.default_http``: GET/DELETE go out bodyless.
    """
    import aiohttp

    async def _call() -> Tuple[int, Dict[str, Any]]:
        req_body = None if method.upper() in ("GET", "DELETE") else payload
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, headers=headers, json=req_body,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except (json.JSONDecodeError, ValueError):
                    body = {}
                return resp.status, body

    return _call()


@dataclass
class OOBCallback:
    """A single OOB interaction (DNS/HTTP/SMTP) reported by Interactsh."""

    type: str            # "dns" | "http" | "smtp" | ...
    timestamp: str
    raw: Dict[str, Any]
    callback: str = ""   # the host/name that actually called back


class OOBEngine:
    """A hunt-wide Interactsh session: register -> embed payloads -> poll -> close.

    See the module docstring for the mode / fail-open / injectability contract.
    One session per hunt; every embedded payload is a unique sub-subdomain of
    the session's collision token, so any interaction on that exact host
    proves the target itself made the request.
    """

    def __init__(
        self,
        mode: Optional[str] = None,
        base_domain: Optional[str] = None,
        interactsh_url: Optional[str] = None,
        api_token: Optional[str] = None,
        http: Optional[HttpFn] = None,
        enabled: Optional[bool] = None,
    ):
        cfg = HarnessConfig.load_from_env()
        self.mode = (mode or cfg.interactsh_mode or "public").strip().lower()
        self.interactsh_url = (interactsh_url or cfg.interactsh_url or "").rstrip("/")
        self.api_token = api_token or None
        self.http: HttpFn = http or _default_http
        # Fail-open gate: only public/selfhosted modes ever talk to Interactsh.
        self.enabled = (
            (self.mode in ("public", "selfhosted")) if enabled is None else enabled
        )
        # Callback base domain: explicit arg > selfhosted URL host > oast.pro.
        self.base_domain = (
            base_domain
            or (_host_of(self.interactsh_url) if self.mode == "selfhosted" else "")
            or PUBLIC_BASE_DOMAIN
        )
        # Session identity on the public Interactsh service. Two things matter:
        #  * anonymous sessions are keyed by the CLIENT IP — a stale session
        #    left by a previously-killed hunt (whose token is unrecoverable)
        #    keeps rejecting new registers with 400 "correlation-id provided
        #    already exists" until it expires server-side; this is why the
        #    receive loop retries a register (``maintain()``) instead of
        #    giving up at boot;
        #  * the User-Agent is a per-instance marker (``ult-harness/3.0/<12
        #    hex>``) so concurrent hunts are distinguishable in the service's
        #    audit logs. It is NOT a reliable session key on its own — rotating
        #    it does not clear an IP-keyed stale session.
        self._ua = f"ult-harness/3.0/{uuid.uuid4().hex[:12]}"
        self.session_id: Optional[str] = None      # == collision token once registered
        self.collaborator: Optional[str] = None
        self.collision_token: Optional[str] = None
        self.callback_domain: Optional[str] = None  # "<token>.<base_domain>"
        self._closed = False
        self._last_reregister: float = 0.0         # monotonic time of last register attempt
        self._embedded: List[Dict[str, Any]] = []  # {"url", "host", "context"}
        self._claimed: set = set()                  # payload hosts already attributed
        self._all: List[OOBCallback] = []           # every interaction ever seen
        self._seen: set = set()                     # dedup keys for poll results

    # ── lifecycle ──────────────────────────────────────────────────────────

    @property
    def initialized(self) -> bool:
        """A live Interactsh session is registered (callbacks can be polled)."""
        return bool(self.collaborator and self.collision_token)

    def _api_base(self) -> str:
        if self.mode == "selfhosted" and self.interactsh_url:
            return self.interactsh_url
        return PUBLIC_API_URL

    def _new_ua(self) -> str:
        """A fresh per-instance User-Agent (see ``_ua`` note in ``__init__``)."""
        self._ua = f"ult-harness/3.0/{uuid.uuid4().hex[:12]}"
        return self._ua

    def _headers(self) -> Dict[str, str]:
        headers = {"User-Agent": self._ua, "Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def init(self) -> None:
        """POST /register -> (collaborator, collision token).

        Fail-open: when disabled, or on any error / missing fields, the engine
        stays available-but-unregistered — payloads keep working as
        placeholders and ``poll_callbacks()`` returns [].

        Stale-session recovery: the public service rejects a register while a
        session for this CLIENT is already alive ("correlation-id provided
        already exists", HTTP 400). On that exact error we rotate the UA once
        and retry immediately; if the slot is still held (a stale session keyed
        by the client IP from a previously-killed hunt), we stay unregistered
        and ``maintain()`` (the hunt's poll loop) retries on a throttle until
        the stale session lapses server-side — a fresh register then succeeds.
        """
        if not self.enabled or self.initialized or self._closed:
            return
        self._last_reregister = time.monotonic()
        status = await self._register_once()
        if status == "stale":
            # One immediate retry under the rotated UA (covers a *concurrent*
            # live hunt); a still-held IP-keyed slot is left to maintain().
            await self._register_once()

    async def _register_once(self) -> str:
        """A single POST /register attempt. Returns:

        ``"registered"`` a session is now live;
        ``"stale"``      the service says a session already exists (client IP
                         still holds one) — the UA is rotated so concurrent
                         hunts stay distinguishable, and the caller/maintain()
                         retries;
        ``"error"``      anything else (network, 5xx, 403, …) — fail-open.

        Never raises, and stays quiet (``logger.debug``) on failure: an
        unregistered OOB session is an expected transient state, not an error
        worth logging every interval.
        """
        self._last_reregister = time.monotonic()  # throttle on the attempt time
        try:
            status, body = await self.http(
                "POST", f"{self._api_base()}/register", self._headers(), {}, 15,
            )
        except Exception as exc:
            logger.debug(f"oob: register attempt failed ({exc}) — unregistered")
            return "error"
        body = body if isinstance(body, dict) else {}
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        collab = body.get("collaborator") or data.get("collaborator")
        token = body.get("collaborator_token") or data.get("collaborator_token")
        if status == 200 and collab and token:
            self.collaborator = str(collab)
            self.collision_token = str(token)
            self.session_id = self.collision_token
            self.callback_domain = f"{self.collision_token}.{self.base_domain}"
            logger.info(f"oob: registered session on {self.callback_domain}")
            return "registered"
        blob = json.dumps(body).lower()
        if status == 400 and "already exists" in blob:
            self._new_ua()
            logger.debug("oob: register 400 (session already exists) — UA "
                         "rotated; will retry via maintain()")
            return "stale"
        logger.debug(f"oob: register HTTP {status} (got {body!r}) — unregistered")
        return "error"

    async def maintain(self) -> None:
        """Receive-loop keep-alive: while we have NO live session, retry a
        register on a throttle (default :data:`REREGISTER_RETRY_SECONDS`).

        This is the self-heal for the public service's IP-keyed stale session:
        boot's ``init()`` may have been blocked by a session a previously-killed
        hunt left behind, and that slot only frees up once the server's TTL
        lapses. Retrying every ~90 s (quiet, one small POST) means a hunt that
        starts with OOB blocked self-registers the moment the slot frees — no
        operator action. Does nothing when already registered / disabled /
        closed, and never raises (``_register_once`` is fail-open)."""
        if not self.enabled or self._closed or self.initialized:
            return
        if time.monotonic() - self._last_reregister < REREGISTER_RETRY_SECONDS:
            return
        await self._register_once()

    async def close(self) -> None:
        """DELETE /deregister. Fail-open + idempotent."""
        if self._closed:
            return
        self._closed = True
        if not self.enabled or not self.initialized:
            return
        try:
            await self.http(
                "DELETE", f"{self._api_base()}/deregister",
                {**self._headers(), "Oob-Platform": "cli"}, {}, 15,
            )
        except Exception as exc:
            logger.warning(f"oob: deregister failed ({exc}) — ignored")

    # ── send side ──────────────────────────────────────────────────────────

    def generate_payload(self, context: Optional[Dict[str, Any]] = None) -> str:
        """A unique callback URL for embedding in a payload (the send side).

        With a live session: ``http://<rand>.<collision_token>.<base>/`` — any
        interaction on that exact host proves the target made the request.
        Without one (disabled / register failed): the same shape on the
        configured base domain — well-formed and unique, it just never
        confirms.

        ``context`` (endpoint / category / correlation_id) is registered with
        the session so the receive side can attribute a callback back to this
        payload (and the finding that fired it).
        """
        if not self.session_id:
            self.session_id = self._random_id()
        token = self._random_id()
        host = f"{token}.{self.session_id}.{self.base_domain}"
        url = f"http://{host}/"
        self._embedded.append({"url": url, "host": host, "context": context or {}})
        return url

    @property
    def payloads(self) -> List[str]:
        """Payload URLs embedded in this session (status / debugging)."""
        return [r["url"] for r in self._embedded]

    # ── receive side ───────────────────────────────────────────────────────

    async def poll_callbacks(self) -> List[OOBCallback]:
        """POST /polling -> interactions new since the last poll (deduped).

        Fail-open: disabled / unregistered / closed / network error -> [].
        """
        if self._closed or not self.enabled or not self.initialized:
            return []
        try:
            status, body = await self.http(
                "POST", f"{self._api_base()}/polling",
                {**self._headers(), "Oob-Platform": "cli"}, {}, 15,
            )
        except Exception as exc:
            logger.warning(f"oob: poll failed ({exc}) — returning []")
            return []
        if status != 200:
            logger.warning(f"oob: poll HTTP {status} — returning []")
            return []
        new = self._parse_interactions(body if isinstance(body, dict) else {})
        self._all.extend(new)
        return new

    def match(self, cb: OOBCallback) -> Optional[Dict[str, Any]]:
        """Claim the registration (payload + context) that this callback hit.

        A registration is claimed at most once — each embedded payload
        confirms at most one finding. Returns the registration dict
        (``{"url", "host", "context"}``) or None.
        """
        hay = self._haystack(cb)
        if not hay:
            return None
        for reg in self._embedded:
            host = reg["host"]
            if host in self._claimed or host not in hay:
                continue
            self._claimed.add(host)
            return reg
        return None

    def _parse_interactions(self, body: Dict[str, Any]) -> List[OOBCallback]:
        """Map a /polling body onto OOBCallback records (deduped).

        Current API: ``{"data": [{"type":..., "raw":{...}, "timestamp":...}]}``.
        The older shape (``data`` = {dns: [...], http: [...], smtp: [...]}) is
        tolerated and tagged with the key as the type.
        """
        data = body.get("data")
        records: List[Dict[str, Any]] = []
        if isinstance(data, list):
            records = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            for key in ("dns", "http", "smtp", "logs"):
                for r in data.get(key, []) or []:
                    if isinstance(r, dict):
                        r.setdefault("type", key)
                        records.append(r)
        out: List[OOBCallback] = []
        for rec in records:
            raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
            name = str(raw.get("Name") or raw.get("Hostname") or raw.get("Host") or "")
            path = str(raw.get("Path") or raw.get("URL") or "")
            cb_type = str(rec.get("type") or "unknown").lower()
            ts = str(rec.get("timestamp") or "")
            ident = f"{cb_type}:{name}:{path}"
            if ident in self._seen:
                continue
            self._seen.add(ident)
            out.append(OOBCallback(
                type=cb_type, timestamp=ts, raw=raw,
                callback=name or path,
            ))
        return out

    @staticmethod
    def _haystack(cb: OOBCallback) -> str:
        """Lowercase blob of every host-ish field on a callback — the
        registered payload host is matched by substring against it."""
        parts = [cb.callback]
        for key in ("Name", "Hostname", "Host", "URL", "Path"):
            v = cb.raw.get(key)
            if v:
                parts.append(str(v))
        return " ".join(p.lower() for p in parts if p)

    @staticmethod
    def _random_id(length: int = 10) -> str:
        return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))
