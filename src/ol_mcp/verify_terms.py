"""verify_terms MCP tool for Omni-Localizer.

Post-translation glossary term verification (no LLM, no network).
Wraps ``ol_terminology.verifier.verify_translation``.
"""
from __future__ import annotations

import json
import logging
from typing import Any

_logger = logging.getLogger(__name__)

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.tools import (
    VerifyTermsInput,
    _error_response,
    _register_tool,
    _success_response,
    mcp_error_boundary,
)


@_register_tool(
    "verify_terms",
    VerifyTermsInput,
    "Verify glossary term usage in translated content. "
    "With glossary: checks each term's verified translation appears in target. "
    "Without glossary: detects inconsistent translations across sentences. "
    "Returns a JSON report with verified/mismatches/absent/inconsistencies/low_confidence lists.",
)
@mcp_error_boundary
async def verify_terms(params: VerifyTermsInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    try:
        from ol_terminology.verifier import verify_translation
    except ImportError as e:
        return json.dumps(
            _error_response(
                "OL_DEPS_MISSING",
                f"ol_terminology.verifier not importable ({e})",
            ),
            ensure_ascii=False,
        )

    # Resolve glossary: inline takes precedence over path
    glossary: dict[str, dict[str, Any]] | None = params.glossary
    if glossary is None and params.glossary_path:
        try:
            from ol_terminology.glossary import load_glossary_from_path
            glossary = load_glossary_from_path(params.glossary_path)
        except (FileNotFoundError, ValueError) as e:
            return json.dumps(
                _error_response(
                    "OL_GLOSSARY_LOAD_FAILED",
                    f"Failed to load glossary from {params.glossary_path}: {e}",
                ),
                ensure_ascii=False,
            )

    try:
        report = verify_translation(
            source_text=params.source,
            target_text=params.target,
            glossary=glossary,
            confidence_threshold=params.confidence_threshold,
        )
    except Exception as e:
        _logger.exception("verify_terms failed: %s", e)
        return json.dumps(
            _error_response("OL_VERIFY_FAILED", str(e)),
            ensure_ascii=False,
        )

    content = report.to_dict()
    return json.dumps(_success_response(content), ensure_ascii=False)
