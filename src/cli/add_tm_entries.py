"""ol add-tm-entries — Add entries to a TMX translation memory file.

Companion CLI to the OL MCP add_tm_entries tool. Two modes:
- Batch: --entries <json_file> containing an array of {source, target,
  source_lang, target_lang} dicts
- Single: --source/--target/--source-lang/--target-lang flags for one
  entry at a time

If the TMX file does not exist, it is created.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from cli._shared import ExitCode


def add_tm_entries(
    tmx_path: str = typer.Argument(..., help="Path to .tmx file (created if missing)"),
    entries: Optional[str] = typer.Option(
        None, "--entries", "-e", help="Path to JSON file with array of {source, target, source_lang, target_lang}"
    ),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Single-entry mode: source text"),
    target: Optional[str] = typer.Option(None, "--target", "-t", help="Single-entry mode: target text"),
    source_lang: Optional[str] = typer.Option(None, "--source-lang", help="Single-entry mode: source language code"),
    target_lang: Optional[str] = typer.Option(None, "--target-lang", help="Single-entry mode: target language code"),
) -> None:
    """Add entries to a TMX translation memory file. Requires: pip install omni-localizer[ml]."""
    try:
        from ol_tm.service import TMService
    except ImportError as e:
        typer.echo(
            f"Error: ML dependencies not installed. Run: pip install omni-localizer[ml] ({e})",
            err=True,
        )
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    if entries:
        # Batch mode
        entry_list = json.loads(Path(entries).read_text(encoding="utf-8"))
        if not isinstance(entry_list, list):
            typer.echo("Error: --entries file must contain a JSON array", err=True)
            raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)
    elif source and target and source_lang and target_lang:
        # Single mode
        entry_list = [{
            "source": source,
            "target": target,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }]
    else:
        typer.echo(
            "Error: provide --entries <json> OR all of --source/--target/--source-lang/--target-lang",
            err=True,
        )
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        svc = TMService(tmx_path)
        for e in entry_list:
            svc.add(e["source"], e["target"], e["source_lang"], e["target_lang"])
        svc.flush()
        typer.echo(f"Added {len(entry_list)} entries to: {tmx_path}")
    except Exception as e:
        typer.echo(f"Error: failed to add TM entries: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    raise typer.Exit(code=ExitCode.SUCCESS)
