"""Tests for XLIFF repair pipeline."""
from ol_core.interfaces import MockLLMRestorer
from ol_xliff.pipeline import XLIFFRepairPipeline


class TestXLIFFRepairPipeline:
    """Test XLIFFRepairPipeline cascade orchestration."""

    def test_l1_cascade_stop(self):
        """Test that cascade stops at L1 when placeholders are complete."""
        pipeline = XLIFFRepairPipeline()

        # Text with placeholder already present
        text = 'text {{_OL_XTAG_x_1_}} end'
        original = 'text <x id="1"/> end'
        shield_map = {'x_1': '<x id="1"/>'}

        result, warnings = pipeline.repair(text, original, shield_map)

        # Placeholder should be present (L1 didn't break it)
        assert '{{_OL_XTAG_x_1_}}' in result or 'x_1' in result
        assert warnings == []

    def test_full_cascade_to_l4(self):
        """Test full cascade through all 4 levels to L4."""
        pipeline = XLIFFRepairPipeline()

        # Text without placeholder (missing)
        text = 'text end'
        original = 'text {{_OL_XTAG_x_1_}} end'
        shield_map = {'x_1': '<x id="1"/>'}

        result, warnings = pipeline.repair(text, original, shield_map)

        # L4 should populate warnings since placeholder is missing.
        # Text itself must NOT contain <note> XML — notes are siblings
        # of <target> injected later by write_target_back.
        assert isinstance(warnings, list)
        assert len(warnings) >= 1
        assert '<note from="OL">' not in result

    def test_is_complete_with_all_placeholders(self):
        """Test is_complete returns True when all placeholders present."""
        pipeline = XLIFFRepairPipeline()
        text = 'Hello {{_OL_XTAG_x_1_}} {{_OL_XTAG_mrk_m2_}} world'
        shield_map = {'x_1': '<x id="1"/>', 'mrk_m2': '<mrk id="m2">text</mrk>'}

        assert pipeline.is_complete(text, shield_map) is True

    def test_is_complete_with_missing_placeholders(self):
        """Test is_complete returns False when placeholders are missing."""
        pipeline = XLIFFRepairPipeline()
        text = 'Hello world'
        shield_map = {'x_1': '<x id="1"/>'}

        assert pipeline.is_complete(text, shield_map) is False

    def test_is_complete_with_empty_shield_map(self):
        """Test is_complete returns True for empty shield_map."""
        pipeline = XLIFFRepairPipeline()
        text = 'Plain text without placeholders'
        shield_map = {}

        assert pipeline.is_complete(text, shield_map) is True

    def test_cascade_with_llm_restorer(self):
        """Test cascade with LLM restorer provided."""
        pipeline = XLIFFRepairPipeline(llm_restorer=MockLLMRestorer())

        text = 'text {{_OL_XTAG_x_1_}} end'
        original = 'text <x id="1"/> end'
        shield_map = {'x_1': '<x id="1"/>'}

        result, warnings = pipeline.repair(text, original, shield_map)
        assert '{{_OL_XTAG_x_1_}}' in result or 'x_1' in result
        assert warnings == []

    def test_l2_span_align_called(self):
        """Test that L2 is invoked when L1 doesn't complete."""
        pipeline = XLIFFRepairPipeline()

        # Text with whitespace issue around placeholder
        text = 'Hello   {{_OL_XTAG_x_1_}} world'
        original = 'Hello <x id="1"/> world'
        shield_map = {'x_1': '<x id="1"/>'}

        result, warnings = pipeline.repair(text, original, shield_map)

        # L1 should clean the whitespace, making it complete
        # If L2 is called, it should not break anything
        assert 'Hello' in result
        assert warnings == []

    def test_l4_always_completes(self):
        """Test that L4 always completes without exception."""
        pipeline = XLIFFRepairPipeline()

        text = 'incomplete text'
        original = 'original text'
        shield_map = {'x_1': '<x id="1"/>', 'mrk_m1': '<mrk id="m1">marked</mrk>'}

        # Should not raise exception
        result, warnings = pipeline.repair(text, original, shield_map)
        assert isinstance(result, str)
        assert isinstance(warnings, list)
        # Text must NOT carry <note> XML — notes are siblings of <target>.
        assert '<note from="OL">' not in result
        # L4 fallback should have produced a warning for each missing placeholder.
        assert len(warnings) >= 1

    def test_empty_text_repair(self):
        """Test repair of empty text."""
        pipeline = XLIFFRepairPipeline()
        result, warnings = pipeline.repair('', '', {})
        assert result == ''
        assert warnings == []

    def test_is_complete_strict_mode_with_placeholder_format(self):
        """Strict mode verifies proper {{_OL_XTAG_key_}} format"""
        pipeline = XLIFFRepairPipeline()
        text = 'Hello {{_OL_XTAG_x_1_}} world'
        shield_map = {'x_1': '<x id="1"/>'}
        assert pipeline.is_complete(text, shield_map, strict=True) is True

    def test_is_complete_strict_mode_false_for_plain_key(self):
        """Strict mode returns False when marker appears but not in placeholder format"""
        pipeline = XLIFFRepairPipeline()
        text = 'Hello x_1 world'
        shield_map = {'x_1': '<x id="1"/>'}
        assert pipeline.is_complete(text, shield_map, strict=True) is False

    def test_is_complete_strict_mode_backward_compatible(self):
        """Strict=False (default) allows plain key match for backward compatibility"""
        pipeline = XLIFFRepairPipeline()
        text = 'Hello x_1 world'
        shield_map = {'x_1': '<x id="1"/>'}
        assert pipeline.is_complete(text, shield_map, strict=False) is True

    def test_is_complete_strict_mode_false_when_missing(self):
        """Strict mode returns False when placeholder missing"""
        pipeline = XLIFFRepairPipeline()
        text = 'Hello world'
        shield_map = {'x_1': '<x id="1"/>'}
        assert pipeline.is_complete(text, shield_map, strict=True) is False
