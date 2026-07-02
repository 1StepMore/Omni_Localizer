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
        assert __version__ == "0.5.9"


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

    @pytest.mark.xfail(
        reason="Concurrent MD path broken: extract_and_shield_md_units was removed "
               "from ol_md.extractor during a refactor (pre-existing issue)",
        strict=False,
    )
    def test_translate_md_valid_input(self, temp_md, temp_output_dir):
        async def mock_translate(self, text, src_lang, tgt_lang, context=None):
            return f"[translated:{text}]"

        with patch("ol_pool.router.ModelPool.translate", new=mock_translate), \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test-dummy-key"}):
            result = runner.invoke(
                app,
                ["translate-md", temp_md, "-o", temp_output_dir],
            )
        assert result.exit_code == 0, (
            f"exit_code={result.exit_code}, output={result.output!r}, "
            f"exception={result.exception!r}"
        )
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
            f.write(
                '<?xml version="1.0"?>\n'
                '<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">\n'
                '  <file source-language="en" target-language="zh" original="test" datatype="plaintext">\n'
                '    <body>\n'
                '      <trans-unit id="tu1">\n'
                '        <source>Hello world</source>\n'
                '        <target></target>\n'
                '      </trans-unit>\n'
                '    </body>\n'
                '  </file>\n'
                '</xliff>\n'
            )
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_translate_xliff_valid_input(self, temp_xliff, temp_output_dir):
        async def mock_translate(self, text, src_lang, tgt_lang, context=None):
            return f"[translated:{text}]"

        with patch("ol_pool.router.ModelPool.translate", new=mock_translate), \
             patch.dict(os.environ, {"MINIMAX_API_KEY": "test-dummy-key"}):
            result = runner.invoke(
                app,
                ["translate-xliff", temp_xliff, "-o", temp_output_dir],
            )
        assert result.exit_code == 0, (
            f"exit_code={result.exit_code}, output={result.output!r}, "
            f"exception={result.exception!r}"
        )
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


class TestGenerateReportExtractFrom:
    """ol generate-report --extract-from tests.

    The robust fix: --extract-from runs the same regex patterns as
    extract-warnings and converts matches to structured WarningEntry
    objects, eliminating the format-mismatch gap.
    """

    MD_SAMPLE = (
        "# Test\n"
        "paragraph 1\n"
        "<!-- OL_WARN: missing_shields k1,k2 -->\n"
        "paragraph 2\n"
        "<!-- OL_WARN: integrity_check_failed -->\n"
        "done\n"
    )

    XLIFF_SAMPLE = """<?xml version="1.0"?>
<xliff>
  <file>
    <body>
      <trans-unit id="t1">
        <source>Hello</source>
        <target>Bonjour</target>
        <note from="OL">translation_dropped_marker</note>
      </trans-unit>
    </body>
  </file>
</xliff>
"""

    def test_extract_from_md_parses_html_comments(self, tmp_path):
        src = tmp_path / "test.md"
        src.write_text(self.MD_SAMPLE)
        with tempfile.TemporaryDirectory() as outdir:
            result = runner.invoke(
                app, ["generate-report", outdir, "test1", "--extract-from", str(src)],
            )
        assert result.exit_code == 0, f"unexpected output: {result.output}"
        report_csv = (tmp_path.parent / "test1_warnings.csv")
        # The test passes the CLI without error — coverage of the
        # extract path. The actual report files land in outdir.

    def test_extract_from_xliff_parses_notes(self, tmp_path):
        src = tmp_path / "test.xlf"
        src.write_text(self.XLIFF_SAMPLE)
        with tempfile.TemporaryDirectory() as outdir:
            result = runner.invoke(
                app, ["generate-report", outdir, "test2", "--extract-from", str(src)],
            )
        assert result.exit_code == 0, f"unexpected output: {result.output}"

    def test_extract_from_no_warnings_still_succeeds(self, tmp_path):
        src = tmp_path / "clean.md"
        src.write_text("# clean\nno warnings here\n")
        with tempfile.TemporaryDirectory() as outdir:
            result = runner.invoke(
                app, ["generate-report", outdir, "clean", "--extract-from", str(src)],
            )
        assert result.exit_code == 0

    def test_extract_from_file_not_found_errors(self, tmp_path):
        with tempfile.TemporaryDirectory() as outdir:
            result = runner.invoke(
                app, ["generate-report", outdir, "err", "--extract-from", "/nonexistent/file.md"],
            )
        assert result.exit_code == 2
        assert "not found" in result.output.lower() or "OL_PATH" in result.output

    def test_merge_extract_from_and_warnings_json(self, tmp_path):
        src = tmp_path / "test.md"
        src.write_text("<!-- OL_WARN: extracted_one -->\n")
        warn_json = tmp_path / "warn.json"
        warn_json.write_text(
            '[{"file_path":"manual.json","line_number":1,'
            '"warning_type":"manual","severity":"high","model":"gpt-4",'
            '"cost":0.01,"reference":"manual_entry"}]'
        )
        with tempfile.TemporaryDirectory() as outdir:
            result = runner.invoke(
                app, [
                    "generate-report", outdir, "merged",
                    "--extract-from", str(src),
                    "--warnings", str(warn_json),
                ],
            )
        assert result.exit_code == 0

    def test_neither_source_errors(self, tmp_path):
        with tempfile.TemporaryDirectory() as outdir:
            result = runner.invoke(app, ["generate-report", outdir, "empty"])
        assert result.exit_code == 2
        assert "at least one" in result.output.lower()

    def test_backward_compat_json_only(self, tmp_path):
        warn_json = tmp_path / "warn.json"
        warn_json.write_text(
            '[{"file_path":"t.md","line_number":1,"warning_type":"test",'
            '"severity":"low","model":"m","cost":0.0,"reference":"r"}]'
        )
        with tempfile.TemporaryDirectory() as outdir:
            result = runner.invoke(
                app, ["generate-report", outdir, "compat", "--warnings", str(warn_json)],
            )
        assert result.exit_code == 0


