"""judge_text MCP tool for Omni-Localizer."""

from __future__ import annotations

import json
import logging

_logger = logging.getLogger(__name__)

from ol_mcp.tools import (
    _error_response,
    _get_config_path,
    _register_tool,
    _success_response,
    JudgeInput,
    mcp_error_boundary,
)
from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_pool.router import ModelPool


@_register_tool(
    "judge_text",
    JudgeInput,
    "Evaluate translation quality using LLM judge.",
)
@mcp_error_boundary
async def judge_text(params: JudgeInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Evaluate translation quality with rubric scores.

    Returns: success, score (0-100), reason, judge_scores breakdown, warnings
    """

    if params.source_lang == params.target_lang:
        return json.dumps(
            _error_response(
                "OL_INVALID_INPUT",
                "Source and target languages must be different.",
            ),
            ensure_ascii=False,
        )

    warnings: list[str] = []

    try:
        config_path = _get_config_path(None)
        pool = ModelPool.get_instance(config_path)
        result = await pool.judge(
            params.source,
            params.target,
            params.source_lang,
            params.target_lang,
            params.glossary,
        )

        content = {
            "score": result.get("score", 50),
            "reason": result.get("reason", ""),
            "judge_scores": {
                "adequacy": result.get("adequacy", 50),
                "fluency": result.get("fluency", 50),
                "terminology_consistency": result.get("terminology_consistency", 50),
                "format_preservation": result.get("format_preservation", 50),
            },
            "warnings": warnings,
        }
        return json.dumps(_success_response(content), ensure_ascii=False)

    except Exception as e:
        return json.dumps(
            _error_response("OL_JUDGE_FAILED", str(e)),
            ensure_ascii=False,
        )
