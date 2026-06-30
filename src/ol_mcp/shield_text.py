"""shield_md_text and unshield_md_text MCP tools for Omni-Localizer.

Protect code blocks, links, math, HTML, and images in markdown before
sending to any LLM. Restore them after the LLM responds.

This is a generic, text-only protect/unprotect API — not coupled to
the OL translation pipeline. Agents can use it before custom LLM calls.
"""
from __future__ import annotations

import json

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.tools import (
    _register_tool,
    _success_response,
    ShieldMdInput,
    UnshieldMdInput,
    mcp_error_boundary,
)


@_register_tool(
    "shield_md_text",
    ShieldMdInput,
    "Replace code/links/math/HTML/images in markdown with [OL:TYPE:NNNN] placeholders. "
    "Use before any LLM call to protect content from translation. "
    "Returns shielded_text and a shield_map for restoration.",
)
@mcp_error_boundary
async def shield_md_text(params: ShieldMdInput) -> str:
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    from ol_md.shield import shield_markdown

    shielded, shield_map = shield_markdown(params.content)
    return json.dumps(
        _success_response(
            {
                "shielded_text": shielded,
                "shield_map": shield_map,
                "marker_count": len(shield_map),
            }
        ),
        ensure_ascii=False,
    )


@_register_tool(
    "unshield_md_text",
    UnshieldMdInput,
    "Restore [OL:TYPE:NNNN] placeholders in markdown text using the shield_map "
    "from a prior shield_md_text call.",
)
@mcp_error_boundary
async def unshield_md_text(params: UnshieldMdInput) -> str:
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    from ol_md.shield import unshield_markdown

    restored = unshield_markdown(params.content, params.shield_map)
    return json.dumps(
        _success_response({"restored_text": restored}),
        ensure_ascii=False,
    )
