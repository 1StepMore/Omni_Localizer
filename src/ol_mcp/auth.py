"""MCP shared-secret auth (round 16 Phase A4).

If ``MCP_SHARED_SECRET`` env var is set, every tool call must
include a ``shared_secret`` field matching that value. If the
env var is not set (dev mode), auth is disabled for backward
compatibility.

Transport note: FastMCP 1.27.2 has no built-in auth or
middleware. For SSE/HTTP transport, the secret rides in the
tool input (every input model has a ``shared_secret`` field).
For stdio transport, the secret is still checked but the
attacker model is local-only (the OS process boundary is
the trust boundary). See .omo/plans/2026-06-18-production-
readiness-plan.md Phase A4 for rationale.
"""

from __future__ import annotations

import os


def check_auth(provided_secret: str | None) -> tuple[bool, str | None]:
    """Check the shared secret against the configured value.

    Returns:
        (True, None) if auth passes or is disabled.
        (False, "AUTH_FAILED") if a secret is configured and the
        provided value does not match.
    """
    expected = os.environ.get("MCP_SHARED_SECRET")
    if not expected:
        # Auth disabled (dev mode / stdio / no env var set).
        return (True, None)
    if provided_secret == expected:
        return (True, None)
    return (False, "AUTH_FAILED")


def auth_failure_response() -> dict:
    """Standard error response for AUTH_FAILED."""
    return {
        "success": False,
        "error_code": "AUTH_FAILED",
        "message": "Authentication failed: shared_secret is missing or incorrect.",
    }
