"""extract_terms MCP tool for Omni-Localizer.

Auto-build glossary from source texts using YAKE. Returns top-N terms
by importance score (lower YAKE score = more relevant).
"""
from __future__ import annotations

import json

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.tools import (
    _error_response,
    _register_tool,
    _success_response,
    ExtractTermsInput,
    mcp_error_boundary,
)


@_register_tool(
    "extract_terms",
    ExtractTermsInput,
    "Extract key terms from source texts using YAKE. ML deps required: pip install omni-localizer[ml].",
)
@mcp_error_boundary
async def extract_terms(params: ExtractTermsInput) -> str:
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    if not params.texts:
        return json.dumps(
            _success_response({"terms": {}, "term_count": 0}),
            ensure_ascii=False,
        )

    try:
        from ol_terminology.extractor import extract_terms as _extract_terms
    except ImportError as e:
        return json.dumps(
            _error_response(
                "OL_ML_DEPS_MISSING",
                f"YAKE not installed. Run: pip install omni-localizer[ml] ({e})",
            ),
            ensure_ascii=False,
        )

    try:
        all_terms = _extract_terms(params.texts)
        # YAKE scores: lower = more relevant. Sort ascending to get top terms first.
        sorted_terms = sorted(
            all_terms.items(), key=lambda kv: kv[1], reverse=False
        )[: params.top_n]
        content = {
            "terms": dict(sorted_terms),
            "term_count": len(sorted_terms),
        }
        return json.dumps(_success_response(content), ensure_ascii=False)
    except Exception as e:
        return json.dumps(
            _error_response("OL_EXTRACT_TERMS_FAILED", str(e)),
            ensure_ascii=False,
        )
