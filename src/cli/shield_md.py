"""ol shield-md — Protect code/links/etc. in markdown with [OL:TYPE:NNNN] placeholders.

Companion CLI to the OL MCP shield_md_text tool. The shield text +
shield_map are written to the output file (or stdout). Use the
companion ``ol unshield-md`` command to restore the placeholders.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from cli._shared import ExitCode
from ol_md.shield import shield_markdown


def shield_md(
    input_file: str | None = typer.Option(
        None, "--input", "-i", help="Input markdown file (or read stdin if omitted)"
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output file (or write stdout if omitted)"
    ),
    pretty: bool = typer.Option(
        False, "--pretty", help="Print the shield_map JSON alongside the shielded text"
    ),
) -> None:
    """Shield code/links/math/HTML/images in markdown before LLM translation."""
    if input_file:
        content = Path(input_file).read_text(encoding="utf-8")
    else:
        content = sys.stdin.read()

    shielded, shield_map = shield_markdown(content)

    if output:
        Path(output).write_text(shielded, encoding="utf-8")
        typer.echo(f"Wrote shielded markdown to: {output}")
    else:
        typer.echo(shielded, nl=False)

    if pretty:
        typer.echo(json.dumps(shield_map, indent=2, ensure_ascii=False))

    raise typer.Exit(code=ExitCode.SUCCESS)
