"""ol verify-terms — Verify glossary term usage in translated content.

Companion CLI to the (planned) OL MCP verify_terms tool. Reads a
source file and a target file, optionally loads a glossary, runs
``ol_terminology.verifier.verify_translation()``, and prints a
JSON report.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from cli._shared import ExitCode, validate_input_file
from ol_terminology.verifier import verify_translation


def verify_terms(
    source: str = typer.Option(
        ..., "--source", "-s",
        help="Path to the source text file (UTF-8)",
    ),
    target: str = typer.Option(
        ..., "--target", "-t",
        help="Path to the target (translated) text file (UTF-8)",
    ),
    glossary: Optional[str] = typer.Option(
        None, "--glossary", "-g",
        help="Path to glossary JSON file (optional; if omitted, runs consistency-only mode)",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Path to write the JSON report. If omitted, prints to stdout.",
    ),
    confidence_threshold: float = typer.Option(
        0.7, "--confidence-threshold",
        help="Minimum glossary term confidence to include in main checks (0-1). "
             "Terms below this threshold are reported as low_confidence.",
    ),
) -> None:
    """Verify glossary term usage in translated content.

    With --glossary: each glossary term is checked against the target.
    Without --glossary: detects inconsistent translations across sentences.
    """
    # Validate input files
    try:
        src_path = validate_input_file(source)
        tgt_path = validate_input_file(target)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    # Read content
    try:
        source_text = src_path.read_text(encoding="utf-8")
        target_text = tgt_path.read_text(encoding="utf-8")
    except OSError as e:
        typer.echo(f"Error reading input files: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    # Load glossary if provided
    glossary_dict = None
    if glossary:
        try:
            from ol_terminology.glossary import load_glossary_from_path
            glossary_dict = load_glossary_from_path(glossary)
        except (FileNotFoundError, ValueError) as e:
            typer.echo(f"Error loading glossary: {e}", err=True)
            raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    # Run verification
    try:
        report = verify_translation(
            source_text=source_text,
            target_text=target_text,
            glossary=glossary_dict,
            confidence_threshold=confidence_threshold,
        )
    except Exception as e:
        typer.echo(f"Error: verification failed: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    # Output
    output_dict = report.to_dict()
    output_json = json.dumps(output_dict, ensure_ascii=False, indent=2)
    if output:
        try:
            Path(output).write_text(output_json, encoding="utf-8")
        except OSError as e:
            typer.echo(f"Error writing output file: {e}", err=True)
            raise typer.Exit(code=ExitCode.PIPELINE_ERROR)
        typer.echo(f"Report written to: {output}")
    else:
        typer.echo(output_json)
    raise typer.Exit(code=ExitCode.SUCCESS)
