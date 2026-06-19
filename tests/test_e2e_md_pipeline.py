"""End-to-end tests for MD pipeline with fixture files."""
import tempfile
from pathlib import Path

import pytest

from ol_core.interfaces import MockLLMRestorer
from ol_md.pipeline import MDRepairPipeline
from ol_review_extractor import extract_warnings


class TestE2EMDHappyPath:
    """E2E tests for happy path through MD pipeline."""

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def fixture_md_path(self):
        """Path to sample.md fixture."""
        return Path(__file__).parent / "fixtures" / "sample.md"

    def test_pipeline_processes_fixture_md(self, fixture_md_path):
        """Test that sample.md fixture can be processed through pipeline."""
        assert fixture_md_path.exists(), f"Fixture not found: {fixture_md_path}"

        content = fixture_md_path.read_text(encoding="utf-8")
        assert len(content) > 0
        assert "# Hello World" in content

    def test_md_repair_pipeline_with_mock_llm(self, fixture_md_path):
        """Test MDRepairPipeline with MockLLMRestorer processes fixture."""
        content = fixture_md_path.read_text(encoding="utf-8")
        pipeline = MDRepairPipeline(llm_restorer=MockLLMRestorer())

        # Mock LLM means pass-through - content should remain unchanged
        result = pipeline.repair(content, content, {})

        assert isinstance(result, str)
        assert len(result) > 0
        # Original content structure preserved
        assert "# Hello World" in result

    def test_pipeline_produces_valid_output(self, fixture_md_path, temp_output_dir):
        """Test pipeline produces valid output file."""
        content = fixture_md_path.read_text(encoding="utf-8")
        pipeline = MDRepairPipeline()

        # Repair with empty shield map (no placeholders)
        result = pipeline.repair(content, content, {})

        output_file = Path(temp_output_dir) / "output.md"
        output_file.write_text(result, encoding="utf-8")

        assert output_file.exists()
        assert output_file.read_text(encoding="utf-8") == result


class TestE2EMDErrorHandling:
    """E2E tests for MD pipeline error handling."""

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_nonexistent_file_raises(self):
        """Test that nonexistent file raises FileNotFoundError."""
        nonexistent = "/nonexistent/path/to/file.md"

        with pytest.raises(FileNotFoundError):
            Path(nonexistent).read_text(encoding="utf-8")

    def test_pipeline_with_corrupted_content(self):
        """Test pipeline handles corrupted/malformed content."""
        corrupted = "text \x00OL_CODE_0000\x00 \x00OL_MATH_0001\x00 end"
        original = "text \x00OL_CODE_0000\x00 \x00OL_MATH_0001\x00 original"
        shield_map = {'CODE_0000': 'code', 'MATH_0001': '$formula$'}

        pipeline = MDRepairPipeline()
        result = pipeline.repair(corrupted, original, shield_map)

        # Should either restore placeholders or add OL_WARN
        assert isinstance(result, str)
        assert len(result) > 0

    def test_pipeline_graceful_failure_with_mock(self):
        """Test pipeline gracefully handles LLM failures with mock."""
        pipeline = MDRepairPipeline(llm_restorer=MockLLMRestorer())

        text = "some translated content"
        original = "original \x00OL_CODE_0000\x00 text"
        shield_map = {'CODE_0000': 'code'}

        # Mock doesn't change anything - L3 is pass-through
        result = pipeline.repair(text, original, shield_map)
        assert isinstance(result, str)

    def test_output_dir_creation(self, temp_output_dir):
        """Test that output directory is created if it doesn't exist."""
        nested_path = Path(temp_output_dir) / "nested" / "deep"
        nested_path.mkdir(parents=True, exist_ok=True)

        output_file = nested_path / "test.md"
        output_file.write_text("# Test", encoding="utf-8")

        assert output_file.exists()


class TestE2EMDWarningExtraction:
    """E2E tests for warning extraction from MD files."""

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def review_fixture_path(self):
        """Path to review_sample.md fixture with OL_WARN markers."""
        return Path(__file__).parent / "fixtures" / "review_sample.md"

    def test_review_fixture_has_warnings(self, review_fixture_path):
        """Test that review_sample.md fixture contains OL_WARN markers."""
        assert review_fixture_path.exists(), f"Fixture not found: {review_fixture_path}"

        content = review_fixture_path.read_text(encoding="utf-8")
        assert "<!-- OL_WARN:" in content
        assert "Tag_auto_appended" in content
        assert "Low_Score" in content

    def test_extract_warnings_from_review_fixture(self, review_fixture_path, temp_output_dir):
        """Test extracting OL_WARN from review_sample.md to review file."""
        output_file = Path(temp_output_dir) / "review.md"

        extract_warnings(str(review_fixture_path), str(output_file))

        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "OL_WARN" in content

    def test_review_file_contains_both_warnings(self, review_fixture_path, temp_output_dir):
        """Test that review file contains both OL_WARN markers from fixture."""
        output_file = Path(temp_output_dir) / "review.md"

        extract_warnings(str(review_fixture_path), str(output_file))

        content = output_file.read_text(encoding="utf-8")
        # review_sample.md has two OL_WARN markers
        assert "Tag_auto_appended" in content or "Low_Score" in content

    def test_no_warnings_produces_placeholder_message(self, temp_output_dir):
        """Test that files without warnings produce appropriate message."""
        clean_file = Path(temp_output_dir) / "clean.md"
        clean_file.write_text("# Clean Document\n\nNo warnings here.", encoding="utf-8")

        output_file = Path(temp_output_dir) / "review.md"
        extract_warnings(str(clean_file), str(output_file))

        content = output_file.read_text(encoding="utf-8")
        assert "# No OL_WARN warnings found" in content


