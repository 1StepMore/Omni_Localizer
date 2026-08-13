"""ol unshield-md — Restore [OL:TYPE:NNNN] placeholders in markdown.

Companion CLI to the OL MCP unshield_md_text tool. Reads the
shield_map (from JSON file or stdin) and the shielded text (from file
or stdin), and writes the restored markdown to file or stdout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from cli._shared import ExitCode
from ol_md.shield import unshield_markdown


def unshield_md(
    input_file: str | None = typer.Option(
        None, "--input", "-i", help="Input markdown file (or read stdin if omitted)"
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output file (or write stdout if omitted)"
    ),
    shield_map: str = typer.Option(
        ..., "--shield-map", "-m",
        help="Path to JSON file containing the shield_map from shield-md"
    ),
) -> None:
    """Restore shielded markers after LLM translation."""
    shield_map_dict = json.loads(Path(shield_map).read_text(encoding="utf-8"))

    if input_file:
        content = Path(input_file).read_text(encoding="utf-8")
    else:
        content = sys.stdin.read()

    restored = unshield_markdown(content, shield_map_dict)

    if output:
        Path(output).write_text(restored, encoding="utf-8")
        typer.echo(f"Wrote restored markdown to: {output}")
    else:
        typer.echo(restored, nl=False)

    raise typer.Exit(code=ExitCode.SUCCESS)
