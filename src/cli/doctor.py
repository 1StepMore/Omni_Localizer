"""ol doctor — Validate the OL configuration (5-check checklist).

Companion to `ol init`: after bootstrapping config/local.yaml, run
`ol doctor` to verify the file exists, parses, loads through the
schema, has >=2 models per role, and every configured role has at
least one model whose ${ENV_VAR} refs all resolve. Any FAIL prints a
hint to run `ol init` and exits 1.
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


def _unresolved_refs(model) -> list[str]:
    """Names of ${VAR} refs in a model's api_key/base_url that are unset."""
    missing: list[str] = []
    for field in ("api_key", "base_url"):
        value = getattr(model, field, None)
        if not isinstance(value, str):
            continue
        for var in _ENV_VAR_RE.findall(value):
            if not os.environ.get(var) and var not in missing:
                missing.append(var)
    return missing


def _missing_env_refs(config) -> list[str]:
    """Return the decorated refs of models that starve a role.

    Mirrors ``router.partition_usable_models`` + the ``ModelPool``
    fail-closed rule (router.py:320-347 / 418-443): a model is unusable
    when any of its ``${VAR}`` refs is unset, and a role is starved only
    when it is configured with >=1 model but every one of them is
    unusable. A role that still has a usable fallback is fine (BYOK —
    one provider key is enough), and a role with no configured models
    cannot starve. Starved roles alone are reported; unset fallbacks in
    otherwise-usable roles are not.
    """
    starved: set[str] = set()
    pool = config.llm_pool
    for role in ("translation", "judging", "restoration", "profiling"):
        models = list(getattr(pool, role, []) or [])
        if not models:
            continue
        if any(not _unresolved_refs(m) for m in models):
            continue
        for model in models:
            for field in ("api_key", "base_url"):
                value = getattr(model, field, None)
                if not isinstance(value, str):
                    continue
                for var in _ENV_VAR_RE.findall(value):
                    if not os.environ.get(var):
                        starved.add(f"{role}/{model.model}/{field}:${{{var}}}")
    return sorted(starved)


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

    # 5. every configured role has >=1 usable model (all its ${VAR} refs
    # resolve) — the router's real fail-closed rule, not "every var set".
    if results["load_config_succeeds"]:
        results["env_vars_resolve"] = not _missing_env_refs(config)

    ok = all(results.values())

    if json_output:
        typer.echo(json.dumps({"ok": ok, "checks": results}, ensure_ascii=False))
    else:
        for name, key in zip(_CHECK_NAMES, _JSON_KEYS):
            typer.echo(f"[{'PASS' if results[key] else 'FAIL'}] {name}")

    if not ok:
        if results["load_config_succeeds"]:
            for detail in _missing_env_refs(config):
                typer.echo(f"  env: {detail}", err=True)
        hint_init_suggestion()
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    raise typer.Exit(code=ExitCode.SUCCESS)
