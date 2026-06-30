"""ol extract-terms — Auto-extract key terms from source text (KeyBERT+YAKE).

Companion CLI to the OL MCP extract_terms tool. Reads a markdown
file, splits into paragraphs (by blank line), and extracts top-N
terms. Outputs JSON (term -> score) to file or stdout.

If KeyBERT and YAKE are not installed, prints a clear actionable error
and exits non-zero (matches the MCP tool's behavior).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from cli._shared import ExitCode


def extract_terms(
    input_file: str | None = typer.Option(
        None, "--input", "-i", help="Input markdown file (or read stdin if omitted)"
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output JSON file (or write stdout if omitted)"
    ),
    top_n: int = typer.Option(20, "--top-n", "-n", help="Max number of terms to return"),
) -> None:
    """Extract key terms from source text. Requires: pip install omni-localizer[ml]."""
    try:
        from ol_terminology.extractor import extract_terms as _extract_terms
    except ImportError as e:
        typer.echo(
            f"Error: ML dependencies not installed. Run: pip install omni-localizer[ml] ({e})",
            err=True,
        )
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    if input_file:
        text = Path(input_file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    # Split by blank line(s) into paragraphs as a list of texts
    texts = [t.strip() for t in text.split("\n\n") if t.strip()]
    if not texts:
        typer.echo("Error: input text is empty", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    all_terms = _extract_terms(texts)
    sorted_terms = sorted(
        all_terms.items(), key=lambda kv: kv[1], reverse=True
    )[:top_n]
    result = {"terms": dict(sorted_terms), "term_count": len(sorted_terms)}

    if output:
        Path(output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        typer.echo(f"Wrote {len(sorted_terms)} terms to: {output}")
    else:
        typer.echo(json.dumps(result, ensure_ascii=False))

    raise typer.Exit(code=ExitCode.SUCCESS)
