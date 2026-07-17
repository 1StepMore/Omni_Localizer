"""ol calibrate-threshold — Run LQA threshold calibration.

Accepts reference scores and judge results as JSON files, runs
grid search, and recommends an optimal LQA threshold.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from ol_lqa.calibration import grid_search_calibrate
from ol_lqa.multi_judge import MultiJudgeResult

from ._shared import ExitCode

DIMENSIONS = ("adequacy", "fluency", "terminology", "format")


def calibrate_threshold(
    reference_scores: str = typer.Option(
        ..., "--reference-scores", help="JSON file with reference LLM scores"
    ),
    judge_results: str = typer.Option(
        ..., "--judge-results", help="JSON file with MultiJudgeResult data"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Run threshold calibration on judge results vs reference scores.

    Reads MultiJudgeResult data and reference scores from JSON files,
    runs grid search, and recommends an optimal LQA threshold.
    """
    # Validate input files
    rs_path = Path(reference_scores)
    if not rs_path.exists():
        raise typer.BadParameter(
            f"Reference scores file not found: {reference_scores}"
        )

    jr_path = Path(judge_results)
    if not jr_path.exists():
        raise typer.BadParameter(
            f"Judge results file not found: {judge_results}"
        )

    # Parse JSON files
    try:
        with open(rs_path) as f:
            rs_data = json.load(f)
    except json.JSONDecodeError as e:
        raise typer.BadParameter(
            f"Invalid JSON in reference scores file: {e}"
        )

    try:
        with open(jr_path) as f:
            jr_data = json.load(f)
    except json.JSONDecodeError as e:
        raise typer.BadParameter(
            f"Invalid JSON in judge results file: {e}"
        )

    # Reference scores: extract dimension-score pairs from each dict
    reference_scores_parsed: list[dict[str, int]] = []
    for item in rs_data:
        if not isinstance(item, dict):
            raise typer.BadParameter(
                "Reference scores must be a list of dicts with "
                "keys: adequacy, fluency, terminology, format"
            )
        parsed = {}
        for dim in DIMENSIONS:
            val = item.get(dim)
            if val is None:
                raise typer.BadParameter(
                    f"Reference score entry missing dimension '{dim}'"
                )
            parsed[dim] = int(val) if not isinstance(val, int) else val
        reference_scores_parsed.append(parsed)

    # MultiJudgeResult: extract dimension scores + dimension_agreement
    judge_results_parsed: list[MultiJudgeResult] = []
    for item in jr_data:
        if not isinstance(item, dict):
            raise typer.BadParameter(
                "Judge results must be a list of dicts"
            )
        adequacy = item.get("adequacy", 0)
        fluency = item.get("fluency", 0)
        terminology = item.get("terminology", 0)
        format_val = item.get("format", 0)
        dim_agreement = item.get("dimension_agreement", {})
        judge_results_parsed.append(MultiJudgeResult(
            adequacy=int(adequacy),
            fluency=int(fluency),
            terminology=int(terminology),
            format=int(format_val),
            dimension_agreement=dim_agreement,
        ))

    # Validate length match
    if len(judge_results_parsed) != len(reference_scores_parsed):
        typer.echo(
            f"Warning: {len(judge_results_parsed)} judge results vs "
            f"{len(reference_scores_parsed)} reference scores",
            err=True,
        )

    # Run grid search
    result = grid_search_calibrate(judge_results_parsed, reference_scores_parsed)

    # Output
    if json_output:
        typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        typer.echo("Calibration Results")
        typer.echo("=" * 60)
        typer.echo(f"  Reference scores file: {reference_scores}")
        typer.echo(f"  Judge results file:    {judge_results}")
        typer.echo(f"  Documents evaluated:   {len(judge_results_parsed)}")
        if result.best_result:
            typer.echo(
                f"  Recommended threshold: {result.best_result.threshold_0_10:.1f} "
                f"(0-10 scale) / {result.best_result.threshold_1_5:.1f} (1-5 scale)"
            )
            typer.echo(
                f"  Spearman correlation:  {result.best_result.spearman:.3f}"
            )
            typer.echo(
                f"  Inter-judge agreement: {result.best_result.agreement:.3f}"
            )
        else:
            typer.echo("  No passing threshold found in grid search.")
        typer.echo("")
        typer.echo("Per-threshold sweep:")
        typer.echo(
            "  Threshold (1-5) | Threshold (0-10) | Spearman | Agreement | Pass"
        )
        typer.echo("  " + "-" * 65)
        for r in result.results:
            typer.echo(
                f"  {r.threshold_1_5:>13.1f} | "
                f"{r.threshold_0_10:>16.1f} | "
                f"{r.spearman:>7.3f} | "
                f"{r.agreement:>8.3f} | "
                f"{'PASS' if r.passed else 'FAIL'}"
            )

    raise typer.Exit(code=ExitCode.SUCCESS)
