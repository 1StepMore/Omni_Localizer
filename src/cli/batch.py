"""translate-batch and extract-warnings CLI commands."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    pass

from cli._shared import (
    ExitCode,
    ensure_output_dir,
    output_json,
    validate_input_file,
)
from ol_logging.core import get_logger

logger = get_logger("cli")


async def _translate_batch_async(
    directory: Path,
    output_dir: Path,
    config_path: str | None,
    src_lang: str,
    tgt_lang: str,
    glossary: dict[str, Any] | None = None,
    max_concurrent: int = 5,
    add_frontmatter: bool = True,
    detect_language: bool = True,
) -> tuple[int, int]:
    from ol_batch.config import BatchConfig
    from ol_batch.discovery import discover_files, validate_directory
    from ol_batch.processor import BatchProcessor
    from ol_batch.progress import ProgressContext
    from ol_batch.summary import print_summary
    from ol_concurrency.scheduler import ConcurrencyLimiter
    from ol_pool.router import ModelPool

    if not validate_directory(directory):
        raise ValueError(f"Directory not found or is not a directory: {directory}")

    file_patterns = ["*.md", "*.xliff", "*.xlf"]
    files = discover_files(directory, file_patterns)

    if not files:
        typer.echo(f"No files found in {directory} matching {file_patterns}")
        return (0, 0)

    typer.echo(f"Found {len(files)} files to process")

    batch_config = BatchConfig(max_concurrent=max_concurrent)
    pool = ModelPool.get_instance(config_path) if config_path else ModelPool.get_instance()

    # POST_MORTEM OL-1: surface LQA knobs to the batch path.
    from ol_config.loader import load_config
    cfg, _ = load_config(config_path or "config/default.yaml")
    enable_lqa = getattr(cfg, "enable_lqa", False)
    lqa_threshold = getattr(cfg, "lqa_threshold", 7.0)
    lqa_max_retries = getattr(cfg, "lqa_max_retries", 2)

    limiter = ConcurrencyLimiter(max_translation=max_concurrent)
    processor = BatchProcessor(
        config=batch_config, model_pool=pool, limiter=limiter, glossary=glossary,
        enable_lqa=enable_lqa,
        lqa_threshold=lqa_threshold, lqa_max_retries=lqa_max_retries,
    )

    start_time = time.time()
    async with ProgressContext() as _:
        result = await processor.process_batch(
            files,
            output_dir,
            add_frontmatter=add_frontmatter,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            detect_language=detect_language,
            enable_lqa=enable_lqa,
            lqa_threshold=lqa_threshold,
            lqa_max_retries=lqa_max_retries,
        )

    duration = time.time() - start_time
    print_summary(result, duration)

    return (len(result.succeeded), len(result.failed))


# ---------------------------------------------------------------------------
# translate-batch command (plain function, registered by ol_cli.py)
# ---------------------------------------------------------------------------

def translate_batch(
    directory: str = typer.Argument(..., help="Input directory path"),
    output_dir: str | None = typer.Option(None, "--output-dir", "-o", help="Output directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    source_lang: str | None = typer.Option(
        None, "--source-lang", "-s", help="Source language (overrides config)"
    ),
    target_lang: str | None = typer.Option(
        None, "--target-lang", "-t", help="Target language (overrides config)"
    ),
    concurrency: int = typer.Option(5, "--concurrency", "-j", help="Max concurrent translations"),
    add_frontmatter: bool = typer.Option(
        True, "--frontmatter/--no-frontmatter", help="Add frontmatter to translated files"
    ),
    detect_language: bool = typer.Option(
        True,
        "--detect-language/--no-detect-language",
        help="Detect source language before translating",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output JSON instead of human-readable text"
    ),
) -> int:
    try:
        input_path = Path(directory)
        if not input_path.exists():
            raise typer.BadParameter(f"Directory not found: {directory}")
        if not input_path.is_dir():
            raise typer.BadParameter(f"Input is not a directory: {directory}")
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    if not output_dir:
        typer.echo("Error: --output-dir is required", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        output_path = ensure_output_dir(output_dir)
    except Exception as e:  # expected — CLI error, echoes then exits
        typer.echo(f"Error: Cannot create output directory: {e}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    logger.info(f"Command: translate_batch {directory}")
    try:
        src = source_lang or "en"
        tgt = target_lang or "zh"

        if config:
            from ol_config.loader import load_config

            cfg, glossary = load_config(config)
            src = src or cfg.source_lang
            tgt = tgt or cfg.target_lang
            typer.echo(f"Using config: {cfg.project_id} ({src} -> {tgt})")
        else:
            src = src or "en"
            tgt = tgt or "zh"

        succeeded, failed = asyncio.run(
            _translate_batch_async(
                input_path,
                output_path,
                config,
                src,
                tgt,
                glossary if config else None,
                concurrency,
                add_frontmatter,
                detect_language,
            ),
        )

        if failed > 0:
            if json_output:
                output_json(False, directory, error=f"{failed} files failed")
            logger.info(f"Completed: translate_batch {directory}")
            raise typer.Exit(code=ExitCode.PIPELINE_ERROR)
        if json_output:
            output_json(True, directory, source_lang=src, target_lang=tgt)
        logger.info(f"Completed: translate_batch {directory}")
        raise typer.Exit(code=ExitCode.SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            output_json(False, directory, error=str(e))
        else:
            typer.echo(f"Pipeline error: {e}", err=True)
        logger.error(f"Failed: translate_batch {directory} - {e}")
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)


# ---------------------------------------------------------------------------
# extract-warnings command (plain function, registered by ol_cli.py)
# ---------------------------------------------------------------------------

def extract_warnings(
    input: str = typer.Argument(..., help="Input file path (MD or XLIFF)"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path"),
) -> int:
    try:
        input_path = validate_input_file(input)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    logger.info(f"Command: extract_warnings {input}")
    try:
        content = input_path.read_text(encoding="utf-8")
        warnings = []
        import re

        md_warn_pattern = re.compile(r"<!--\s*OL_WARN:\s*([^>]+)\s*-->")
        for match in md_warn_pattern.finditer(content):
            warnings.append(f"MD: {match.group(0)}")

        xliff_warn_pattern = re.compile(r'<note\s+from="OL"[^>]*>([^<]+)</note>')
        for match in xliff_warn_pattern.finditer(content):
            warnings.append(f"XLIFF: {match.group(0)}")

        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_content = "\n".join(warnings) if warnings else "# No warnings found"
            output_path.write_text(output_content, encoding="utf-8")
            typer.echo(f"Extracted {len(warnings)} warnings to: {output}")
        elif warnings:
            typer.echo(f"Found {len(warnings)} warnings:")
            for w in warnings:
                typer.echo(w)
        else:
            typer.echo("# No warnings found (0 warnings)")

        logger.info(f"Completed: extract_warnings {input}")
        raise typer.Exit(code=ExitCode.SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Pipeline error: {e}", err=True)
        logger.error(f"Failed: extract_warnings {input} - {e}")
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)
