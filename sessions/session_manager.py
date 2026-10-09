# sessions/session_manager.py
"""Bootstraps and maintains multi-session authentication tokens for IDOR/BAC testing.

The session manager authenticates multiple user personas (User A, User B, Admin)
against the target application and provides their tokens to specialist agents.
A background refresh loop re-authenticates every 25 minutes to prevent expiry.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import aiohttp

from core.types import MultiSessionContext

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages authentication sessions for multi-user vulnerability testing.

    Usage:
        sm = SessionManager(auth_config={
            "user_a": {"login_url": "https://target.com/api/login", "payload": {"email": "a@test.com", "password": "..."}},
            "user_b": {"login_url": "https://target.com/api/login", "payload": {"email": "b@test.com", "password": "..."}},
            "admin":  {"login_url": "https://target.com/api/login", "payload": {"email": "admin@test.com", "password": "..."}},
        })
        ctx = await sm.bootstrap_sessions()
        # ctx.user_a_headers, ctx.user_b_headers, ctx.admin_headers, ctx.unauth_headers
    """

    def __init__(
        self,
        auth_config: Dict[str, Any],
        refresh_interval_minutes: int = 25,
        proxy_url: Optional[str] = None,
    ):
        self.auth_config = auth_config
        self.refresh_interval = refresh_interval_minutes * 60  # seconds
        self.proxy_url = proxy_url  # e.g. "http://127.0.0.1:8080" for egress proxy
        self.context: Optional[MultiSessionContext] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._session_metadata: Dict[str, Any] = {}

    async def bootstrap_sessions(self) -> MultiSessionContext:
        """Authenticate all configured user personas and build the session context.

        Returns a MultiSessionContext with Authorization headers for each persona.
        """
        user_a = await self._login("user_a", self.auth_config.get("user_a"))
        user_b = await self._login("user_b", self.auth_config.get("user_b"))
        admin = await self._login("admin", self.auth_config.get("admin"))

        self.context = MultiSessionContext(
            user_a_headers=self._build_auth_headers(user_a),
            user_b_headers=self._build_auth_headers(user_b),
            admin_headers=self._build_auth_headers(admin),
            unauth_headers={},  # intentionally empty — no auth
            session_metadata=self._session_metadata,
        )

        # Start the background refresh loop (if not already running)
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._token_refresh_loop())

        logger.info(
            "sessions_bootstrapped",
            extra={
                "user_a": bool(user_a.get("token")),
                "user_b": bool(user_b.get("token")),
                "admin": bool(admin.get("token")),
            },
        )

        return self.context

    async def _login(self, persona: str, creds: Optional[Dict]) -> Dict[str, str]:
        """Authenticate a single persona against the target's login endpoint.

        Returns {"token": "...", "token_type": "Bearer"} or empty values on failure/skip.
        """
        if not creds:
            logger.info(f"No credentials configured for {persona} — skipping")
            return {"token": "", "token_type": "Bearer"}

        login_url = creds.get("login_url", "")
        payload = creds.get("payload", {})

        if not login_url:
            logger.warning(f"No login_url for {persona} — skipping")
            return {"token": "", "token_type": "Bearer"}

        try:
            connector_kwargs = {}
            if self.proxy_url:
                # Note: aiohttp uses trust_env or explicit proxy
                connector_kwargs["trust_env"] = True

            async with aiohttp.ClientSession(**connector_kwargs) as session:
                async with session.post(
                    login_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                    proxy=self.proxy_url,
                ) as resp:
                    if resp.status >= 400:
                        logger.error(
                            f"Login failed for {persona}: HTTP {resp.status} from {login_url}"
                        )
                        return {"token": "", "token_type": "Bearer"}

                    data = await resp.json()

                    # Support common token field names
                    token = (
                        data.get("access_token")
                        or data.get("token")
                        or data.get("jwt")
                        or data.get("session_token")
                        or ""
                    )
                    token_type = data.get("token_type", "Bearer")

                    self._session_metadata[persona] = {
                        "login_url": login_url,
                        "status": resp.status,
                        "has_token": bool(token),
                    }

                    logger.info(f"Login successful for {persona} — token acquired")
                    return {"token": token, "token_type": token_type}

        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            logger.error(f"Login failed for {persona}: {exc}")
            return {"token": "", "token_type": "Bearer"}

    @staticmethod
    def _build_auth_headers(login_result: Dict[str, str]) -> Dict[str, str]:
        """Convert a login result into request headers."""
        token = login_result.get("token", "")
        if not token:
            return {}
        token_type = login_result.get("token_type", "Bearer")
        return {"Authorization": f"{token_type} {token}"}

    async def _token_refresh_loop(self) -> None:
        """Background loop: re-authenticate all sessions at the configured interval.

        Detects 401 responses from specialists and triggers immediate re-auth
        rather than waiting for the polling interval.
        """
        while True:
            await asyncio.sleep(self.refresh_interval)
            try:
                logger.info("Refreshing authentication sessions...")
                # Re-bootstrap without restarting the refresh loop
                user_a = await self._login("user_a", self.auth_config.get("user_a"))
                user_b = await self._login("user_b", self.auth_config.get("user_b"))
                admin = await self._login("admin", self.auth_config.get("admin"))

                if self.context:
                    self.context.user_a_headers = self._build_auth_headers(user_a)
                    self.context.user_b_headers = self._build_auth_headers(user_b)
                    self.context.admin_headers = self._build_auth_headers(admin)
                    self.context.session_metadata = self._session_metadata

                logger.info("Session tokens refreshed successfully")
            except Exception as e:
                logger.error(f"Token refresh failed: {e}")

    async def force_refresh(self) -> MultiSessionContext:
        """Trigger an immediate session refresh (e.g., after a 401 from a specialist)."""
        logger.info("Forced session refresh triggered")
        return await self.bootstrap_sessions()

    async def shutdown(self) -> None:
        """Cancel the background refresh task on harness shutdown."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            logger.info("Session refresh loop stopped")
