"""Unit tests for ol_lqa report module."""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mock fcntl for Windows compatibility in tests
if sys.platform == 'win32':
    import unittest.mock
    sys.modules['fcntl'] = unittest.mock.MagicMock()

from ol_lqa.report import (
    WarningEntry,
    ModelCostEntry,
    ReportData,
    generate_report,
    create_warning_entry,
    create_model_cost_entry,
)


class TestReportModuleImport:
    """Test report module import and basic structure."""

    def test_report_module_imports(self):
        """Test that all expected classes and functions are importable."""
        from ol_lqa.report import WarningEntry, ModelCostEntry, ReportData
        from ol_lqa.report import generate_report, create_warning_entry, create_model_cost_entry
        assert WarningEntry is not None
        assert ModelCostEntry is not None
        assert ReportData is not None

    def test_warning_entry_dataclass(self):
        """Test WarningEntry dataclass creation."""
        entry = WarningEntry(
            file_path="test.md",
            line_number=10,
            warning_type="OL_WARN",
            severity="high",
            model="gpt-4o",
            cost=0.05,
            source_text="Hello",
            target_text="Bonjour",
            reference="Heading 1"
        )
        assert entry.file_path == "test.md"
        assert entry.line_number == 10
        assert entry.warning_type == "OL_WARN"
        assert entry.severity == "high"
        assert entry.model == "gpt-4o"
        assert entry.cost == 0.05

    def test_model_cost_entry_dataclass(self):
        """Test ModelCostEntry dataclass creation."""
        entry = ModelCostEntry(
            model_name="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_per_1k_tokens=0.01,
            total_cost=0.0015
        )
        assert entry.model_name == "gpt-4o"
        assert entry.prompt_tokens == 100
        assert entry.completion_tokens == 50
        assert entry.total_tokens == 150

    def test_report_data_dataclass(self):
        """Test ReportData dataclass creation."""
        report = ReportData(
            job_id="test_job",
            generated_at=datetime.now(),
            warnings=[],
            model_costs={},
            total_warnings=0,
            severity_breakdown={}
        )
        assert report.job_id == "test_job"
        assert report.has_warnings is False

    def test_report_data_has_warnings_property(self):
        """Test ReportData has_warnings property."""
        warnings = [WarningEntry(
            file_path="test.md", line_number=1,
            warning_type="OL_WARN", severity="high",
            model="gpt-4o", cost=0.01
        )]
        report = ReportData(
            job_id="test_job",
            generated_at=datetime.now(),
            warnings=warnings
        )
        assert report.has_warnings is True

    def test_report_data_total_cost_property(self):
        """Test ReportData total_cost property."""
        model_costs = {
            "gpt-4o": ModelCostEntry(
                model_name="gpt-4o",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_per_1k_tokens=0.01,
                total_cost=0.0015
            )
        }
        report = ReportData(
            job_id="test_job",
            generated_at=datetime.now(),
            model_costs=model_costs
        )
        assert report.total_cost == 0.0015

    def test_report_data_total_tokens_property(self):
        """Test ReportData total_tokens property."""
        model_costs = {
            "gpt-4o": ModelCostEntry(
                model_name="gpt-4o",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_per_1k_tokens=0.01,
                total_cost=0.0015
            )
        }
        report = ReportData(
            job_id="test_job",
            generated_at=datetime.now(),
            model_costs=model_costs
        )
        assert report.total_tokens == 150


class TestCreateFunctions:
    """Test helper functions for creating entries."""

    def test_create_warning_entry(self):
        """Test create_warning_entry function."""
        entry = create_warning_entry(
            file_path="test.md",
            line_number=10,
            warning_type="OL_WARN",
            severity="high",
            model="gpt-4o",
            cost=0.05,
            source_text="Hello",
            target_text="Bonjour",
            reference="Heading 1"
        )
        assert isinstance(entry, WarningEntry)
        assert entry.file_path == "test.md"
        assert entry.line_number == 10

    def test_create_model_cost_entry(self):
        """Test create_model_cost_entry function."""
        entry = create_model_cost_entry(
            model_name="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_per_1k_tokens=0.01
        )
        assert isinstance(entry, ModelCostEntry)
        assert entry.model_name == "gpt-4o"
        assert entry.total_tokens == 150
        assert entry.total_cost == 0.0015  # (150/1000) * 0.01


