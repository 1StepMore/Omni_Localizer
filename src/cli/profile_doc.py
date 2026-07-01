"""ol profile-doc — Profile a document's writing style.

Reads a document, calls the LLM-based doc_profiler, and prints the
resulting StyleGuide as JSON. With --output, writes to a file.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer

from cli._shared import ExitCode, validate_input_file
from ol_style.cache import ProfileCache
from ol_style.doc_profiler import profile_document


def profile_doc(
    input_file: str = typer.Argument(
        ..., help="Path to input document (UTF-8)",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Path to write the JSON profile. If omitted, prints to stdout.",
    ),
    source_lang: str = typer.Option(
        "en", "--source-lang", "-s",
        help="Source language code (default: en)",
    ),
    config: Optional[str] = typer.Option(
        None, "--config", "-c",
        help="Path to OL YAML config (default: config/default.yaml)",
    ),
    cache_dir: Optional[str] = typer.Option(
        None, "--cache-dir",
        help="Directory to store profile cache. If omitted, in-memory only.",
    ),
) -> None:
    """Profile a document's writing style and emit a StyleGuide."""
    try:
        path = validate_input_file(input_file)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        typer.echo(f"Error reading input file: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    cache: ProfileCache | None = None
    if cache_dir:
        cache = ProfileCache(cache_dir=Path(cache_dir))
    else:
        cache = ProfileCache()

    try:
        guide = asyncio.run(profile_document(
            content=content,
            source_lang=source_lang,
            config_path=config,
            cache=cache,
        ))
    except Exception as e:
        typer.echo(f"Error: profiling failed: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    output_dict = guide.to_dict()
    output_json = json.dumps(output_dict, ensure_ascii=False, indent=2)
    if output:
        try:
            Path(output).write_text(output_json, encoding="utf-8")
        except OSError as e:
            typer.echo(f"Error writing output file: {e}", err=True)
            raise typer.Exit(code=ExitCode.PIPELINE_ERROR)
        typer.echo(f"Profile written to: {output}")
    else:
        typer.echo(output_json)
    raise typer.Exit(code=ExitCode.SUCCESS)
