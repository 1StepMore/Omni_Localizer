"""ol generate-report — Generate HTML and CSV quality reports.

Companion CLI to the OL MCP generate_report tool. Reads warnings
and model-costs from JSON files (or both from stdin), generates the
report in the specified output directory, and prints the report paths.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from cli._shared import ExitCode


def generate_report(
    output_dir: str = typer.Argument(..., help="Directory to write report.html and report.csv into"),
    job_id: str = typer.Argument(..., help="Job identifier (used in report filenames)"),
    warnings: Optional[str] = typer.Option(
        None, "--warnings", "-w", help="Path to JSON file with list of warning entries"
    ),
    model_costs: Optional[str] = typer.Option(
        None, "--model-costs", "-m", help="Path to JSON file with list of model-cost entries"
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing report files"),
) -> None:
    """Generate HTML and CSV quality reports from translation warnings and model costs."""
    try:
        from ol_lqa.report import (
            ModelCostEntry,
            WarningEntry,
            generate_report as _gen_report,
        )
    except ImportError as e:
        typer.echo(f"Error: ol_lqa.report not importable: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    # Read warnings
    if warnings:
        warnings_list = json.loads(Path(warnings).read_text(encoding="utf-8"))
    else:
        warnings_list = []
    warnings_objs = [WarningEntry(**w) for w in warnings_list]

    # Read model costs
    if model_costs:
        model_costs_list = json.loads(Path(model_costs).read_text(encoding="utf-8"))
    else:
        model_costs_list = []
    model_costs_dict = {}
    for mc in model_costs_list:
        entry = ModelCostEntry(
            model_name=mc["model_name"],
            prompt_tokens=mc.get("prompt_tokens", 0),
            completion_tokens=mc.get("completion_tokens", 0),
            cost_per_1k_tokens=mc.get("cost_per_1k_tokens", 0.0),
        )
        model_costs_dict[mc["model_name"]] = entry

    try:
        result = _gen_report(
            output_dir=output_dir,
            job_id=job_id,
            force=force,
            warnings=warnings_objs,
            model_costs=model_costs_dict,
        )
    except FileExistsError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)
    except Exception as e:
        typer.echo(f"Error: failed to generate report: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    typer.echo(f"Wrote report.html: {result.get('html')}")
    typer.echo(f"Wrote report.csv: {result.get('csv')}")
    raise typer.Exit(code=ExitCode.SUCCESS)
