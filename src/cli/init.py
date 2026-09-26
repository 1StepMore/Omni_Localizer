"""ol init — Bootstrap a local OL config (config/local.yaml).

Generates a YAML config with the unified 3-provider LLM pool that mirrors
``config/default.yaml`` (the single source of truth), in priority order:
glm-4.7-flash (Zhipu) + minimaxai/minimax-m3 (NVIDIA NIM) + ark-code-latest
(Volcengine Ark). Every api_key/base_url is a ${ENV_VAR} reference — literal
keys are never written.
"""
from __future__ import annotations

from typing import Optional

import typer

from cli._shared import ExitCode

# Mirrors config/default.yaml (the source of truth): provider "openai",
# timeout 120.0, all api_key/base_url as ${ENV_VAR} refs. Parity is locked by
# tests/test_model_pool_config_parity.py — keep the two in sync.
_POOL_MODELS: tuple[tuple[str, str, str], ...] = (
    ("glm-4.7-flash", "${ZHIPU_API_KEY}", "https://open.bigmodel.cn/api/paas/v4"),
    ("minimaxai/minimax-m3", "${NVIDIA_NIM_API_KEY}", "https://integrate.api.nvidia.com/v1"),
    ("ark-code-latest", "${ARK_API_KEY}", "https://ark.cn-beijing.volces.com/api/coding/v3"),
)

UNIFIED_POOL_PRESET: dict[str, list[dict[str, str | int | float]]] = {
    role: [
        {
            "provider": "openai",
            "model": model,
            "priority": priority,
            "role": role,
            "api_key": api_key,
            "base_url": base_url,
            "timeout": 120.0,
        }
        for priority, (model, api_key, base_url) in enumerate(_POOL_MODELS, start=1)
    ]
    for role in ("translation", "judging", "restoration", "profiling")
}

# Env vars the generated config references (for the export hint). Order is
# presentation-only (parity compares sets) but must track _POOL_MODELS.
PRESET_ENV_VARS: tuple[str, ...] = (
    "ZHIPU_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "ARK_API_KEY",
)


def init(
    config_path: Optional[str] = typer.Option(
        None, "--config", "-c",
        help="Path to write the generated config (default: config/local.yaml)",
    ),
    preset: str = typer.Option(
        "default", "--preset", help="Preset to generate (default)"
    ),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Skip prompts"
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite existing config"
    ),
) -> None:
    """Bootstrap a local OL config with the unified LLM model pool."""
    from pathlib import Path

    import yaml

    target = Path(config_path) if config_path else Path("config/local.yaml")

    if preset != "default":
        typer.echo(
            f"Warning: unknown preset {preset!r}; using 'default'",
            err=True,
        )

    if target.exists() and not force:
        typer.echo(
            f"Error: {target} already exists. Use --force to overwrite.",
            err=True,
        )
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    # Interactive branch: ask which provider keys the user has, so the
    # final export hint only lists what they actually hold. Answers are
    # never written to the YAML — only ${ENV_VAR} refs are.
    have_keys: dict[str, bool] = {}
    if non_interactive:
        have_keys = {var: True for var in PRESET_ENV_VARS}
    else:
        for var in PRESET_ENV_VARS:
            have_keys[var] = typer.confirm(f"Do you have {var} set?")

    data = {
        "project_id": "ol-local",
        "source_lang": "en",
        "target_lang": "zh",
        "glossary_path": None,
        "llm_pool": UNIFIED_POOL_PRESET,
        "enable_lqa": True,
        "lqa_threshold": 7.0,
        "lqa_max_retries": 2,
        "max_xliff_concurrent": 5,
        "quality_gates": {
            "inline_tags": True,
            "terminology": True,
            "source_script_check": True,
            "protocol_artifact_check": True,
            "block_on_source_script_fragment": True,
            "length_ratio": {"enabled": True, "min": 0.5, "max": 2.0},
            "locale": {"enabled": True, "target_locale": "en-US"},
        },
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    _ = target.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    typer.echo(f"Wrote {target}")
    typer.echo("Export these env vars before running OL:")
    for var in PRESET_ENV_VARS:
        if have_keys.get(var):
            typer.echo(f"  export {var}=...")
    typer.echo(f"Run `ol doctor --config {target}` to validate")
    raise typer.Exit(code=ExitCode.SUCCESS)
