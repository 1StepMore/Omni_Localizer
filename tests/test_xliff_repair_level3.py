"""Tests for XLIFF repair level 3 (LLM restoration delegation)."""
from unittest.mock import Mock

from ol_xliff.repair.level3 import level3_llm_restore


class TestRepairLevel3:
    """Test level3_llm_restore() mock delegation."""

    def test_delegation_to_mock_restorer(self):
        """Test that function delegates to MockLLMRestorer."""
        mock_restorer = Mock()
        mock_restorer.restore_placeholders.return_value = 'Restored text'

        result = level3_llm_restore(
            'Translated text',
            'Original text',
            {'x_1': '<x id="1"/>'},
            mock_restorer,
        )

        mock_restorer.restore_placeholders.assert_called_once_with(
            'Translated text',
            'Original text',
            {'x_1': '<x id="1"/>'},
        )
        assert result == 'Restored text'

    def test_delegation_passthrough(self):
        """Test that MockLLMRestorer returns text unchanged (pass-through)."""
        from ol_core.interfaces import MockLLMRestorer

        restorer = MockLLMRestorer()
        text = 'Hello {{_OL_XTAG_x_1_}} world'
        original = 'Hello <x id="1"/> world'
        shield_map = {'x_1': '<x id="1"/>'}

        result = level3_llm_restore(text, original, shield_map, restorer)
        # Mock returns text unchanged in Phase 2
        assert result == text

    def test_empty_inputs(self):
        """Test handling of empty inputs."""
        mock_restorer = Mock()
        mock_restorer.restore_placeholders.return_value = ''

        result = level3_llm_restore('', '', {}, mock_restorer)
        assert result == ''

    def test_preserves_shield_map(self):
        """Test that shield_map is passed through correctly."""
        mock_restorer = Mock()
        shield_map = {'mrk_m1': '<mrk id="m1">text</mrk>'}
        mock_restorer.restore_placeholders.return_value = 'result'

        level3_llm_restore('text', 'original', shield_map, mock_restorer)

        call_args = mock_restorer.restore_placeholders.call_args
        assert call_args[0][2] == shield_map
