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
from ol_mcp.security import get_default_validator


def load_glossary(
    path: str = typer.Argument(..., help="Path to JSON glossary file"),
    config_dir: Optional[str] = typer.Option(
        None, "--config-dir",
        help="Base dir for relative paths (matches the MCP tool's config_dir)"
    ),
) -> None:
    """Load a JSON glossary file and print as JSON."""
    vresult = get_default_validator().validate_path(path)
    if not vresult.success:
        typer.echo(f"Error: {vresult.error}", err=True)
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