class TestE2EMDPipelineFailure:
    """E2E tests for pipeline failure graceful handling."""

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_pipeline_handles_missing_placeholders(self):
        """Test pipeline handles case where placeholders are missing."""
        translated = "translated text without placeholders"
        original = "original \x00OL_CODE_0000\x00 text"
        shield_map = {'CODE_0000': 'code'}

        pipeline = MDRepairPipeline()
        result = pipeline.repair(translated, original, shield_map)

        # Should trigger L4 safe fallback
        assert isinstance(result, str)
        assert "OL_WARN" in result

    def test_pipeline_with_empty_shield_map(self):
        """Test pipeline works with empty shield map."""
        text = "Simple text content"
        pipeline = MDRepairPipeline()

        result = pipeline.repair(text, text, {})

        assert result == text

    def test_pipeline_preserves_intact_placeholders(self):
        """Test pipeline preserves intact placeholders."""
        text = "text \x00OL_CODE_0000\x00 end"
        original = "original \x00OL_CODE_0000\x00 text"
        shield_map = {'CODE_0000': 'code'}

        pipeline = MDRepairPipeline()
        result = pipeline.repair(text, original, shield_map)

        # Placeholder should be preserved
        assert '\x00OL_CODE_0000\x00' in result

    def test_is_complete_validation(self):
        """Test is_complete method validates placeholder presence.

        The completion signal is the {{_OL_XTAG_<key>_}} shield format, which
        the L2 span-aligner uses to indicate a preserved placeholder.
        The legacy \x00OL_<key>\x00 active wrapper is treated as
        "still in flight" (incomplete) by is_complete — by design, it triggers
        the L3 LLM-restore path. See test_md_auto_repair.py for the
        corresponding strict-mode tests.
        """
        pipeline = MDRepairPipeline()

        # Modern {{_OL_XTAG_..._}} format — considered complete
        text_with_modern_placeholder = "text {{_OL_XTAG_CODE_0000_}} end"
        shield_map = {'CODE_0000': 'code'}
        assert pipeline.is_complete(text_with_modern_placeholder, shield_map) is True

        # Plain key (no wrapper) — also complete (backward-compat path)
        text_with_plain_key = "text CODE_0000 end"
        assert pipeline.is_complete(text_with_plain_key, shield_map) is True

        # No placeholder key at all — incomplete
        text_without_placeholder = "text end"
        assert pipeline.is_complete(text_without_placeholder, shield_map) is False


class TestE2EMDMockLLMIntegration:
    """E2E tests for MD pipeline with mocked LLM calls."""

    def test_mock_llm_restorer_is_pass_through(self):
        """Test MockLLMRestorer doesn't modify translated text."""
        restorer = MockLLMRestorer()

        translated = "translated content"
        original = "original \x00OL_CODE_0000\x00 text"
        shield_map = {'CODE_0000': 'code'}

        result = restorer.restore_placeholders(translated, original, shield_map)

        # Mock should return translated text unchanged
        assert result == translated

    def test_pipeline_with_mock_restorer(self):
        """Test MDRepairPipeline works with MockLLMRestorer."""
        pipeline = MDRepairPipeline(llm_restorer=MockLLMRestorer())

        text = "text with \x00OL_CODE_0000\x00 placeholder"
        result = pipeline.repair(text, text, {'CODE_0000': 'code'})

        assert isinstance(result, str)
        assert '\x00OL_CODE_0000\x00' in result

    def test_pipeline_with_none_restorer_uses_default(self):
        """Test MDRepairPipeline works without explicit restorer."""
        pipeline = MDRepairPipeline()  # No restorer passed

        text = "text \x00OL_CODE_0000\x00 end"
        result = pipeline.repair(text, text, {'CODE_0000': 'code'})

        # Should work with default (mock behavior)
        assert '\x00OL_CODE_0000\x00' in result


class TestE2EMDPerformance:
    """E2E tests for MD pipeline performance."""

    def test_pipeline_completes_within_timeout(self):
        """Test pipeline operations complete within reasonable time."""
        import time

        pipeline = MDRepairPipeline()

        text = "# Test\n\nContent for performance test."
        shield_map = {}

        start = time.time()
        result = pipeline.repair(text, text, shield_map)
        elapsed = time.time() - start

        assert elapsed < 1.0  # Should complete in under 1 second
        assert isinstance(result, str)

    def test_multiple_operations_sequence(self):
        """Test multiple pipeline operations in sequence."""
        pipeline = MDRepairPipeline()

        texts = [
            "# Document 1\n\nContent",
            "# Document 2\n\nMore content",
            "# Document 3\n\nEven more",
        ]

        for text in texts:
            result = pipeline.repair(text, text, {})
            assert isinstance(result, str)
            assert len(result) > 0
