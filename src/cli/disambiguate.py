"""ol disambiguate — Resolve polysemous terms using context-aware scoring.

Companion CLI to the OL MCP disambiguate tool. Reads text from a file
or stdin, applies confidence-based disambiguation against a glossary
file, and outputs the resolved terms as JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from cli._shared import ExitCode


def disambiguate(
    text_file: str | None = typer.Option(
        None, "--text", "-t", help="Input text file (or read stdin if omitted)"
    ),
    glossary: str = typer.Option(
        ..., "--glossary", "-g", help="Path to glossary JSON file"
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output JSON file (or write stdout if omitted)"
    ),
) -> None:
    """Resolve polysemous terms using confidence-based selection (no LLM)."""
    if text_file:
        text = Path(text_file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    glossary_dict = json.loads(Path(glossary).read_text(encoding="utf-8"))

    from ol_terminology.disambiguator import disambiguate as _disambiguate

    try:
        resolved = _disambiguate(text, glossary_dict)
    except Exception as e:
        typer.echo(f"Error: disambiguation failed: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    result = {"resolved_terms": resolved, "resolved_count": len(resolved)}
    if output:
        Path(output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        typer.echo(f"Wrote {len(resolved)} resolved terms to: {output}")
    else:
        typer.echo(json.dumps(result, ensure_ascii=False))

    raise typer.Exit(code=ExitCode.SUCCESS)
