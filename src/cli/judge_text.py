"""ol judge-text — Evaluate translation quality using LLM judge.

Companion CLI to the OL MCP judge_text tool. Prints the score (0-100)
and rubric breakdown (adequacy, fluency, terminology, format) as JSON.
"""
from __future__ import annotations

import json
from typing import Optional

import typer

from cli._shared import ExitCode, warn_fake_llm_mode


def judge_text(
    source: str = typer.Argument(..., help="Source text to evaluate"),
    target: str = typer.Argument(..., help="Target (translated) text to evaluate"),
    source_lang: str = typer.Option("en", "--source-lang", "-s", help="Source language code"),
    target_lang: str = typer.Option("zh", "--target-lang", "-t", help="Target language code"),
    glossary: Optional[str] = typer.Option(
        None, "--glossary", "-g",
        help="Path to glossary JSON file (e.g. from ol load-glossary)"
    ),
    config: Optional[str] = typer.Option(
        None, "--config", "-c",
        help="Path to OL YAML config (overrides OL_CONFIG_PATH env and cwd-default)"
    ),
) -> None:
    """Evaluate translation quality using LLM judge (OL#8 rubric).

    Reads the LLM's native fields (accuracy, score) directly because the
    underlying _remap_llm_fields in ol_lqa/judge.py only emits adequacy,
    fluency, accuracy, and score. The 'terminology_consistency' and
    'format_preservation' fields seen in the broader evaluation pipeline
    are not produced by the LLM and would always default to 50 in this CLI.
    Once the upstream remap is fixed, this CLI should be updated to read
    the canonical fields instead.
    """
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
        warn_fake_llm_mode()
        pool = ModelPool.get_instance(_get_config_path(config))
        result = asyncio.run(pool.judge(
            source, target, source_lang, target_lang, glossary_dict,
        ))
    except FileNotFoundError as e:
        typer.echo(
            f"Error: config file not found: {e}\n"
            f"  Use --config <path> or set OL_CONFIG_PATH to point to your OL YAML config.\n"
            f"  Or run from the OL project root (the directory containing config/default.yaml).",
            err=True,
        )
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)
    except Exception as e:
        typer.echo(f"Error: judge failed: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    # WORKAROUND: read the LLM-direct fields. The upstream
    # ol_lqa/judge.py remap only produces adequacy/fluency/accuracy/score
    # — the 'terminology_consistency' and 'format_preservation' fields
    # that other OL code expects would always default to 50 in this CLI.
    # Issue filed against ol_lqa/judge.py for the upstream field-name
    # mismatch; this CLI reads the LLM-direct fields for now.
    content = {
        "score": result.get("score", 50),
        "reason": result.get("reason", ""),
        "rubric": {
            "adequacy": result.get("adequacy", 50),
            "fluency": result.get("fluency", 50),
            "accuracy": result.get("accuracy", 50),
        },
    }
    typer.echo(json.dumps(content, indent=2, ensure_ascii=False))
    raise typer.Exit(code=ExitCode.SUCCESS)
