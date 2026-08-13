"""ol load-glossary — Load a JSON glossary file.

Companion CLI to the OL MCP load_glossary tool. Prints the loaded
glossary as JSON (term_count + full glossary dict).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from cli._shared import ExitCode


def load_glossary(
    path: str = typer.Argument(..., help="Path to JSON glossary file"),
    config_dir: Optional[str] = typer.Option(
        None, "--config-dir",
        help="Base dir for relative paths (matches the MCP tool's config_dir)"
    ),
    allow_dir: Optional[list[str]] = typer.Option(
        None, "--allow-dir", "-a",
        help=(
            "Additional directory to allow for path validation. "
            "Can be passed multiple times. "
            "These are merged with OL_MCP_ALLOWED_DIRS env var and the default."
        )
    ),
) -> None:
    """Load a JSON glossary file and print as JSON."""
    from pathlib import Path as _P
    from ol_mcp.security import PathValidator as _PV

    # Build a custom validator that extends the default allowlist with
    # any directories provided via --allow-dir. This is needed because
    # the default validator only allows project root + /tmp + env-configured
    # dirs, which is too restrictive when loading glossaries from other
    # paths (e.g. a shared corpus directory).
    base_dirs: list = []
    env_dirs = __import__('os').environ.get(
        "OL_MCP_ALLOWED_DIRS",
        __import__('os').environ.get("OL_ALLOWED_DIRECTORIES", ""),
    )
    if env_dirs.strip():
        base_dirs.extend(_P(d).resolve() for d in env_dirs.split(",") if d.strip())
    if allow_dir:
        base_dirs.extend(_P(d).resolve() for d in allow_dir if d.strip())
    if not base_dirs:
        # Fallback: default allowlist (project root + /tmp)
        base_dirs = [_P.cwd().resolve(), _P("/tmp").resolve()]
    validator = _PV(allowed_directories=base_dirs)

    vresult = validator.validate_path(path)
    if not vresult.success:
        typer.echo(
            f"Error: {vresult.error}\n"
            f"  Use --allow-dir <path> (can be repeated) to add a path to the allowlist,\n"
            f"  or set OL_MCP_ALLOWED_DIRS env var (comma-separated).",
            err=True,
        )
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        from ol_terminology.glossary import load_glossary_from_path
        glossary = load_glossary_from_path(
            path,
            config_dir=Path(config_dir) if config_dir else None,
        )
    except Exception as e:
        typer.echo(f"Error: failed to load glossary: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    content = {"glossary": glossary, "term_count": len(glossary)}
    typer.echo(json.dumps(content, ensure_ascii=False))
    raise typer.Exit(code=ExitCode.SUCCESS)
