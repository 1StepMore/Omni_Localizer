"""Tests for XLIFF repair level 4 (safe fallback)."""
from ol_xliff.repair.level4 import level4_safe_fallback


class TestRepairLevel4:
    """Test level4_safe_fallback() function.

    Contract: returns (text, warnings) tuple. Text no longer contains
    <note> XML — warnings are emitted separately so write_target_back
    can inject them as siblings of <target>, not nested inside.
    """

    def test_actual_tag_content_appended(self):
        text = '<unit id="1"><source>Hello world</source></unit>'
        missing_placeholders = {'x_1': '<x id="1"/>', 'mrk_m2': '<mrk id="m2">marked</mrk>'}
        text_out, warnings = level4_safe_fallback(text, missing_placeholders)

        assert '<x id="1"/>' in text_out
        assert '<mrk id="m2">marked</mrk>' in text_out
        assert '{{_OL_XTAG_' not in text_out
        assert '<note' not in text_out
        assert len(warnings) >= 1

    def test_ol_note_in_warnings(self):
        text = '<unit id="1"><source>Test</source></unit>'
        missing_placeholders = {'x_1': '<x id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing_placeholders)

        assert '<note' not in text_out
        joined = ' '.join(warnings)
        assert 'Tag auto-appended' in joined or 'Warning' in joined

    def test_no_unit_boundary_fallback(self):
        text = 'Plain text without unit tags'
        missing_placeholders = {'x_1': '<x id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing_placeholders)

        assert '<x id="1"/>' in text_out
        assert '{{_OL_XTAG_' not in text_out
        assert '<note' not in text_out
        assert len(warnings) >= 1

    def test_empty_text(self):
        text_out, warnings = level4_safe_fallback('', {'x_1': '<x id="1"/>'})
        assert '<x id="1"/>' in text_out
        assert len(warnings) >= 1

    def test_empty_missing_placeholders(self):
        text = '<unit id="1">Hello</unit>'
        result = level4_safe_fallback(text, {})
        assert result == (text, [])

    def test_multiple_missing_placeholders(self):
        text = '<trans-unit id="1"><source>Test</source></trans-unit>'
        missing_placeholders = {
            'x_1': '<x id="1"/>',
            'ph_2': '<ph id="2"/>',
            'mrk_m3': '<mrk id="m3">text</mrk>',
        }
        text_out, warnings = level4_safe_fallback(text, missing_placeholders)

        assert '<x id="1"/>' in text_out
        assert '<ph id="2"/>' in text_out
        assert '<mrk id="m3">text</mrk>' in text_out
        assert len(warnings) >= 1

    def test_trans_unit_boundary(self):
        text = '<trans-unit id="1"><source>Hello</source></trans-unit>'
        missing = {'bx_1': '<bx id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        assert '<bx id="1"/>' in text_out
        assert len(warnings) >= 1
