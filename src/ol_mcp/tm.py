"""search_tm MCP tool for Omni-Localizer."""

from __future__ import annotations

import json
import logging

_logger = logging.getLogger(__name__)

from ol_mcp.tools import (
    _error_response,
    _register_tool,
    _success_response,
    SearchTMInput,
    mcp_error_boundary,
)
from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.security import get_default_validator
from ol_tm.service import TMService


@_register_tool(
    "search_tm",
    SearchTMInput,
    "Search translation memory for similar past translations.",
)
@mcp_error_boundary
async def search_tm(params: SearchTMInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Search TMX file for similar past translations.

    Uses embedding-based similarity search with configurable threshold.

    Returns: success, matches list, count
    """

    warnings: list[str] = []

    vresult = get_default_validator().validate_path(params.tmx_path)
    if not vresult.success:
        return json.dumps(
            _error_response(
                "OL_INVALID_INPUT",
                f"OL_PATH_NOT_ALLOWED: {vresult.error}",
            ),
            ensure_ascii=False,
        )

    try:
        svc = TMService(params.tmx_path)
        matches = svc.search(params.source_text, threshold=params.threshold, src_lang=params.source_lang, tgt_lang=params.target_lang)
        content = {
            "matches": [
                {
                    "source": m.source,
                    "target": m.target,
                    "similarity": m.similarity,
                    "language_pair": m.language_pair,
                }
                for m in matches
            ],
            "count": len(matches),
        }
        return json.dumps(_success_response(content), ensure_ascii=False)

    except Exception as e:
        return json.dumps(
            _error_response("OL_TM_SEARCH_FAILED", str(e)),
            ensure_ascii=False,
        )
