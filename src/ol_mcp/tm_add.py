"""add_tm_entries MCP tool for Omni-Localizer.

Write entries to a TMX translation memory file. Agents use this to
build and maintain translation memory across sessions.
"""
from __future__ import annotations

import json

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.security import get_default_validator
from ol_mcp.tools import (
    _error_response,
    _register_tool,
    _success_response,
    TMAddInput,
    mcp_error_boundary,
)


@_register_tool(
    "add_tm_entries",
    TMAddInput,
    "Add translation entries to a TMX file. Creates the file if it doesn't exist. "
    "ML deps required for embedding-based features: pip install omni-localizer[ml].",
)
@mcp_error_boundary
async def add_tm_entries(params: TMAddInput) -> str:
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    vresult = get_default_validator().validate_path(params.tmx_path)
    if not vresult.success:
        return json.dumps(
            _error_response(
                "OL_INVALID_INPUT", f"OL_PATH_NOT_ALLOWED: {vresult.error}"
            ),
            ensure_ascii=False,
        )

    if not params.entries:
        return json.dumps(
            _success_response({"entries_added": 0, "tmx_path": params.tmx_path}),
            ensure_ascii=False,
        )

    try:
        from ol_tm.service import TMService
    except ImportError as e:
        return json.dumps(
            _error_response(
                "OL_ML_DEPS_MISSING",
                f"TM service deps not installed. Run: pip install omni-localizer[ml] ({e})",
            ),
            ensure_ascii=False,
        )

    try:
        svc = TMService(params.tmx_path)
        for entry in params.entries:
            svc.add(entry.source, entry.target, entry.source_lang, entry.target_lang)
        svc.flush()
        return json.dumps(
            _success_response(
                {"entries_added": len(params.entries), "tmx_path": params.tmx_path}
            ),
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            _error_response("OL_TM_ADD_FAILED", str(e)),
            ensure_ascii=False,
        )
