"""Omni-Localizer CLI - Typer-based command line interface."""
import sys
from pathlib import Path
from typing import Optional

import typer

from ol_md.pipeline import MDRepairPipeline
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
    """Validate that input file exists."""
    file_path = Path(path)
    if not file_path.exists():
        raise typer.BadParameter(f"Input file not found: {path}")
    if not file_path.is_file():
        raise typer.BadParameter(f"Input is not a file: {path}")
    return file_path


def ensure_output_dir(path: str) -> Path:
    """Ensure output directory exists, create if missing."""
    output_path = Path(path)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


@app.command()
def translate_md(
    input: str = typer.Argument(..., help="Input markdown file path"),
    output_dir: str = typer.Option("--output-dir", "-o", help="Output directory"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
) -> int:
    """Translate markdown file through MD repair pipeline."""
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
        # Read input file
        original_text = input_path.read_text(encoding="utf-8")

        # Initialize pipeline
        pipeline = MDRepairPipeline()

        # Run repair pipeline (pass-through since CLI doesn't do actual translation)
        repaired = pipeline.repair(original_text, original_text, {})

        # Write output
        output_file = output_path / input_path.name
        output_file.write_text(repaired, encoding="utf-8")

        typer.echo(f"Translated: {input_path.name} -> {output_file}")
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
) -> int:
    """Translate XLIFF file through XLIFF repair pipeline."""
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
        # Read input file
        original_text = input_path.read_text(encoding="utf-8")

        # Initialize pipeline
        pipeline = XLIFFRepairPipeline()

        # Run repair pipeline (pass-through since CLI doesn't do actual translation)
        repaired = pipeline.repair(original_text, original_text, {})

        # Write output
        output_file = output_path / input_path.name
        output_file.write_text(repaired, encoding="utf-8")

        typer.echo(f"Translated: {input_path.name} -> {output_file}")
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
    """Extract OL_WARN warnings from input file into review file."""
    try:
        input_path = validate_input_file(input)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        content = input_path.read_text(encoding="utf-8")

        # Extract warnings based on patterns
        warnings = []

        # MD pattern: <!-- OL_WARN: ... -->
        import re

        md_warn_pattern = re.compile(r'<!--\s*OL_WARN:\s*([^>]+)\s*-->')
        for match in md_warn_pattern.finditer(content):
            warnings.append(f"MD: {match.group(0)}")

        # XLIFF pattern: <note from="OL">...</note>
        xliff_warn_pattern = re.compile(r'<note\s+from="OL"[^>]*>([^<]+)</note>')
        for match in xliff_warn_pattern.finditer(content):
            warnings.append(f"XLIFF: {match.group(0)}")

        # Plain pattern: OL_WARN:
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
    """Omni-Localizer CLI - Batch-mode localization pipeline."""
    if version:
        typer.echo(f"ol version {__version__}")
        raise typer.Exit()


def main_entry() -> int:
    """Entry point for the CLI."""
    app()
    return ExitCode.SUCCESS


if __name__ == "__main__":
    sys.exit(main_entry())