"""get_capabilities tool for Omni-Localizer.

Returns module-level static information about what the OL MCP server
can do. This is the "self-description" feature requested by agents.
"""
from __future__ import annotations

import json

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response


# Documented language pairs (en↔zh, en↔ja + reverse)
_LANGUAGE_PAIRS = ["en-zh", "zh-en", "en-ja", "ja-en", "en-ko", "ko-en"]

# LLM roles
_ROLES = ["translation", "judging", "restoration"]


def get_capabilities() -> str:
    """Return OL capabilities for MCP clients.

    Returns a JSON string with:
        module (str): "ol"
        version (str | None): OL version (best-effort)
        roles (list[str]): 3 LLM roles
        language_pairs (list[str]): documented language pair directions
        tools (list[str]): available MCP tool names, derived from the live
            registry at call time (never a hardcoded list)
    """
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(None)  # get_capabilities is auth-free for discoverability
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    version: str | None = None
    try:
        from ol import __version__ as _v  # type: ignore
        version = _v
    except Exception:  # expected
        pass

    # Derive the tool list from the live registry at call time. The import is
    # lazy to avoid a circular import: tools.py imports this module at load
    # time and registers TOOL_REGISTRY["get_capabilities"] afterward.
    from ol_mcp.tools import TOOL_REGISTRY

    tools = sorted(TOOL_REGISTRY.keys())

    return json.dumps(
        {
            "success": True,
            "content": {
                "module": "ol",
                "version": version,
                "roles": _ROLES,
                "language_pairs": _LANGUAGE_PAIRS,
                "tools": tools,
            },
        },
        ensure_ascii=False,
    )
