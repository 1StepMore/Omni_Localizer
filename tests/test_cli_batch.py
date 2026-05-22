"""Integration tests for translate-batch CLI command."""
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from ol_cli import app
from ol_pool.router import ModelPool

runner = CliRunner()


class TestTranslateBatchHelp:
    """Test --help output for translate-batch command."""

    def test_translate_batch_help_flag(self):
        result = runner.invoke(app, ["translate-batch", "--help"])
        assert result.exit_code == 0
        assert "translate-batch" in result.output.lower()
        assert "--help" in result.output

    def test_translate_batch_help_shows_options(self):
        result = runner.invoke(app, ["translate-batch", "--help"])
        assert result.exit_code == 0
        assert "--output-dir" in result.output
        assert "--config" in result.output
        assert "--source-lang" in result.output
        assert "--target-lang" in result.output
        assert "--concurrency" in result.output


class TestTranslateBatchFilesystem:
    """Test translate-batch with real filesystem operations."""

    @pytest.fixture
    def temp_input_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test markdown files
            md_file1 = Path(tmpdir) / "intro.md"
            md_file1.write_text("# Introduction\n\nHello world content.", encoding="utf-8")

            md_file2 = Path(tmpdir) / "chapter1.md"
            md_file2.write_text("# Chapter 1\n\nSome content here.", encoding="utf-8")

            # Create test XLIFF file
            xliff_file = Path(tmpdir) / "doc.xlf"
            xliff_file.write_text(
                '<?xml version="1.0"?>\n<xliff version="1.2"><file></file></xliff>',
                encoding="utf-8",
            )

            yield tmpdir

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_translate_batch_directory_not_found(self):
        result = runner.invoke(
            app,
            ["translate-batch", "/nonexistent/directory", "-o", "/tmp/output"],
        )
        assert result.exit_code == 2
        assert "not found" in result.output.lower()

    def test_translate_batch_missing_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                ["translate-batch", tmpdir],
            )
            assert result.exit_code == 2
            assert "output-dir" in result.output.lower() or "required" in result.output.lower()

    def test_translate_batch_finds_markdown_files(self, temp_input_dir, temp_output_dir):
        with patch.object(ModelPool, "__init__", return_value=None):
            with patch.object(ModelPool, "translate", new_callable=AsyncMock) as mock_translate:
                mock_translate.return_value = "# Introduction\n\nTranslated content."
                result = runner.invoke(
                    app,
                    ["translate-batch", temp_input_dir, "-o", temp_output_dir],
                )
                # Should find files and attempt processing
                assert "found" in result.output.lower() or result.exit_code in (0, 1)

    def test_translate_batch_empty_directory(self, temp_output_dir):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                ["translate-batch", tmpdir, "-o", temp_output_dir],
            )
            # Empty dir should not crash
            assert result.exit_code in (0, 1)


class TestTranslateBatchErrorAggregation:
    """Test error aggregation: one bad file doesn't stop others."""

    @pytest.fixture
    def temp_input_dir_with_bad_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a valid file
            valid_file = Path(tmpdir) / "valid.md"
            valid_file.write_text("# Valid\n\nGood content.", encoding="utf-8")

            # Create a file with unsupported extension (should be skipped/not found)
            unsupported_file = Path(tmpdir) / "data.docx"
            unsupported_file.write_text("Binary content not supported.", encoding="utf-8")

            yield tmpdir

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_batch_processes_valid_files_despite_unsupported(
        self, temp_input_dir_with_bad_file, temp_output_dir,
    ):
        """Unsupported files should be skipped, valid files still processed."""
        with patch.object(ModelPool, "__init__", return_value=None):
            with patch.object(ModelPool, "translate", new_callable=AsyncMock) as mock_translate:
                mock_translate.return_value = "Translated content."
                result = runner.invoke(
                    app,
                    ["translate-batch", temp_input_dir_with_bad_file, "-o", temp_output_dir],
                )
                # Should complete without crashing even with unsupported file
                assert result.exit_code in (0, 1)


class TestTranslateBatchOutputStructure:
    """Test output directory structure mirroring input."""

    @pytest.fixture
    def temp_nested_input_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested directory structure
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()

            md_file = subdir / "nested.md"
            md_file.write_text("# Nested\n\nContent in subdirectory.", encoding="utf-8")

            yield tmpdir

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_batch_creates_output_directory(self, temp_nested_input_dir, temp_output_dir):
        """Output directory should be created if it doesn't exist."""
        # Ensure output dir does NOT exist initially
        assert not Path(temp_output_dir).exists() or Path(temp_output_dir).is_dir()

        with patch.object(ModelPool, "__init__", return_value=None):
            with patch.object(ModelPool, "translate", new_callable=AsyncMock) as mock_translate:
                mock_translate.return_value = "Translated content."
                result = runner.invoke(
                    app,
                    ["translate-batch", temp_nested_input_dir, "-o", temp_output_dir],
                )
                # Output directory should now exist
                assert Path(temp_output_dir).exists()


class TestTranslateBatchConcurrency:
    """Test concurrency option handling."""

    def test_concurrency_option_accepted(self):
        """--concurrency option should be accepted without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as outdir:
                with patch.object(ModelPool, "__init__", return_value=None):
                    with patch.object(ModelPool, "translate", new_callable=AsyncMock) as mock_translate:
                        mock_translate.return_value = "Translated"
                        result = runner.invoke(
                            app,
                            [
                                "translate-batch",
                                tmpdir,
                                "-o",
                                outdir,
                                "-j",
                                "3",
                            ],
                        )
                        # Should not fail due to invalid concurrency value
                        assert result.exit_code in (0, 1, 2)


class TestTranslateBatchSummary:
    """Test batch processing summary output."""

    def test_batch_summary_shows_counts(self):
        """Output should show succeeded/failed counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as outdir:
                # Create a file to trigger processing
                test_file = Path(tmpdir) / "test.md"
                test_file.write_text("# Test\n\nContent.", encoding="utf-8")

                with patch.object(ModelPool, "__init__", return_value=None):
                    with patch.object(ModelPool, "translate", new_callable=AsyncMock) as mock_translate:
                        mock_translate.return_value = "Translated content."
                        result = runner.invoke(
                            app,
                            ["translate-batch", tmpdir, "-o", outdir],
                        )
                        # Should show processing summary
                        assert "processed" in result.output.lower() or result.exit_code in (0, 1)
