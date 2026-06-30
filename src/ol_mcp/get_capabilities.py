"""get_capabilities tool for Omni-Localizer.

Returns module-level static information about what the OL MCP server
can do. This is the "self-description" feature requested by agents.
"""
from __future__ import annotations

import json

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response


# 14 MCP tools (this one included — 8 original + 6 from prior session)
_TOOLS = [
    "translate_md_text", "translate_xliff", "judge_text",
    "load_glossary", "get_relevant_terms", "search_tm",
    "batch_translate_texts", "get_translation_status",
    "extract_terms", "add_tm_entries", "shield_md_text",
    "unshield_md_text", "generate_report", "inspect_config",
    "disambiguate", "ping", "get_capabilities",
]

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
        tools (list[str]): 16 available MCP tool names
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
    except Exception:
        pass

    return json.dumps(
        {
            "success": True,
            "content": {
                "module": "ol",
                "version": version,
                "roles": _ROLES,
                "language_pairs": _LANGUAGE_PAIRS,
                "tools": _TOOLS,
            },
        },
        ensure_ascii=False,
    )
