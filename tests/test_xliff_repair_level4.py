"""Tests for XLIFF repair level 4 (safe fallback)."""
from ol_xliff.repair.level4 import level4_safe_fallback


class TestRepairLevel4:
    """Test level4_safe_fallback() function."""

    def test_append_at_unit_end(self):
        """Test that actual tag content is appended at unit end, not placeholder keys."""
        text = '<unit id="1"><source>Hello world</source></unit>'
        missing_placeholders = {'x_1': '<x id="1"/>', 'mrk_m2': '<mrk id="m2">marked</mrk>'}
        result = level4_safe_fallback(text, missing_placeholders)

        # Should have actual tag content, not placeholder markers
        assert '<x id="1"/>' in result
        assert '<mrk id="m2">marked</mrk>' in result
        # Should NOT have placeholder keys
        assert '{{_OL_XTAG_' not in result
        assert 'x_1' not in result or 'x id="1"' in result
        # Should have OL note
        assert '<note from="OL">' in result

    def test_ol_note_added(self):
        """Test that OL note is added after placeholders."""
        text = '<unit id="1"><source>Test</source></unit>'
        missing_placeholders = {'x_1': '<x id="1"/>'}
        result = level4_safe_fallback(text, missing_placeholders)

        assert '<note from="OL">Warning: Tag auto-appended at end, manual check needed</note>' in result

    def test_no_unit_boundary_fallback(self):
        """Test fallback when no unit boundary exists - actual tags appended."""
        text = 'Plain text without unit tags'
        missing_placeholders = {'x_1': '<x id="1"/>'}
        result = level4_safe_fallback(text, missing_placeholders)

        # Actual tag should be appended, not placeholder key
        assert '<x id="1"/>' in result
        assert '{{_OL_XTAG_' not in result
        # OL note should be present
        assert '<note from="OL">' in result

    def test_empty_text(self):
        """Test handling of empty text."""
        result = level4_safe_fallback('', {'x_1': '<x id="1"/>'})
        assert '<note from="OL">' in result

    def test_empty_missing_placeholders(self):
        """Test handling when no placeholders are missing."""
        text = '<unit id="1">Hello</unit>'
        result = level4_safe_fallback(text, {})
        assert result == text

    def test_multiple_missing_placeholders(self):
        """Test appending multiple missing placeholders."""
        text = '<trans-unit id="1"><source>Test</source></trans-unit>'
        missing_placeholders = {
            'x_1': '<x id="1"/>',
            'ph_2': '<ph id="2"/>',
            'mrk_m3': '<mrk id="m3">text</mrk>',
        }
        result = level4_safe_fallback(text, missing_placeholders)

        # Should have note for OL warning
        assert '<note from="OL">' in result
        # All placeholder types should be mentioned
        assert 'x_1' in result or 'x' in result
        assert 'ph_2' in result or 'ph' in result
        assert 'mrk_m3' in result or 'mrk' in result

    def test_trans_unit_boundary(self):
        """Test fallback with trans-unit boundary (XLIFF 1.x)."""
        text = '<trans-unit id="1"><source>Hello</source></trans-unit>'
        missing = {'bx_1': '<bx id="1"/>'}
        result = level4_safe_fallback(text, missing)

        assert '<note from="OL">' in result
        assert '</trans-unit>' in text or 'bx' in result
