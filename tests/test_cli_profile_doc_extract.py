"""Tests for _extract_text_from_file() helper in profile_doc.py."""
import pytest

from cli.profile_doc import _extract_text_from_file


class TestExtractTextFromFile:
    def test_plain_text_file(self, tmp_path):
        """UTF-8 text files are read directly."""
        p = tmp_path / "test.md"
        p.write_text("# Hello\n\nWorld", encoding="utf-8")
        result = _extract_text_from_file(p)
        assert result == "# Hello\n\nWorld"

    def test_csv_file(self, tmp_path):
        """CSV files (extension) are read as UTF-8."""
        p = tmp_path / "test.csv"
        p.write_text("a,b,c\n1,2,3", encoding="utf-8")
        result = _extract_text_from_file(p)
        assert "1,2,3" in result

    def test_docx_file(self, tmp_path):
        """DOCX files are extracted via python-docx."""
        try:
            from docx import Document
        except ImportError:
            pytest.skip("python-docx not installed")

        p = tmp_path / "test.docx"
        doc = Document()
        doc.add_paragraph("Hello from docx")
        doc.save(str(p))
        result = _extract_text_from_file(p)
        assert "Hello from docx" in result

    def test_pptx_file(self, tmp_path):
        """PPTX files are extracted via python-pptx."""
        try:
            from pptx import Presentation
        except ImportError:
            pytest.skip("python-pptx not installed")

        p = tmp_path / "test.pptx"
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "Hello from pptx"
        prs.save(str(p))
        result = _extract_text_from_file(p)
        assert "Hello from pptx" in result

    def test_unknown_binary_raises_clear_error(self, tmp_path):
        """A binary file with unknown extension raises ValueError with helpful message."""
        p = tmp_path / "test.xyz"
        p.write_bytes(b"\x80\x81\x82\x83 binary content")
        with pytest.raises(ValueError) as exc:
            _extract_text_from_file(p)
        assert "Unsupported" in str(exc.value) or "binary" in str(exc.value).lower()

    def test_docx_import_error_gives_clear_message(self, tmp_path, monkeypatch):
        """If python-docx is not installed, raise ValueError with install instructions."""
        # Simulate ImportError by removing docx from sys.modules if present
        p = tmp_path / "test.docx"
        p.write_bytes(b"PK\x03\x04 fake docx")

        import sys
        original_docx = sys.modules.get("docx")
        sys.modules["docx"] = None  # force ImportError
        try:
            with pytest.raises(ValueError) as exc:
                _extract_text_from_file(p)
            assert "python-docx" in str(exc.value)
        finally:
            if original_docx is not None:
                sys.modules["docx"] = original_docx
            else:
                sys.modules.pop("docx", None)
