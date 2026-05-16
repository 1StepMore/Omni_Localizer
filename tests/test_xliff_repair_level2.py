"""Tests for XLIFF repair level 2 (anchor mapping)."""
import pytest
from unittest.mock import Mock, patch
from ol_xliff.repair.level2 import level2_span_align, _has_span_aligner


class TestRepairLevel2:
    """Test level2_span_align() function with graceful degradation."""

    def test_graceful_degradation_no_span_aligner(self):
        """Test that function returns text unchanged when span-aligner unavailable."""
        if _has_span_aligner:
            pytest.skip("span-aligner is available, cannot test graceful degradation")

        text = 'Hello world'
        shield_map = {'x_1': '<x id="1"/>'}
        original = 'Hello world'
        result = level2_span_align(text, shield_map, original)
        assert result == text

    def test_anchor_mapping_called(self):
        """Test that SpanProjector.project() is called when span-aligner available."""
        if not _has_span_aligner:
            pytest.skip("span-aligner not available, cannot test anchor mapping")

        text = 'Hello world'
        shield_map = {'x_1': '<x id="1"/>'}
        original = 'Hello world'

        with patch('ol_xliff.repair.level2.SpanProjector') as mock_projector_class:
            mock_instance = Mock()
            mock_instance.project.return_value = text
            mock_projector_class.return_value = mock_instance

            result = level2_span_align(text, shield_map, original)

            mock_instance.project.assert_called_once_with(text, shield_map, original)
            assert result == text

    def test_empty_inputs(self):
        """Test handling of empty inputs."""
        result = level2_span_align('', {}, '')
        assert result == ''

    def test_empty_shield_map(self):
        """Test handling of empty shield_map."""
        text = 'Hello world'
        result = level2_span_align(text, {}, 'Hello world')
        assert result == text

    def test_text_unchanged_when_no_span_aligner(self):
        """Test that text is returned unchanged when span-aligner import fails."""
        with patch.dict('sys.modules', {'span_alignment': None}):
            # Re-import to test the import error path
            import importlib
            import ol_xliff.repair.level2 as level2_mod
            importlib.reload(level2_mod)

            text = 'Test text'
            result = level2_mod.level2_span_align(text, {'x_1': '<x id="1"/>'}, 'Test text')
            assert result == text