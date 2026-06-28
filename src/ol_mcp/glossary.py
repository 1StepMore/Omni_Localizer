"""load_glossary and get_relevant_terms MCP tools for Omni-Localizer."""

from __future__ import annotations

import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

from ol_mcp.tools import (
    _error_response,
    _register_tool,
    _success_response,
    LoadGlossaryInput,
    GetRelevantTermsInput,
    mcp_error_boundary,
)
from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.security import get_default_validator
from ol_terminology.glossary import get_relevant_terms as _get_relevant_terms, load_glossary_from_path


@_register_tool(
    "load_glossary",
    LoadGlossaryInput,
    "Load a JSON glossary file for use in translation.",
)
@mcp_error_boundary
async def load_glossary(params: LoadGlossaryInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Load a JSON glossary file.

    Returns: success, glossary dict, term_count, warnings
    """

    warnings: list[str] = []

    vresult = get_default_validator().validate_path(params.path)
    if not vresult.success:
        return json.dumps(
            _error_response(
                "OL_INVALID_INPUT",
                f"OL_PATH_NOT_ALLOWED: {vresult.error}",
            ),
            ensure_ascii=False,
        )

    try:
        glossary = load_glossary_from_path(
            params.path,
            config_dir=Path(params.config_dir) if params.config_dir else None,
        )
        content = {
            "glossary": glossary,
            "term_count": len(glossary),
            "warnings": warnings,
        }
        return json.dumps(_success_response(content), ensure_ascii=False)

    except Exception as e:
        return json.dumps(
            _error_response("OL_GLOSSARY_LOAD_FAILED", str(e)),
            ensure_ascii=False,
        )


@_register_tool(
    "get_relevant_terms",
    GetRelevantTermsInput,
    "Extract relevant glossary terms for a given text.",
)
@mcp_error_boundary
async def get_relevant_terms(params: GetRelevantTermsInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Select top-k terms from glossary relevant to the given text.

    Matching is based on exact/partial substring + confidence scoring.

    Returns: success, terms list, count
    """

    try:
        terms = _get_relevant_terms(params.text, params.glossary, top_k=params.top_k)
        content = {
            "terms": terms,
            "count": len(terms),
        }
        return json.dumps(_success_response(content), ensure_ascii=False)

    except Exception as e:
        return json.dumps(
            _error_response("OL_TERMS_FAILED", str(e)),
            ensure_ascii=False,
        )
