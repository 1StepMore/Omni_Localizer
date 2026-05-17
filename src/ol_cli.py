"""Omni-Localizer CLI - Typer-based command line interface."""
import sys
import asyncio
from pathlib import Path
from typing import Optional

import typer

from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_xliff.pipeline import XLIFFRepairPipeline

__version__ = "0.1.0"

app = typer.Typer(
    name="ol",
    help="Omni-Localizer: AI-native localization pipeline with automated quality control.",
    add_completion=False,
)


class ExitCode:
    SUCCESS = 0
    PIPELINE_ERROR = 1
    CLI_USAGE_ERROR = 2


def validate_input_file(path: str) -> Path:
    file_path = Path(path)
    if not file_path.exists():
        raise typer.BadParameter(f"Input file not found: {path}")
    if not file_path.is_file():
        raise typer.BadParameter(f"Input is not a file: {path}")
    return file_path


def ensure_output_dir(path: str) -> Path:
    output_path = Path(path)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


async def _translate_md_async(
    input_path: Path,
    output_path: Path,
    config_path: Optional[str],
    src_lang: str,
    tgt_lang: str,
) -> str:
    from ol_pool.router import ModelPool

    pool = ModelPool(config_path) if config_path else None
    original_text = input_path.read_text(encoding="utf-8")

    shielded, shield_map = shield_markdown(original_text)

    if pool:
        translated = await pool.translate(shielded, src_lang, tgt_lang)
    else:
        from ol_config.loader import load_config
        cfg = load_config(config_path)
        src_lang = src_lang or cfg.source_lang
        tgt_lang = tgt_lang or cfg.target_lang
        pool = ModelPool(config_path)
        translated = await pool.translate(shielded, src_lang, tgt_lang)

    if shield_map:
        translated = unshield_markdown(translated, shield_map)

    repaired = MDRepairPipeline().repair(translated, original_text, shield_map)

    output_file = output_path / input_path.name
    output_file.write_text(repaired, encoding="utf-8")

    return str(output_file)


@app.command()
def translate_md(
    input: str = typer.Argument(..., help="Input markdown file path"),
    output_dir: str = typer.Option("--output-dir", "-o", help="Output directory"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
    source_lang: Optional[str] = typer.Option(None, "--source-lang", "-s", help="Source language (overrides config)"),
    target_lang: Optional[str] = typer.Option(None, "--target-lang", "-t", help="Target language (overrides config)"),
) -> int:
    try:
        input_path = validate_input_file(input)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    if not output_dir:
        typer.echo("Error: --output-dir is required", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        output_path = ensure_output_dir(output_dir)
    except Exception as e:
        typer.echo(f"Error: Cannot create output directory: {e}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        src = source_lang or "en"
        tgt = target_lang or "zh"

        if config:
            from ol_config.loader import load_config
            cfg = load_config(config)
            src = src or cfg.source_lang
            tgt = tgt or cfg.target_lang
            typer.echo(f"Using config: {cfg.project_id} ({src} -> {tgt})")
        else:
            src = src or "en"
            tgt = tgt or "zh"

        output_file = asyncio.run(
            _translate_md_async(input_path, output_path, config, src, tgt)
        )

        typer.echo(f"Translated: {input_path.name} -> {output_file} ({src} -> {tgt})")
        raise typer.Exit(code=ExitCode.SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Pipeline error: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)


@app.command()
def translate_xliff(
    input: str = typer.Argument(..., help="Input XLIFF file path"),
    output_dir: str = typer.Option("--output-dir", "-o", help="Output directory"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
    source_lang: Optional[str] = typer.Option(None, "--source-lang", "-s", help="Source language (overrides config)"),
    target_lang: Optional[str] = typer.Option(None, "--target-lang", "-t", help="Target language (overrides config)"),
) -> int:
    try:
        input_path = validate_input_file(input)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    if not output_dir:
        typer.echo("Error: --output-dir is required", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        output_path = ensure_output_dir(output_dir)
    except Exception as e:
        typer.echo(f"Error: Cannot create output directory: {e}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        src_lang = source_lang
        tgt_lang = target_lang
        if config:
            from ol_config.loader import load_config
            cfg = load_config(config)
            src_lang = src_lang or cfg.source_lang
            tgt_lang = tgt_lang or cfg.target_lang
            typer.echo(f"Using config: {cfg.project_id} ({src_lang} -> {tgt_lang})")
        else:
            src_lang = src_lang or "en"
            tgt_lang = tgt_lang or "zh"

        original_text = input_path.read_text(encoding="utf-8")
        pipeline = XLIFFRepairPipeline()
        repaired = pipeline.repair(original_text, original_text, {})

        output_file = output_path / input_path.name
        output_file.write_text(repaired, encoding="utf-8")

        typer.echo(f"Translated: {input_path.name} -> {output_file} ({src_lang} -> {tgt_lang})")
        raise typer.Exit(code=ExitCode.SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Pipeline error: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)


@app.command()
def extract_warnings(
    input: str = typer.Argument(..., help="Input file path (MD or XLIFF)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
) -> int:
    try:
        input_path = validate_input_file(input)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        content = input_path.read_text(encoding="utf-8")
        warnings = []
        import re

        md_warn_pattern = re.compile(r'<!--\s*OL_WARN:\s*([^>]+)\s*-->')
        for match in md_warn_pattern.finditer(content):
            warnings.append(f"MD: {match.group(0)}")

        xliff_warn_pattern = re.compile(r'<note\s+from="OL"[^>]*>([^<]+)</note>')
        for match in xliff_warn_pattern.finditer(content):
            warnings.append(f"XLIFF: {match.group(0)}")

        plain_warn_pattern = re.compile(r'OL_WARN:\s*(\w+)')
        for match in plain_warn_pattern.finditer(content):
            warnings.append(f"Plain: OL_WARN: {match.group(1)}")

        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_content = "\n".join(warnings) if warnings else "# No warnings found"
            output_path.write_text(output_content, encoding="utf-8")
            typer.echo(f"Warnings extracted to: {output}")
        else:
            if warnings:
                for w in warnings:
                    typer.echo(w)
            else:
                typer.echo("# No warnings found")

        raise typer.Exit(code=ExitCode.SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Pipeline error: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)


@app.callback(invoke_without_command=True)
def main(
    version: Optional[bool] = typer.Option(None, "--version", is_eager=True, help="Show version"),
) -> None:
    if version:
        typer.echo(f"ol version {__version__}")
        raise typer.Exit()


def main_entry() -> int:
    app()
    return ExitCode.SUCCESS


if __name__ == "__main__":
    sys.exit(main_entry())