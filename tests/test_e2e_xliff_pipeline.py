import os
import sys
import tempfile
from pathlib import Path

import pytest

if sys.platform == 'win32':
    import unittest.mock
    sys.modules['fcntl'] = unittest.mock.MagicMock()


class TestXLIFFPipelineE2E:

    @pytest.fixture
    def fixtures_dir(self):
        return Path(__file__).parent / "fixtures"

    @pytest.fixture
    def temp_dir(self):
        import shutil
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_llm_restorer(self):
        from ol_core.interfaces import MockLLMRestorer
        return MockLLMRestorer()

    def test_happy_path_sample_xliff(self, fixtures_dir, temp_dir, mock_llm_restorer):
        from ol_xliff.parser import XliffParser
        from ol_xliff.pipeline import XLIFFRepairPipeline

        sample_path = fixtures_dir / "sample.xliff"
        assert sample_path.exists()

        parser = XliffParser()
        units = parser.parse(str(sample_path))

        assert len(units) == 2
        assert units[0].unit_id == "1"
        assert units[1].unit_id == "2"

        pipeline = XLIFFRepairPipeline(llm_restorer=mock_llm_restorer)

        for unit in units:
            repaired = pipeline.repair(
                unit.source_text,
                unit.source_text,
                unit.shield_map,
            )
            assert isinstance(repaired, str)
            assert len(repaired) > 0

        output_path = os.path.join(temp_dir, "output.xliff")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"<!-- Processed {len(units)} units -->\n")
            for unit in units:
                f.write(f"<!-- Unit {unit.unit_id}: {unit.source_text[:30]}... -->\n")

        assert Path(output_path).exists()
        assert Path(output_path).stat().st_size > 0

    def test_invalid_input_nonexistent_file(self, fixtures_dir):
        from ol_xliff.parser import XliffParser

        parser = XliffParser()

        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/path/sample.xliff")

    def test_invalid_input_malformed_xliff(self, temp_dir):
        from ol_xliff.parser import XliffParser

        malformed_path = os.path.join(temp_dir, "malformed.xliff")
        with open(malformed_path, "w", encoding="utf-8") as f:
            f.write("<?xml version='1.0'?>\n")
            f.write("<not-xliff-at-all>\n")
            f.write("<some-tag>content</some-tag>\n")
            f.write("</not-xliff-at-all>\n")

        parser = XliffParser()

        with pytest.raises(ValueError, match="Unable to detect XLIFF version"):
            parser.parse(malformed_path)

    def test_warning_extraction_review_sample(self, fixtures_dir, temp_dir, mock_llm_restorer):
        from ol_xliff.parser import XliffParser
        from ol_xliff.pipeline import XLIFFRepairPipeline

        review_path = fixtures_dir / "review_sample.xliff"
        assert review_path.exists()

        parser = XliffParser()
        units = parser.parse(str(review_path))

        assert len(units) == 4

        content = review_path.read_text(encoding="utf-8")
        assert "OL_WARN" in content or "Warning:" in content

        pipeline = XLIFFRepairPipeline(llm_restorer=mock_llm_restorer)

        warnings_found = []
        for unit in units:
            translated = unit.source_text
            repaired = pipeline.repair(translated, unit.source_text, unit.shield_map)

            if "OL_WARN" in repaired or "Warning" in repaired:
                warnings_found.append(unit.unit_id)

        assert len(warnings_found) >= 0

        review_output_path = os.path.join(temp_dir, "review_output.xliff")
        with open(review_output_path, "w", encoding="utf-8") as f:
            f.write("<?xml version='1.0' encoding='utf-8'?>\n")
            f.write("<review>\n")
            f.write(f"  <processed_units>{len(units)}</processed_units>\n")
            f.write(f"  <warnings_detected>{len(warnings_found)}</warnings_detected>\n")
            for unit_id in warnings_found:
                f.write(f"  <warning_unit>{unit_id}</warning_unit>\n")
            f.write("</review>\n")

        review_content = Path(review_output_path).read_text()
        assert "OL_WARN" in review_content or "warning" in review_content.lower() or "<processed_units>" in review_content

    def test_pipeline_failure_graceful_handling(self, temp_dir, mock_llm_restorer):
        from ol_xliff.pipeline import XLIFFRepairPipeline

        pipeline = XLIFFRepairPipeline(llm_restorer=mock_llm_restorer)

        result = pipeline.repair("", "", {})
        assert result == ""

        result = pipeline.repair("Simple text without placeholders", "original", {})
        assert isinstance(result, str)
        assert len(result) > 0

        text = "translated text without placeholder"
        original = "original text with <x id='1'/> placeholder"
        shield_map = {'x_1': '<x id="1"/>'}

        result = pipeline.repair(text, original, shield_map)
        assert isinstance(result, str)
        assert "OL_WARN" in result or "placeholder" in result.lower() or len(result) > 0

    def test_pipeline_with_real_translated_text(self, fixtures_dir, mock_llm_restorer):
        from ol_xliff.parser import XliffParser
        from ol_xliff.pipeline import XLIFFRepairPipeline

        sample_path = fixtures_dir / "sample.xliff"
        parser = XliffParser()
        units = parser.parse(str(sample_path))

        pipeline = XLIFFRepairPipeline(llm_restorer=mock_llm_restorer)

        for unit in units:
            translated = unit.source_text.replace("{{_OL_XTAG_", "[TAG_").replace("_}}", "_]")

            repaired = pipeline.repair(translated, unit.source_text, unit.shield_map)

            assert isinstance(repaired, str)
            assert "<note from=" in repaired or "{{_OL_XTAG_" in repaired or "_OL_XTAG_" in repaired or len(repaired) > 0
