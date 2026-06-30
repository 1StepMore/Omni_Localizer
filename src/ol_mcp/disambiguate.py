"""disambiguate MCP tool for Omni-Localizer.

Resolve polysemous terms (words with multiple translations) using
context-aware confidence-based selection. The MCP tool uses the
fallback path only — for LLM-based disambiguation, use the Python API.
"""
from __future__ import annotations

import json

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.tools import (
    _error_response,
    _register_tool,
    _success_response,
    DisambiguateInput,
    mcp_error_boundary,
)


@_register_tool(
    "disambiguate",
    DisambiguateInput,
    "Resolve polysemous terms in text using context-aware confidence-based "
    "selection from a glossary. Confidence-based only (no LLM); for LLM-based "
    "disambiguation, call the Python API directly with a model_pool.",
)
@mcp_error_boundary
async def disambiguate(params: DisambiguateInput) -> str:
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    if not params.text or not params.glossary:
        return json.dumps(
            _success_response({"resolved_terms": {}, "resolved_count": 0}),
            ensure_ascii=False,
        )

    try:
        from ol_terminology.disambiguator import disambiguate as _disambiguate
    except ImportError as e:
        return json.dumps(
            _error_response(
                "OL_DEPS_MISSING",
                f"ol_terminology.disambiguator not importable ({e})",
            ),
            ensure_ascii=False,
        )

    try:
        resolved = _disambiguate(params.text, params.glossary)
        return json.dumps(
            _success_response(
                {
                    "resolved_terms": resolved,
                    "resolved_count": len(resolved),
                }
            ),
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            _error_response("OL_DISAMBIGUATE_FAILED", str(e)),
            ensure_ascii=False,
        )
