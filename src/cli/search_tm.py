"""ol search-tm — Search TMX translation memory for similar past translations.

Companion CLI to the OL MCP search_tm tool. Prints matches as JSON.
"""
from __future__ import annotations

import json
from typing import Optional

import typer

from cli._shared import ExitCode
from ol_mcp.security import get_default_validator


def search_tm(
    source_text: str = typer.Argument(..., help="Text to search for in TM"),
    tmx_path: str = typer.Argument(..., help="Path to .tmx translation memory file"),
    threshold: float = typer.Option(0.85, "--threshold", "-t", help="Minimum similarity (0-1)"),
    source_lang: str = typer.Option("en", "--source-lang", "-s", help="Source language code"),
    target_lang: str = typer.Option("zh", "--target-lang", "-g", help="Target language code"),
) -> None:
    """Search translation memory for similar past translations."""
    vresult = get_default_validator().validate_path(tmx_path)
    if not vresult.success:
        typer.echo(f"Error: {vresult.error}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        from ol_tm.service import TMService
        svc = TMService(tmx_path)
        matches = svc.search(
            source_text,
            threshold=threshold,
            src_lang=source_lang,
            tgt_lang=target_lang,
        )
    except Exception as e:
        typer.echo(f"Error: TM search failed: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    if not matches:
        # Better error message: help the user debug. The most common
        # cause of 0 matches is a language-pair mismatch (TMX stores
        # exact codes like "EN-US" while the CLI passes "en").
        typer.echo(
            f"No matches found for source_lang={source_lang!r} "
            f"target_lang={target_lang!r} (threshold={threshold}).\n"
            f"  Common causes:\n"
            f"    1. TMX file uses different language codes "
            f"(e.g. 'EN-US' vs 'en') — language match is exact\n"
            f"    2. Threshold is too high — try --threshold 0.5 to see\n"
            f"       lower-similarity matches\n"
            f"    3. TMX file is empty or has wrong language pairs",
            err=True,
        )
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    content = {
        "matches": [
            {
                "source": m.source,
                "target": m.target,
                "similarity": m.similarity,
                "language_pair": m.language_pair,
            }
            for m in matches
        ],
        "count": len(matches),
    }
    typer.echo(json.dumps(content, ensure_ascii=False))
    raise typer.Exit(code=ExitCode.SUCCESS)
