"""ol judge-text — Evaluate translation quality using LLM judge.

Companion CLI to the OL MCP judge_text tool. Prints the score (0-100)
and rubric breakdown (adequacy, fluency, terminology, format) as JSON.
"""
from __future__ import annotations

import json
from typing import Optional

import typer

from cli._shared import ExitCode


def judge_text(
    source: str = typer.Argument(..., help="Source text to evaluate"),
    target: str = typer.Argument(..., help="Target (translated) text to evaluate"),
    source_lang: str = typer.Option("en", "--source-lang", "-s", help="Source language code"),
    target_lang: str = typer.Option("zh", "--target-lang", "-t", help="Target language code"),
    glossary: Optional[str] = typer.Option(
        None, "--glossary", "-g",
        help="Path to glossary JSON file (e.g. from ol load-glossary)"
    ),
) -> None:
    """Evaluate translation quality using LLM judge (OL#8 rubric)."""
    if source_lang == target_lang:
        typer.echo("Error: source and target languages must be different", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    glossary_dict = None
    if glossary:
        glossary_dict = json.loads(open(glossary, encoding="utf-8").read())

    try:
        import asyncio
        from ol_pool.router import ModelPool
        from ol_mcp.tools import _get_config_path
        pool = ModelPool.get_instance(_get_config_path(None))
        result = asyncio.run(pool.judge(
            source, target, source_lang, target_lang, glossary_dict,
        ))
    except Exception as e:
        typer.echo(f"Error: judge failed: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    content = {
        "score": result.get("score", 50),
        "reason": result.get("reason", ""),
        "rubric": {
            "adequacy": result.get("adequacy", 50),
            "fluency": result.get("fluency", 50),
            "terminology": result.get("terminology_consistency", 50),
            "format": result.get("format_preservation", 50),
        },
    }
    typer.echo(json.dumps(content, indent=2, ensure_ascii=False))
    raise typer.Exit(code=ExitCode.SUCCESS)
