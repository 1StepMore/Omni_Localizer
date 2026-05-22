"""Report generation module for Omni-Localizer Phase 4.

This module generates HTML and CSV reports with:
- Bidirectional traceability (source line → target line mapping)
- Model cost dashboard with token usage statistics
- OL_WARN summary with severity breakdown
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ol_core.dataclass import EvaluationResult


@dataclass
class WarningEntry:
    """Represents a warning entry in the report."""

    file_path: str
    line_number: int
    warning_type: str
    severity: str
    model: str
    cost: float
    source_text: str = ""
    target_text: str = ""
    reference: str = ""  # MD: Heading/paragraph, XLIFF: trans-unit id


@dataclass
class ModelCostEntry:
    """Represents model usage and cost statistics."""

    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_per_1k_tokens: float = 0.0
    total_cost: float = 0.0


@dataclass
class ReportData:
    """Container for report generation data."""

    job_id: str
    generated_at: datetime
    warnings: list[WarningEntry] = field(default_factory=list)
    model_costs: dict[str, ModelCostEntry] = field(default_factory=dict)
    total_warnings: int = 0
    severity_breakdown: dict[str, int] = field(default_factory=dict)

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def total_cost(self) -> float:
        return sum(mc.total_cost for mc in self.model_costs.values())

    @property
    def total_tokens(self) -> int:
        return sum(mc.total_tokens for mc in self.model_costs.values())


def _get_template_dir() -> Path:
    """Get the templates directory path."""
    return Path(__file__).parent / "templates"


def _ensure_reports_dir(output_dir: str) -> Path:
    """Ensure reports directory exists."""
    reports_dir = Path(output_dir) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def _get_html_report_path(reports_dir: Path, job_id: str) -> Path:
    """Get the HTML report file path."""
    return reports_dir / f"{job_id}_report.html"


def _get_csv_report_path(reports_dir: Path, job_id: str) -> Path:
    """Get the CSV report file path."""
    return reports_dir / f"{job_id}_report.csv"


def _init_jinja_env() -> Environment:
    """Initialize Jinja2 environment with template loader."""
    template_dir = _get_template_dir()
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env


def _serialize_evaluation_result(result: EvaluationResult) -> dict:
    """Serialize an EvaluationResult to a dictionary."""
    return {
        "unit_id": result.unit_id,
        "scorer_scores": result.scorer_scores,
        "judge_scores": result.judge_scores,
        "format_preserved": result.format_preserved,
        "format_errors": result.format_errors,
        "warnings": result.warnings,
        "passed_scorer": result.passed_scorer,
        "judge_overall_score": result.judge_overall_score,
    }


def _create_report_data(
    job_id: str,
    evaluation_results: list[EvaluationResult] | None = None,
    warnings: list[WarningEntry] | None = None,
    model_costs: dict[str, ModelCostEntry] | None = None,
) -> ReportData:
    report_data = ReportData(
        job_id=job_id,
        generated_at=datetime.now(),
    )

    if warnings is not None:
        report_data.warnings = warnings
    else:
        report_data.warnings = []

    if model_costs is not None:
        report_data.model_costs = model_costs
    else:
        report_data.model_costs = {}

    severity_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for warning in report_data.warnings:
        severity = warning.severity.lower()
        if severity in severity_counts:
            severity_counts[severity] += 1
        else:
            severity_counts[severity] = 1

    report_data.severity_breakdown = severity_counts
    report_data.total_warnings = len(report_data.warnings)

    return report_data


def generate_report(
    output_dir: str,
    job_id: str,
    *,
    force: bool = False,
    evaluation_results: list[EvaluationResult] | None = None,
    warnings: list[WarningEntry] | None = None,
    model_costs: dict[str, ModelCostEntry] | None = None,
) -> dict[str, str]:
    """Generate HTML and CSV reports.

    Args:
        output_dir: Output directory path
        job_id: Job identifier used for report filenames
        force: If True, overwrite existing reports; otherwise skip
        evaluation_results: Optional list of EvaluationResult objects
        warnings: Optional list of WarningEntry objects for the report
        model_costs: Optional dict mapping model names to ModelCostEntry objects

    Returns:
        Dict with keys "html" and "csv" pointing to generated file paths

    Raises:
        FileExistsError: If report exists and force=False

    Example:
        >>> warnings = [
        ...     WarningEntry(
        ...         file_path="test.md",
        ...         line_number=10,
        ...         warning_type="OL_WARN",
        ...         severity="high",
        ...         model="gpt-4o",
        ...         cost=0.05,
        ...         source_text="Hello",
        ...         target_text="Bonjour",
        ...         reference="Heading 2.1"
        ...     )
        ... ]
        >>> model_costs = {
        ...     "gpt-4o": ModelCostEntry(
        ...         model_name="gpt-4o",
        ...         prompt_tokens=100,
        ...         completion_tokens=50,
        ...         total_tokens=150,
        ...         cost_per_1k_tokens=0.01,
        ...         total_cost=0.0015
        ...     )
        ... }
        >>> result = generate_report("/tmp/out", "job123", warnings=warnings, model_costs=model_costs)
        >>> print(result)
        {'html': '/tmp/out/reports/job123_report.html', 'csv': '/tmp/out/reports/job123_report.csv'}

    """
    reports_dir = _ensure_reports_dir(output_dir)
    html_path = _get_html_report_path(reports_dir, job_id)
    csv_path = _get_csv_report_path(reports_dir, job_id)

    # Check if reports exist and force flag
    if not force:
        if html_path.exists():
            raise FileExistsError(f"HTML report already exists: {html_path}")
        if csv_path.exists():
            raise FileExistsError(f"CSV report already exists: {csv_path}")

    # Create report data
    report_data = _create_report_data(job_id, evaluation_results, warnings, model_costs)

    # Render HTML report
    env = _init_jinja_env()
    html_template = env.get_template("report.html.j2")
    html_content = html_template.render(report=report_data)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # Render CSV report
    csv_template = env.get_template("report.csv.j2")
    csv_content = csv_template.render(report=report_data)

    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(csv_content)

    return {
        "html": str(html_path),
        "csv": str(csv_path),
    }


def create_warning_entry(
    file_path: str,
    line_number: int,
    warning_type: str,
    severity: str,
    model: str,
    cost: float,
    source_text: str = "",
    target_text: str = "",
    reference: str = "",
) -> WarningEntry:
    """Create a WarningEntry with the given parameters.

    Args:
        file_path: Path to the source file
        line_number: Line number in source file
        warning_type: Type of warning (e.g., "OL_WARN", "Format_Error")
        severity: Severity level ("high", "medium", "low")
        model: Model name used for translation
        cost: Cost of the translation
        source_text: Original source text
        target_text: Translated target text
        reference: MD reference (Heading/paragraph) or XLIFF reference (trans-unit id)

    Returns:
        WarningEntry object

    """
    return WarningEntry(
        file_path=file_path,
        line_number=line_number,
        warning_type=warning_type,
        severity=severity,
        model=model,
        cost=cost,
        source_text=source_text,
        target_text=target_text,
        reference=reference,
    )


def create_model_cost_entry(
    model_name: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_per_1k_tokens: float = 0.0,
) -> ModelCostEntry:
    """Create a ModelCostEntry with the given parameters.

    Args:
        model_name: Name of the model
        prompt_tokens: Number of prompt tokens used
        completion_tokens: Number of completion tokens generated
        cost_per_1k_tokens: Cost per 1000 tokens

    Returns:
        ModelCostEntry object

    """
    total_tokens = prompt_tokens + completion_tokens
    total_cost = (total_tokens / 1000.0) * cost_per_1k_tokens

    return ModelCostEntry(
        model_name=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_per_1k_tokens=cost_per_1k_tokens,
        total_cost=total_cost,
    )