class TestHTMLReportGeneration:
    """Test HTML report generation with mock data."""

    @pytest.fixture
    def temp_output_dir(self):
        """Create temporary output directory."""
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_warnings(self):
        """Create mock warning entries."""
        return [
            WarningEntry(
                file_path="docs/guide.md",
                line_number=42,
                warning_type="OL_WARN",
                severity="high",
                model="gpt-4o",
                cost=0.023,
                source_text="Click the submit button",
                target_text="Cliquez sur le bouton soumettre",
                reference="Section 3.2"
            ),
            WarningEntry(
                file_path="docs/api.md",
                line_number=15,
                warning_type="OL_WARN",
                severity="medium",
                model="gpt-4o-mini",
                cost=0.012,
                source_text="API response format",
                target_text="Format de reponse API",
                reference="trans-unit-42"
            ),
        ]

    @pytest.fixture
    def mock_model_costs(self):
        """Create mock model cost entries."""
        return {
            "gpt-4o": ModelCostEntry(
                model_name="gpt-4o",
                prompt_tokens=5000,
                completion_tokens=2500,
                total_tokens=7500,
                cost_per_1k_tokens=0.015,
                total_cost=0.1125
            ),
            "gpt-4o-mini": ModelCostEntry(
                model_name="gpt-4o-mini",
                prompt_tokens=3000,
                completion_tokens=1500,
                total_tokens=4500,
                cost_per_1k_tokens=0.003,
                total_cost=0.0135
            ),
        }

    def test_html_report_creation(self, temp_output_dir, mock_warnings, mock_model_costs):
        """Test HTML report is created correctly."""
        result = generate_report(
            temp_output_dir,
            "test_job_001",
            warnings=mock_warnings,
            model_costs=mock_model_costs
        )

        assert "html" in result
        html_path = Path(result["html"])
        assert html_path.exists()
        assert html_path.name == "test_job_001_report.html"

    def test_html_report_contains_warnings(self, temp_output_dir, mock_warnings, mock_model_costs):
        """Test HTML report contains warning data."""
        result = generate_report(
            temp_output_dir,
            "test_job_002",
            warnings=mock_warnings,
            model_costs=mock_model_costs
        )

        html_content = Path(result["html"]).read_text(encoding="utf-8")
        assert "OL_WARN" in html_content
        assert "docs/guide.md" in html_content
        assert "42" in html_content  # line number

    def test_html_report_contains_model_costs(self, temp_output_dir, mock_warnings, mock_model_costs):
        """Test HTML report contains model cost data."""
        result = generate_report(
            temp_output_dir,
            "test_job_003",
            warnings=mock_warnings,
            model_costs=mock_model_costs
        )

        html_content = Path(result["html"]).read_text(encoding="utf-8")
        assert "gpt-4o" in html_content
        assert "7500" in html_content  # total tokens


