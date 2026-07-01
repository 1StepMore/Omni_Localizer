"""Tests for the `ol verify-terms` CLI subcommand."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

if sys.platform == "win32":
    import unittest.mock
    sys.modules.setdefault("fcntl", unittest.mock.MagicMock())

from ol_cli import app

runner = CliRunner()


@pytest.fixture
def sample_files(tmp_path):
    """Create sample source, target, and glossary files."""
    src = tmp_path / "source.md"
    src.write_text("Click the API endpoint.", encoding="utf-8")
    tgt = tmp_path / "target.md"
    tgt.write_text("点击 API 端点。", encoding="utf-8")
    glossary = tmp_path / "glossary.json"
    glossary.write_text(json.dumps({
        "API": {
            "translation": "API 端点",
            "variants": {},
            "confidence": 0.95,
        }
    }), encoding="utf-8")
    return src, tgt, glossary


class TestVerifyTermsCLI:
    """Test the ol verify-terms CLI command."""

    def test_cli_runs_with_minimum_args(self, sample_files):
        src, tgt, _ = sample_files
        result = runner.invoke(app, [
            "verify-terms",
            "--source", str(src),
            "--target", str(tgt),
        ])
        # Should exit 0 even without glossary (consistency check only)
        assert result.exit_code == 0
        # Should print a JSON report to stdout
        output = json.loads(result.output)
        assert "verified" in output
        assert "mismatches" in output
        assert "inconsistencies" in output

    def test_cli_with_glossary(self, sample_files):
        src, tgt, glossary = sample_files
        result = runner.invoke(app, [
            "verify-terms",
            "--source", str(src),
            "--target", str(tgt),
            "--glossary", str(glossary),
        ])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["total_terms_checked"] == 1
        assert len(output["verified"]) == 1

    def test_cli_with_output_file(self, sample_files, tmp_path):
        src, tgt, glossary = sample_files
        output_path = tmp_path / "report.json"
        result = runner.invoke(app, [
            "verify-terms",
            "--source", str(src),
            "--target", str(tgt),
            "--glossary", str(glossary),
            "--output", str(output_path),
        ])
        assert result.exit_code == 0
        # File should be created and contain the report
        assert output_path.exists()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert "verified" in report

    def test_cli_with_confidence_threshold(self, sample_files):
        src, tgt, glossary = sample_files
        result = runner.invoke(app, [
            "verify-terms",
            "--source", str(src),
            "--target", str(tgt),
            "--glossary", str(glossary),
            "--confidence-threshold", "0.5",
        ])
        assert result.exit_code == 0
        output = json.loads(result.output)
        # Lower threshold should still verify the term (confidence is 0.95 > 0.5)
        assert len(output["verified"]) == 1

    def test_cli_missing_source_file(self, tmp_path):
        result = runner.invoke(app, [
            "verify-terms",
            "--source", str(tmp_path / "nonexistent.md"),
            "--target", str(tmp_path / "tgt.md"),
        ])
        # Should exit with non-zero (CLI usage error)
        assert result.exit_code != 0

    def test_cli_help(self):
        result = runner.invoke(app, ["verify-terms", "--help"])
        assert result.exit_code == 0
        assert "verify-terms" in result.output
        assert "--source" in result.output
        assert "--target" in result.output


class TestVerifyTermsCLIMismatch:
    """Test mismatch detection via CLI."""

    def test_cli_detects_mismatch(self, tmp_path):
        src = tmp_path / "source.md"
        src.write_text("Click the API endpoint.", encoding="utf-8")
        tgt = tmp_path / "target.md"
        tgt.write_text("点击 应用程序接口。", encoding="utf-8")  # wrong translation
        glossary = tmp_path / "glossary.json"
        glossary.write_text(json.dumps({
            "API": {
                "translation": "API 端点",
                "variants": {},
                "confidence": 0.95,
            }
        }), encoding="utf-8")
        result = runner.invoke(app, [
            "verify-terms",
            "--source", str(src),
            "--target", str(tgt),
            "--glossary", str(glossary),
        ])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output["mismatches"]) == 1
        assert output["mismatches"][0]["term"] == "API"
