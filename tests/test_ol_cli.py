"""Unit tests for ol_cli typer application."""
import os
import tempfile
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ol_cli import __version__, app

runner = CliRunner()


class TestCLICommandLoading:
    """Test CLI command loading."""

    def test_cli_app_exists(self):
        assert app is not None

    def test_version_constant(self):
        assert __version__ == "0.2.3"


class TestVersionFlag:
    """Test --version flag."""

    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestHelpFlag:
    """Test --help flag."""

    def test_help_flag(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Omni-Localizer" in result.output

    def test_help_shows_commands(self):
        result = runner.invoke(app, ["--help"])
        assert "translate-md" in result.output
        assert "translate-xliff" in result.output
        assert "extract-warnings" in result.output


class TestTranslateMD:
    """Test translate-md command."""

    @pytest.fixture
    def temp_md(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
        ) as f:
            f.write("# Test\n\nContent here.")
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_translate_md_valid_input(self, temp_md, temp_output_dir):
        result = runner.invoke(
            app,
            ["translate-md", temp_md, "-o", temp_output_dir],
        )
        assert result.exit_code == 0
        assert "Translated" in result.output

    def test_translate_md_file_not_found(self):
        result = runner.invoke(
            app,
            ["translate-md", "/nonexistent/file.md"],
        )
        assert result.exit_code == 2
        assert "not found" in result.output.lower()


class TestTranslateXliff:
    """Test translate-xliff command."""

    @pytest.fixture
    def temp_xliff(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xlf", delete=False,
        ) as f:
            f.write('<?xml version="1.0"?>\n<xliff version="1.2"><file></file></xliff>')
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_translate_xliff_valid_input(self, temp_xliff, temp_output_dir):
        result = runner.invoke(
            app,
            ["translate-xliff", temp_xliff, "-o", temp_output_dir],
        )
        assert result.exit_code == 0
        assert "Translated" in result.output

    def test_translate_xliff_file_not_found(self):
        result = runner.invoke(
            app,
            ["translate-xliff", "/nonexistent/file.xlf"],
        )
        assert result.exit_code == 2
        assert "not found" in result.output.lower()


class TestExtractWarnings:
    """Test extract-warnings command."""

    @pytest.fixture
    def temp_md_with_warnings(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
        ) as f:
            f.write("# Test\n\n<!-- OL_WARN: Tag_auto_appended -->\nContent.\n\n<!-- OL_WARN: Low_Score -->\nMore content.")
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def temp_md_empty(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
        ) as f:
            f.write("# Test\n\nJust normal content.")
            path = f.name
        yield path
        os.unlink(path)

    def test_extract_warnings_with_warnings(self, temp_md_with_warnings):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "review.md")
            result = runner.invoke(
                app,
                ["extract-warnings", temp_md_with_warnings, "--output", output_file],
            )
            assert result.exit_code == 0
            assert "2 warnings" in result.output

    def test_extract_warnings_empty_input(self, temp_md_empty):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "review.md")
            result = runner.invoke(
                app,
                ["extract-warnings", temp_md_empty, "--output", output_file],
            )
            assert result.exit_code == 0
            assert "0 warnings" in result.output

    def test_extract_warnings_file_not_found(self):
        result = runner.invoke(
            app,
            ["extract-warnings", "/nonexistent/file.md"],
        )
        assert result.exit_code == 2
        assert "not found" in result.output.lower()


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_file_not_found(self):
        result = runner.invoke(
            app,
            ["translate-md", "/nonexistent/file.md"],
        )
        assert result.exit_code == 2
        assert "not found" in result.output.lower()

    def test_permission_denied_simulation(self):
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = False
            result = runner.invoke(
                app,
                ["translate-md", "/protected/file.md"],
            )
            assert result.exit_code == 2

    def test_invalid_command(self):
        result = runner.invoke(app, ["invalid-command"])
        assert result.exit_code != 0

    def test_missing_required_argument(self):
        result = runner.invoke(app, ["translate-md"])
        assert result.exit_code != 0