class TestCSVReportGeneration:
    """Test CSV report generation with mock data."""

    @pytest.fixture
    def temp_output_dir(self):
        """Create temporary output directory."""
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_warnings(self):
        """Create mock warning entries for CSV tests."""
        return [
            WarningEntry(
                file_path="src/app.md",
                line_number=100,
                warning_type="Format_Error",
                severity="low",
                model="gpt-4o",
                cost=0.008,
                source_text="Original text",
                target_text="Texte cible",
                reference="Paragraph 5"
            ),
        ]

    @pytest.fixture
    def mock_model_costs(self):
        """Create mock model costs for CSV tests."""
        return {
            "gpt-4o": ModelCostEntry(
                model_name="gpt-4o",
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500,
                cost_per_1k_tokens=0.015,
                total_cost=0.0225
            ),
        }

    def test_csv_report_creation(self, temp_output_dir, mock_warnings, mock_model_costs):
        """Test CSV report is created correctly."""
        result = generate_report(
            temp_output_dir,
            "csv_test_job",
            warnings=mock_warnings,
            model_costs=mock_model_costs
        )

        assert "csv" in result
        csv_path = Path(result["csv"])
        assert csv_path.exists()
        assert csv_path.name == "csv_test_job_report.csv"

    def test_csv_report_content_format(self, temp_output_dir, mock_warnings, mock_model_costs):
        """Test CSV report has correct format."""
        result = generate_report(
            temp_output_dir,
            "csv_format_test",
            warnings=mock_warnings,
            model_costs=mock_model_costs
        )

        csv_content = Path(result["csv"]).read_text(encoding="utf-8")
        lines = csv_content.strip().split("\n")
        # Header line
        assert "file" in lines[0]
        assert "warning_type" in lines[0]
        # Data line - template has blank line after header
        assert "src/app.md" in lines[2]


class TestTemplateRendering:
    """Test template rendering with various data scenarios."""

    @pytest.fixture
    def temp_output_dir(self):
        """Create temporary output directory."""
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_template_renders_with_empty_warnings(self, temp_output_dir):
        """Test templates render correctly with no warnings."""
        result = generate_report(
            temp_output_dir,
            "empty_warnings_job",
            warnings=[],
            model_costs={}
        )

        html_content = Path(result["html"]).read_text(encoding="utf-8")
        assert "No warnings" in html_content or "empty-state" in html_content

    def test_template_renders_with_empty_model_costs(self, temp_output_dir):
        """Test templates render correctly with no model costs."""
        result = generate_report(
            temp_output_dir,
            "empty_costs_job",
            warnings=[
                WarningEntry(
                    file_path="test.md",
                    line_number=1,
                    warning_type="OL_WARN",
                    severity="high",
                    model="gpt-4o",
                    cost=0.01
                )
            ],
            model_costs={}
        )

        html_content = Path(result["html"]).read_text(encoding="utf-8")
        assert "No model cost data" in html_content or "empty-state" in html_content


class TestBidirectionalTraceability:
    """Test report contains bidirectional traceability."""

    @pytest.fixture
    def temp_output_dir(self):
        """Create temporary output directory."""
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_warning_entry_contains_source_and_target(self):
        """Test WarningEntry stores source and target text for traceability."""
        entry = WarningEntry(
            file_path="test.md",
            line_number=10,
            warning_type="OL_WARN",
            severity="high",
            model="gpt-4o",
            cost=0.05,
            source_text="Source text here",
            target_text="Target text here",
            reference="Heading 2.1"
        )
        assert entry.source_text == "Source text here"
        assert entry.target_text == "Target text here"
        assert entry.reference == "Heading 2.1"

    def test_report_contains_bidirectional_traceability_data(self, temp_output_dir):
        """Test generated report contains source-target mapping."""
        warnings = [
            WarningEntry(
                file_path="docs/config.md",
                line_number=50,
                warning_type="OL_WARN",
                severity="high",
                model="gpt-4o",
                cost=0.035,
                source_text="configuration setting",
                target_text="parametrage",
                reference="Section 4.1"
            ),
        ]

        result = generate_report(
            temp_output_dir,
            "traceability_test",
            warnings=warnings,
            model_costs={}
        )

        html_content = Path(result["html"]).read_text(encoding="utf-8")
        assert "configuration setting" in html_content
        assert "parametrage" in html_content
        assert "Section 4.1" in html_content