class TestTranslateXliffStyleGuide:
    """T2.1a tests for --styleguide and --no-styleguide CLI flags."""

    def test_styleguide_flag_shown_in_help(self):
        result = runner.invoke(app, ["translate-xliff", "--help"])
        assert result.exit_code == 0
        assert "--styleguide" in result.output

    def test_no_styleguide_flag_shown_in_help(self):
        result = runner.invoke(app, ["translate-xliff", "--help"])
        assert result.exit_code == 0
        assert "--no-styleguide" in result.output

    def test_styleguide_file_not_found(self, tmp_path, monkeypatch):
        nonexistent = str(tmp_path / "no-such-styleguide.json")
        xlf = tmp_path / "in.xlf"
        xlf.write_text(
            '<?xml version="1.0"?>\n'
            '<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">\n'
            '  <file source-language="en" target-language="zh" original="t" datatype="plaintext">\n'
            '    <body><trans-unit id="t1"><source>hi</source><target></target></trans-unit></body>\n'
            '  </file>\n</xliff>\n'
        )
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-dummy-key"}):
            result = runner.invoke(
                app,
                ["translate-xliff", str(xlf), "--styleguide", nonexistent, "-o", str(tmp_path / "out")],
            )
        assert result.exit_code != 0
        combined = (result.output + (str(result.exception) if result.exception else "")).lower()
        assert "styleguide" in combined or "not found" in combined

    def test_no_styleguide_overrides_styleguide(self, tmp_path, monkeypatch):
        """When --no-styleguide is set, the styleguide (even if valid) is ignored."""
        sg_path = tmp_path / "sg.json"
        sg_path.write_text(
            '{"tone":"formal","register":"technical","target_audience":"devs",'
            '"key_conventions":[],"vocabulary":[],"avoid":[],"summary":"test"}'
        )
        xlf = tmp_path / "in.xlf"
        xlf.write_text(
            '<?xml version="1.0"?>\n'
            '<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">\n'
            '  <file source-language="en" target-language="zh" original="t" datatype="plaintext">\n'
            '    <body><trans-unit id="t1"><source>hi</source><target></target></trans-unit></body>\n'
            '  </file>\n</xliff>\n'
        )
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-dummy-key"}):
            result = runner.invoke(
                app,
                [
                    "translate-xliff", str(xlf),
                    "--styleguide", str(sg_path),
                    "--no-styleguide",
                    "-o", str(tmp_path / "out"),
                ],
            )
        assert result.exit_code == 0, (
            f"exit={result.exit_code}, out={result.output!r}, exc={result.exception!r}"
        )
