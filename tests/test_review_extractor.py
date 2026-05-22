"""Unit tests for ol_review_extractor module."""
import os
import tempfile
from pathlib import Path

import pytest

from ol_review_extractor import extract_warnings


class TestMDWarningExtraction:
    """Test MD warning extraction."""

    @pytest.fixture
    def temp_md_with_warnings(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
        ) as f:
            f.write("# Test Document\n\n")
            f.write("Some content here.\n\n")
            f.write("<!-- OL_WARN: Tag_auto_appended -->\n")
            f.write("More content after warning.\n\n")
            f.write("## Another Section\n\n")
            f.write("<!-- OL_WARN: Low_Score -->\n")
            f.write("Final paragraph.\n")
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def temp_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "review.md")

    def test_extract_md_warnings(self, temp_md_with_warnings, temp_output):
        """Test extraction of MD warnings from mock MD file."""
        extract_warnings(temp_md_with_warnings, temp_output)

        assert os.path.exists(temp_output)
        content = Path(temp_output).read_text(encoding="utf-8")
        assert "<!-- OL_WARN: Tag_auto_appended -->" in content
        assert "<!-- OL_WARN: Low_Score -->" in content

    def test_extract_md_warning_count(self, temp_md_with_warnings, temp_output):
        """Test that all MD warnings are extracted."""
        extract_warnings(temp_md_with_warnings, temp_output)

        content = Path(temp_output).read_text(encoding="utf-8")
        lines = content.splitlines()
        # Should have exactly 2 warning lines
        assert len(lines) == 2


class TestXLIFFWarningExtraction:
    """Test XLIFF warning extraction."""

    @pytest.fixture
    def temp_xliff_with_warnings(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xlf", delete=False,
        ) as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            f.write('<xliff version="1.2">\n')
            f.write('  <file source-language="en" target-language="zh">\n')
            f.write('    <body>\n')
            f.write('      <trans-unit id="tu1">\n')
            f.write('        <source>Hello world</source>\n')
            f.write('        <note from="OL">Warning: Tag auto-appended at end</note>\n')
            f.write('      </trans-unit>\n')
            f.write('      <trans-unit id="tu2">\n')
            f.write('        <source>Goodbye</source>\n')
            f.write('        <note from="OL">Warning: Term_miss</note>\n')
            f.write('      </trans-unit>\n')
            f.write('    </body>\n')
            f.write('  </file>\n')
            f.write('</xliff>\n')
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def temp_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "review.xlf")

    def test_extract_xliff_warnings(self, temp_xliff_with_warnings, temp_output):
        """Test extraction of XLIFF warnings from mock XLIFF file."""
        extract_warnings(temp_xliff_with_warnings, temp_output)

        assert os.path.exists(temp_output)
        content = Path(temp_output).read_text(encoding="utf-8")
        assert '<note from="OL">Warning: Tag auto-appended at end</note>' in content
        assert '<note from="OL">Warning: Term_miss</note>' in content

    def test_extract_xliff_warning_count(self, temp_xliff_with_warnings, temp_output):
        """Test that all XLIFF warnings are extracted."""
        extract_warnings(temp_xliff_with_warnings, temp_output)

        content = Path(temp_output).read_text(encoding="utf-8")
        lines = content.splitlines()
        # Should have exactly 2 warning lines
        assert len(lines) == 2


class TestPlainTextOL_WARNExtraction:
    """Test plain text OL_WARN extraction."""

    @pytest.fixture
    def temp_plain_with_warnings(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False,
        ) as f:
            f.write("Normal line without warning\n")
            f.write("OL_WARN: Tag_auto_appended\n")
            f.write("Another normal line\n")
            f.write("OL_WARN: Low_Score\n")
            f.write("Final normal line\n")
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def temp_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "review.txt")

    def test_extract_plain_warnings(self, temp_plain_with_warnings, temp_output):
        """Test extraction of plain text OL_WARN patterns."""
        extract_warnings(temp_plain_with_warnings, temp_output)

        assert os.path.exists(temp_output)
        content = Path(temp_output).read_text(encoding="utf-8")
        assert "OL_WARN: Tag_auto_appended" in content
        assert "OL_WARN: Low_Score" in content

    def test_extract_plain_warning_count(self, temp_plain_with_warnings, temp_output):
        """Test that all plain text OL_WARN are extracted."""
        extract_warnings(temp_plain_with_warnings, temp_output)

        content = Path(temp_output).read_text(encoding="utf-8")
        lines = content.splitlines()
        # Should have exactly 2 OL_WARN lines
        assert len(lines) == 2


class TestNoWarningsFound:
    """Test handling when no warnings are found."""

    @pytest.fixture
    def temp_clean_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
        ) as f:
            f.write("# Clean Document\n\n")
            f.write("No warnings here.\n\n")
            f.write("Just normal content.\n")
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def temp_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "review.md")

    def test_no_warnings_found(self, temp_clean_file, temp_output):
        """Test output file creation when no warnings found."""
        extract_warnings(temp_clean_file, temp_output)

        assert os.path.exists(temp_output)
        content = Path(temp_output).read_text(encoding="utf-8")
        assert "# No OL_WARN warnings found" in content


class TestInvalidInputFile:
    """Test handling of invalid input file."""

    @pytest.fixture
    def temp_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield os.path.join(tmpdir, "review.md")

    def test_file_not_found(self, temp_output):
        """Test that FileNotFoundError is raised for missing input."""
        nonexistent = "/nonexistent/path/to/file.md"

        with pytest.raises(FileNotFoundError):
            extract_warnings(nonexistent, temp_output)


class TestOutputFileCreation:
    """Test output file creation."""

    @pytest.fixture
    def temp_md_with_warning(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
        ) as f:
            f.write("# Test\n\n")
            f.write("Some content.\n\n")
            f.write("<!-- OL_WARN: Test_warning -->\n")
            f.write("More content.\n")
            path = f.name
        yield path
        os.unlink(path)

    def test_output_directory_created(self, temp_md_with_warning):
        """Test that output directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_output = os.path.join(tmpdir, "nested", "deep", "review.md")
            extract_warnings(temp_md_with_warning, nested_output)

            assert os.path.exists(nested_output)

    def test_output_file_is_valid_utf8(self, temp_md_with_warning):
        """Test that output file contains valid UTF-8 text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "review.md")
            extract_warnings(temp_md_with_warning, output_file)

            # Should be readable as UTF-8
            content = Path(output_file).read_text(encoding="utf-8")
            assert isinstance(content, str)

    def test_output_preserves_warning_line(self, temp_md_with_warning):
        """Test that warning lines are preserved exactly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "review.md")
            extract_warnings(temp_md_with_warning, output_file)

            content = Path(output_file).read_text(encoding="utf-8")
            assert "<!-- OL_WARN: Test_warning -->" in content
