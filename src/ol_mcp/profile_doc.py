"""profile_doc MCP tool for Omni-Localizer.

LLM-based document profiler. Wraps ``ol_style.doc_profiler.profile_document``.
"""
from __future__ import annotations

import json
import logging

_logger = logging.getLogger(__name__)

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.tools import (
    ProfileDocInput,
    _error_response,
    _register_tool,
    _success_response,
    mcp_error_boundary,
)


@_register_tool(
    "profile_doc",
    ProfileDocInput,
    "Profile a document's writing style using an LLM. "
    "Returns a StyleGuide (tone, register, target_audience, key_conventions, "
    "vocabulary, avoid, summary). Uses an in-process cache for repeated calls.",
)
@mcp_error_boundary
async def profile_doc(params: ProfileDocInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    try:
        from ol_style.doc_profiler import profile_document
        from ol_style.cache import ProfileCache
    except ImportError as e:
        return json.dumps(
            _error_response(
                "OL_DEPS_MISSING",
                f"ol_style modules not importable ({e})",
            ),
            ensure_ascii=False,
        )

    cache: ProfileCache | None = None
    if params.use_cache:
        cache = ProfileCache()  # in-memory only for MCP

    try:
        guide = await profile_document(
            content=params.content,
            source_lang=params.source_lang,
            config_path=params.config_path,
            cache=cache,
        )
    except Exception as e:
        _logger.exception("profile_doc failed: %s", e)
        return json.dumps(
            _error_response("OL_PROFILE_FAILED", str(e)),
            ensure_ascii=False,
        )

    profile_dict = guide.to_dict()
    # Add metadata fields for the MCP response
    profile_dict["_source_lang"] = params.source_lang
    profile_dict["_content_length"] = len(params.content)

    content = {"profile": profile_dict}
    return json.dumps(_success_response(content), ensure_ascii=False)
