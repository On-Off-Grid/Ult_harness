# agents/dual_session_tester.py
"""Matrix tester for IDOR and Broken Access Control (BAC).

Executes a 4-session request matrix (User A, User B, Admin, Unauth)
and compares response states to locate access control failures.
"""

import logging
from typing import Any, Dict, Tuple
import aiohttp

from core.types import MultiSessionContext

logger = logging.getLogger(__name__)


class DualSessionTester:
    """Executes requests across four distinct authentication sessions and analyzes access states.

    Matrix rules:
      - Owner (User A) request -> expected to succeed (HTTP 2xx).
      - Peer (User B) request -> expected to fail/deny (HTTP 401/403/404).
      - Admin request -> typically succeeds (or denied if strict segregation is implemented).
      - Unauthenticated (Unauth) request -> expected to fail/deny (HTTP 401/403).
    """

    def __init__(self, proxy_url: Optional[str] = None):
        self.proxy_url = proxy_url

    async def run_matrix(
        self,
        url: str,
        method: str,
        session_ctx: MultiSessionContext,
        json_data: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Perform request to target URL across all 4 auth contexts."""
        headers = headers or {}
        results = {}

        personas = [
            ("user_a", session_ctx.user_a_headers),
            ("user_b", session_ctx.user_b_headers),
            ("admin", session_ctx.admin_headers),
            ("unauth", session_ctx.unauth_headers),
        ]

        connector_kwargs = {}
        if self.proxy_url:
            connector_kwargs["trust_env"] = True

        async with aiohttp.ClientSession(**connector_kwargs) as session:
            for name, auth_headers in personas:
                # Merge custom and auth headers
                req_headers = {**headers, **auth_headers}
                try:
                    async with session.request(
                        method=method,
                        url=url,
                        json=json_data,
                        headers=req_headers,
                        proxy=self.proxy_url,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        text = await resp.text()
                        results[name] = {
                            "status": resp.status,
                            "length": len(text),
                            "is_success": 200 <= resp.status < 300,
                        }
                except Exception as e:
                    logger.warning(f"Error during matrix test for {name}: {e}")
                    results[name] = {
                        "status": 0,
                        "length": 0,
                        "is_success": False,
                        "error": str(e),
                    }
        return results

    @staticmethod
    def analyze_results(results: Dict[str, Any]) -> Tuple[bool, bool, str]:
        """Evaluate response status codes and body states.

        Returns: (is_idor, is_bac, description)
        """
        # If User A (owner) can't access it, the target url is invalid or auth fails
        if not results.get("user_a", {}).get("is_success"):
            return (
                False,
                False,
                "Owner session (User A) request failed. Matrix comparison inconclusive.",
            )

        is_idor = False
        is_bac = False
        description = []

        # Check User B (Peer) access on User A's resource
        b_res = results.get("user_b", {})
        if b_res.get("is_success"):
            is_idor = True
            description.append(
                f"IDOR detected: User B (peer) accessed resource successfully (HTTP {b_res['status']})"
            )

        # Check Unauth access on User A's resource
        unauth_res = results.get("unauth", {})
        if unauth_res.get("is_success"):
            is_bac = True
            description.append(
                f"BAC detected: Unauthenticated request accessed resource successfully (HTTP {unauth_res['status']})"
            )

        return is_idor, is_bac, " | ".join(description)