class TestModelCostDashboard:
    """Test model cost dashboard data in reports."""

    @pytest.fixture
    def temp_output_dir(self):
        """Create temporary output directory."""
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_model_cost_calculation(self):
        """Test ModelCostEntry calculates total correctly."""
        entry = create_model_cost_entry(
            model_name="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_per_1k_tokens=0.02
        )
        assert entry.total_tokens == 1500
        assert entry.total_cost == 0.03  # 1.5 * 0.02

    def test_report_aggregates_model_costs(self, temp_output_dir):
        """Test report correctly aggregates multiple model costs."""
        model_costs = {
            "gpt-4o": ModelCostEntry(
                model_name="gpt-4o",
                prompt_tokens=2000,
                completion_tokens=1000,
                total_tokens=3000,
                cost_per_1k_tokens=0.015,
                total_cost=0.045
            ),
            "claude-3-opus": ModelCostEntry(
                model_name="claude-3-opus",
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500,
                cost_per_1k_tokens=0.05,
                total_cost=0.075
            ),
        }

        result = generate_report(
            temp_output_dir,
            "cost_aggregation_test",
            warnings=[],
            model_costs=model_costs
        )

        html_content = Path(result["html"]).read_text(encoding="utf-8")
        assert "gpt-4o" in html_content
        assert "claude-3-opus" in html_content

    def test_model_cost_dashboard_in_report(self, temp_output_dir):
        """Test model cost dashboard data is included in report."""
        model_costs = {
            "gpt-4o": ModelCostEntry(
                model_name="gpt-4o",
                prompt_tokens=500,
                completion_tokens=250,
                total_tokens=750,
                cost_per_1k_tokens=0.015,
                total_cost=0.01125
            ),
        }

        result = generate_report(
            temp_output_dir,
            "dashboard_test",
            warnings=[],
            model_costs=model_costs
        )

        html_content = Path(result["html"]).read_text(encoding="utf-8")
        assert "Model Cost Summary" in html_content or "Cost" in html_content
        assert "750" in html_content  # total tokens


class TestForceFlag:
    """Test --force flag for overwriting existing reports."""

    @pytest.fixture
    def temp_output_dir(self):
        """Create temporary output directory."""
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_force_flag_overwrites_existing_report(self, temp_output_dir):
        """Test force=True allows overwriting existing reports."""
        warnings = [WarningEntry(
            file_path="test.md", line_number=1,
            warning_type="OL_WARN", severity="high",
            model="gpt-4o", cost=0.01
        )]

        # Create first report
        result1 = generate_report(
            temp_output_dir,
            "force_test",
            warnings=warnings,
            model_costs={}
        )
        assert Path(result1["html"]).exists()

        # Overwrite with force=True
        new_warnings = [WarningEntry(
            file_path="new.md", line_number=2,
            warning_type="OL_WARN", severity="low",
            model="gpt-4o-mini", cost=0.005
        )]
        result2 = generate_report(
            temp_output_dir,
            "force_test",
            warnings=new_warnings,
            model_costs={},
            force=True
        )
        assert Path(result2["html"]).exists()

    def test_without_force_raises_on_existing(self, temp_output_dir):
        """Test force=False raises FileExistsError when report exists."""
        warnings = [WarningEntry(
            file_path="test.md", line_number=1,
            warning_type="OL_WARN", severity="high",
            model="gpt-4o", cost=0.01
        )]

        # Create first report
        generate_report(
            temp_output_dir,
            "exists_test",
            warnings=warnings,
            model_costs={}
        )

        # Try to create again without force
        with pytest.raises(FileExistsError):
            generate_report(
                temp_output_dir,
                "exists_test",
                warnings=warnings,
                model_costs={},
                force=False
            )

    def test_force_flag_allows_new_report(self, temp_output_dir):
        """Test force=True allows creating new report."""
        warnings = [WarningEntry(
            file_path="test.md", line_number=1,
            warning_type="OL_WARN", severity="high",
            model="gpt-4o", cost=0.01
        )]

        result = generate_report(
            temp_output_dir,
            "new_report_force",
            warnings=warnings,
            model_costs={},
            force=True
        )

        assert Path(result["html"]).exists()
        assert Path(result["csv"]).exists()