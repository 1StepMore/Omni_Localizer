"""ol doctor — Validate the OL configuration (5-check checklist).

Companion to `ol init`: after bootstrapping config/local.yaml, run
`ol doctor` to verify the file exists, parses, loads through the
schema, has >=2 models per role, and every ${ENV_VAR} reference
resolves. Any FAIL prints a hint to run `ol init` and exits 1.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

import typer

from cli._shared import ExitCode, hint_init_suggestion
from ol_logging.core import get_logger

logger = get_logger("cli")

# Human-readable checklist names (display order).
_CHECK_NAMES: tuple[str, ...] = (
    "config file exists",
    "yaml parses",
    "load_config succeeds",
    "min models per role",
    "env vars resolve",
)

# Machine-readable JSON keys (same order as _CHECK_NAMES).
_JSON_KEYS: tuple[str, ...] = (
    "config_file_exists",
    "yaml_parses",
    "load_config_succeeds",
    "min_models_per_role",
    "env_vars_resolve",
)

_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _resolve_config_path(config_path: str | None) -> Path:
    """Resolve the config to validate: --config → local.yaml → OL_CONFIG_PATH → default.yaml."""
    if config_path:
        return Path(config_path)
    local = Path("config/local.yaml")
    if local.is_file():
        return local
    env_path = os.environ.get("OL_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    return Path("config/default.yaml")


def _missing_env_refs(config) -> list[str]:
    """Return sorted unique ${VAR} refs across the pool that are unset."""
    missing: set[str] = set()
    pool = config.llm_pool
    for role in ("translation", "judging", "restoration", "profiling"):
        for model in getattr(pool, role, []):
            for field in ("api_key", "base_url"):
                value = getattr(model, field, None)
                if not isinstance(value, str):
                    continue
                for var in _ENV_VAR_RE.findall(value):
                    if var not in os.environ:
                        missing.add(f"{role}/{model.model}/{field}:${{{var}}}")
    return sorted(missing)


def doctor(
    config_path: Optional[str] = typer.Option(
        None, "--config", "-c",
        help="Config to validate (default: config/local.yaml → OL_CONFIG_PATH → config/default.yaml)",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Machine-readable JSON output"
    ),
) -> None:
    """Validate the OL config with a 5-check checklist."""
    import yaml
    from ol_config.loader import SecurityError, load_config

    target = _resolve_config_path(config_path)

    results: dict[str, bool] = {key: False for key in _JSON_KEYS}

    # 1. config file exists
    results["config_file_exists"] = target.is_file()

    # 2. YAML parses
    if results["config_file_exists"]:
        try:
            with open(target, encoding="utf-8") as f:
                yaml.safe_load(f)
            results["yaml_parses"] = True
        except Exception as exc:
            # Deliberate swallow: reported via results["yaml_parses"]; logged for auditability.
            logger.debug("doctor: YAML parse failed: %s", exc)
            results["yaml_parses"] = False

    # 3. load_config succeeds (schema validation incl. min-models-per-role)
    config = None
    if results["yaml_parses"]:
        try:
            config, _ = load_config(str(target))
            results["load_config_succeeds"] = True
        except (FileNotFoundError, ValueError, SecurityError):
            results["load_config_succeeds"] = False

    # 4. per-role model count >= 2 (translation/judging/restoration)
    if results["load_config_succeeds"]:
        pool = config.llm_pool
        counts = {
            "translation": len(pool.translation),
            "judging": len(pool.judging),
            "restoration": len(pool.restoration),
        }
        results["min_models_per_role"] = all(c >= 2 for c in counts.values())

    # 5. every ${ENV_VAR} ref across the pool resolves (api_key + base_url)
    if results["load_config_succeeds"]:
        results["env_vars_resolve"] = not _missing_env_refs(config)

    ok = all(results.values())

    if json_output:
        typer.echo(json.dumps({"ok": ok, "checks": results}, ensure_ascii=False))
    else:
        for name, key in zip(_CHECK_NAMES, _JSON_KEYS):
            typer.echo(f"[{'PASS' if results[key] else 'FAIL'}] {name}")

    if not ok:
        hint_init_suggestion()
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    raise typer.Exit(code=ExitCode.SUCCESS)
