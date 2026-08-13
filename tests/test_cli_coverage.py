"""Tests for OL#44 §1 CLI integration: --report-coverage and --coverage-threshold."""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_GLOSSARY = FIXTURES_DIR / "glossary_爱上海尔.json"


class TestReportCoverageFlag:
    """The --report-coverage flag must be accepted by both translate-md and translate-xliff."""

    def test_translate_md_help_shows_report_coverage(self):
        """`ol translate-md --help` lists --report-coverage."""
        result = subprocess.run(
            [
                sys.executable, "-m", "ol_cli", "translate-md", "--help",
            ],
            capture_output=True, text=True,
            env={**os.environ, "OMNI_TEST_FAKE_LLM": "1", "PYTHONPATH": "src"},
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert "--report-coverage" in result.stdout

    def test_translate_md_help_shows_coverage_threshold(self):
        """`ol translate-md --help` lists --coverage-threshold."""
        result = subprocess.run(
            [
                sys.executable, "-m", "ol_cli", "translate-md", "--help",
            ],
            capture_output=True, text=True,
            env={**os.environ, "OMNI_TEST_FAKE_LLM": "1", "PYTHONPATH": "src"},
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert "--coverage-thres" in result.stdout

    def test_translate_xliff_help_shows_report_coverage(self):
        """`ol translate-xliff --help` lists --report-coverage."""
        result = subprocess.run(
            [
                sys.executable, "-m", "ol_cli", "translate-xliff", "--help",
            ],
            capture_output=True, text=True,
            env={**os.environ, "OMNI_TEST_FAKE_LLM": "1", "PYTHONPATH": "src"},
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert "--report-coverage" in result.stdout

    def test_translate_xliff_help_shows_coverage_threshold(self):
        """`ol translate-xliff --help` lists --coverage-threshold."""
        result = subprocess.run(
            [
                sys.executable, "-m", "ol_cli", "translate-xliff", "--help",
            ],
            capture_output=True, text=True,
            env={**os.environ, "OMNI_TEST_FAKE_LLM": "1", "PYTHONPATH": "src"},
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert "--coverage-thres" in result.stdout


class TestReportCoverageIntegration:
    """End-to-end test: --report-coverage with FAKE_LLM emits the report."""

    def test_translate_md_with_report_coverage_emits_report(self, tmp_path):
        """Running translate-md with --report-coverage prints the coverage report."""
        sample = tmp_path / "sample.md"
        sample.write_text(
            "# Test\n\n开利是全球领先的空调制造商。三翼鸟是海尔智家的品牌。\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [
                sys.executable, "-m", "ol_cli", "translate-md",
                str(sample),
                "-s", "zh", "-t", "en",
                "-o", str(out_dir),
                "--glossary", str(SAMPLE_GLOSSARY),
                "--report-coverage",
                "--no-cache",
            ],
            capture_output=True, text=True,
            env={**os.environ, "OMNI_TEST_FAKE_LLM": "1", "PYTHONPATH": "src"},
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0, (
            f"CLI failed: rc={result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        assert "Glossary Coverage Report" in result.stdout
        assert "Total terms:" in result.stdout
        assert "Match type breakdown:" in result.stdout

    def test_translate_md_with_report_coverage_no_glossary(self, tmp_path):
        """When --report-coverage is set but no glossary, message is shown."""
        sample = tmp_path / "sample.md"
        sample.write_text(
            "# Test\n\nHello world.\n", encoding="utf-8"
        )
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [
                sys.executable, "-m", "ol_cli", "translate-md",
                str(sample),
                "-s", "en", "-t", "zh",
                "-o", str(out_dir),
                "--report-coverage",
                "--no-cache",
            ],
            capture_output=True, text=True,
            env={**os.environ, "OMNI_TEST_FAKE_LLM": "1", "PYTHONPATH": "src"},
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0, (
            f"CLI failed: rc={result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        assert "no glossary provided" in result.stdout.lower()

    def test_translate_md_with_coverage_threshold_warning(self, tmp_path):
        """When coverage < threshold, a WARNING is emitted."""
        sample = tmp_path / "sample.md"
        sample.write_text(
            "# Test\n\nPlain text with no glossary terms.\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [
                sys.executable, "-m", "ol_cli", "translate-md",
                str(sample),
                "-s", "en", "-t", "zh",
                "-o", str(out_dir),
                "--glossary", str(SAMPLE_GLOSSARY),
                "--report-coverage",
                "--coverage-threshold", "50",
                "--no-cache",
            ],
            capture_output=True, text=True,
            env={**os.environ, "OMNI_TEST_FAKE_LLM": "1", "PYTHONPATH": "src"},
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert "WARNING" in result.stdout

    def test_translate_md_without_report_coverage_no_extra_output(self, tmp_path):
        """When --report-coverage is NOT set, no coverage report is emitted."""
        sample = tmp_path / "sample.md"
        sample.write_text(
            "# Test\n\nHello world.\n", encoding="utf-8"
        )
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [
                sys.executable, "-m", "ol_cli", "translate-md",
                str(sample),
                "-s", "en", "-t", "zh",
                "-o", str(out_dir),
                "--glossary", str(SAMPLE_GLOSSARY),
                "--no-cache",
            ],
            capture_output=True, text=True,
            env={**os.environ, "OMNI_TEST_FAKE_LLM": "1", "PYTHONPATH": "src"},
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert "Glossary Coverage Report" not in result.stdout
