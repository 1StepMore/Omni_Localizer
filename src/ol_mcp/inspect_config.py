"""inspect_config MCP tool for Omni-Localizer.

Introspect OL configuration: which models are available, what paths are
configured, what LQA settings are in effect.

SECURITY: All API keys, base_urls (when containing hardcoded tokens), and
shared secrets are REDACTED before returning. This tool MUST NOT leak
secrets. The server-side load_config() also runs _check_for_hardcoded_secrets.
"""
from __future__ import annotations

import json
import os

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.security import get_default_validator
from ol_mcp.tools import (
    _error_response,
    _register_tool,
    _success_response,
    InspectConfigInput,
    mcp_error_boundary,
)


def _redact_secret(value: str | None) -> str:
    """Redact a secret value. Returns '***REDACTED***' for any non-empty value."""
    return "***REDACTED***" if value else ""


def _looks_safe_base_url(url: str | None) -> bool:
    """A base_url is safe to expose only if it's a pure ${ENV_VAR} template.

    If the URL contains hardcoded tokens (substrings like 'sk-', 'Bearer', etc.),
    we redact it.
    """
    if not url:
        return True
    if "${" in url:
        return True
    unsafe_substrings = ("sk-", "Bearer ", "token=", "key=", "secret=")
    return not any(s in url for s in unsafe_substrings)


@_register_tool(
    "inspect_config",
    InspectConfigInput,
    "Inspect OL configuration: models, paths, LQA settings. "
    "All API keys and base_urls with hardcoded tokens are REDACTED. "
    "Use to discover what's configured without reading the file directly.",
)
@mcp_error_boundary
async def inspect_config(params: InspectConfigInput) -> str:
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    cfg_path = params.config_path or os.environ.get(
        "OL_CONFIG_PATH", "config/default.yaml"
    )

    vresult = get_default_validator().validate_path(cfg_path)
    if not vresult.success:
        return json.dumps(
            _error_response(
                "OL_INVALID_INPUT", f"OL_PATH_NOT_ALLOWED: {vresult.error}"
            ),
            ensure_ascii=False,
        )

    try:
        from ol_config.loader import load_config
    except ImportError as e:
        return json.dumps(
            _error_response(
                "OL_DEPS_MISSING",
                f"ol_config not importable ({e})",
            ),
            ensure_ascii=False,
        )

    try:
        config, glossary = load_config(cfg_path)
    except Exception as e:
        return json.dumps(
            _error_response("OL_CONFIG_LOAD_FAILED", str(e)),
            ensure_ascii=False,
        )

    models_by_role: dict[str, list[dict]] = {}
    pool = config.llm_pool
    for role_name in ("translation", "judging", "restoration"):
        role_models = getattr(pool, role_name, [])
        models_by_role[role_name] = [
            {
                "provider": m.provider,
                "model": m.model,
                "priority": m.priority,
                "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                "timeout": m.timeout,
                "requests_per_minute": getattr(m, "requests_per_minute", None),
                "api_key": _redact_secret(getattr(m, "api_key", None)),
                "base_url": (
                    m.base_url
                    if _looks_safe_base_url(getattr(m, "base_url", None))
                    else _redact_secret(m.base_url)
                ),
            }
            for m in role_models
        ]

    content = {
        "config_path": str(cfg_path),
        "project_id": config.project_id,
        "default_source_lang": config.source_lang,
        "default_target_lang": config.target_lang,
        "glossary_path": config.glossary_path,
        "lqa_enabled": config.enable_lqa,
        "lqa_threshold": config.lqa_threshold,
        "lqa_max_retries": config.lqa_max_retries,
        "max_input_size_mb": config.max_input_size_mb,
        "models_by_role": models_by_role,
        "glossary_term_count": len(glossary) if glossary else 0,
    }
    return json.dumps(_success_response(content), ensure_ascii=False)
