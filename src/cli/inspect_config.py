"""ol inspect-config — Print OL configuration (secrets redacted).

Companion CLI to the OL MCP inspect_config tool. By default, all
API keys and unsafe base URLs are redacted in the output. Pass
``--raw`` (with caution) to see the unredacted values.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from cli._shared import ExitCode


def inspect_config(
    config_path: Optional[str] = typer.Option(
        None, "--config", "-c",
        help="Path to YAML config file (defaults to OL_CONFIG_PATH or config/default.yaml)"
    ),
    raw: bool = typer.Option(
        False, "--raw", help="Show unredacted values (CAUTION: prints API keys)"
    ),
) -> None:
    """Inspect OL configuration: models, paths, LQA settings."""
    from ol_config.loader import load_config
    from ol_mcp.inspect_config import (
        _looks_safe_base_url,
        _redact_secret,
    )

    cfg_path = config_path or Path("config/default.yaml")
    try:
        config, glossary = load_config(str(cfg_path))
    except Exception as e:
        typer.echo(f"Error: failed to load config: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    pool = config.llm_pool
    models_by_role = {}
    for role_name in ("translation", "judging", "restoration"):
        role_models = getattr(pool, role_name, [])
        models_by_role[role_name] = []
        for m in role_models:
            api_key = getattr(m, "api_key", None)
            base_url = getattr(m, "base_url", None)
            if not raw:
                api_key = _redact_secret(api_key)
                if not _looks_safe_base_url(base_url):
                    base_url = _redact_secret(base_url)
            models_by_role[role_name].append({
                "provider": m.provider,
                "model": m.model,
                "priority": m.priority,
                "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                "timeout": m.timeout,
                "requests_per_minute": getattr(m, "requests_per_minute", None),
                "api_key": api_key,
                "base_url": base_url,
            })

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
    typer.echo(json.dumps(content, indent=2, ensure_ascii=False))
    raise typer.Exit(code=ExitCode.SUCCESS)
