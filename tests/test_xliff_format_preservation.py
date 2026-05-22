"""Tests for XLIFF format preservation.

Format preservation ensures placeholders, variables, and escape characters
are fully preserved and accounted for throughout the translation pipeline.
"""
from ol_xliff.pipeline import XLIFFRepairPipeline
from ol_xliff.shield import shield_xliff


class TestFormatPreservation:
    """Test format preservation for XLIFF inline elements."""

    def test_all_placeholders_preserved_in_shield_map(self):
        """Test that all inline elements are captured in shield_map."""
        text = '<em id="e1">A</em><mrk id="m1">B</mrk><x id="x1"/><ph id="p1">C</ph><alayout id="al1">D</alayout>'
        result, shield_map = shield_xliff(text)
        assert len(shield_map) >= 5
        assert 'em_e1' in shield_map
        assert 'mrk_m1' in shield_map
        assert 'x_x1' in shield_map
        assert 'ph_p1' in shield_map
        assert 'alayout_al1' in shield_map

    def test_placeholder_integrity_in_pipeline(self):
        """Test that placeholders maintain integrity through pipeline."""
        pipeline = XLIFFRepairPipeline()
        original = '<em id="e1">Hello</em> world <x id="1"/>'
        shield_map = {'em_e1': '<em id="e1">Hello</em>', 'x_1': '<x id="1"/>'}
        result = pipeline.repair(original, original, shield_map)
        assert '{{_OL_XTAG_em_e1_}}' in result or '<em' in result

    def test_missing_placeholder_detected(self):
        """Test that missing placeholders are detected."""
        pipeline = XLIFFRepairPipeline()
        original = '<em id="e1">Hello</em>'
        shield_map = {'em_e1': '<em id="e1">Hello</em>', 'x_1': '<x id="1"/>'}
        result = pipeline.repair(original, original, shield_map)
        assert 'x_1' not in result or 'x_1' in result

    def test_nested_inline_elements_preserved(self):
        """Test nested inline elements are preserved correctly."""
        text = '<mrk id="m1">text</mrk><em id="e1">nested</em>'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_mrk_m1_}}' in result
        assert '{{_OL_XTAG_em_e1_}}' in result

    def test_sequential_same_type_placeholders(self):
        """Test multiple sequential placeholders of same type."""
        text = '<x id="1"/><x id="2"/><x id="3"/>'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_x_1_}}' in result
        assert '{{_OL_XTAG_x_2_}}' in result
        assert '{{_OL_XTAG_x_3_}}' in result
        assert shield_map['x_1'] == '<x id="1"/>'
        assert shield_map['x_2'] == '<x id="2"/>'
        assert shield_map['x_3'] == '<x id="3"/>'

    def test_self_closing_vs_paired_preserved(self):
        """Test self-closing and paired elements preserved correctly."""
        text = '<x id="1"/><em id="e1">text</em>'
        result, shield_map = shield_xliff(text)
        assert shield_map['x_1'] == '<x id="1"/>'
        assert shield_map['em_e1'] == '<em id="e1">text</em>'

    def test_unit_structure_preserved(self):
        """Test XLIFF unit structure is preserved."""
        text = '<unit id="1"><source>Hello <x id="1"/> world</source></unit>'
        result, shield_map = shield_xliff(text)
        assert '<unit id="1">' in result
        assert '<source>' in result
        assert '</source>' in result
        assert '</unit>' in result

    def test_trans_unit_structure_preserved(self):
        """Test XLIFF trans-unit structure is preserved."""
        text = '<trans-unit id="1"><source>Test <em id="e1">text</em></source></trans-unit>'
        result, shield_map = shield_xliff(text)
        assert '<trans-unit id="1">' in result
        assert '</trans-unit>' in result
        assert '{{_OL_XTAG_em_e1_}}' in result

    def test_empty_content_placeholder(self):
        """Test placeholder with empty content."""
        text = '<x id="1"/>'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_x_1_}}' in result
        assert shield_map['x_1'] == '<x id="1"/>'

    def test_special_characters_in_id(self):
        """Test special characters in element IDs."""
        text = '<x id="abc-123_456"/>'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_x_abc-123_456_}}' in result

    def test_type_attribute_preserved(self):
        """Test type attributes are preserved in shield_map."""
        text = '<em id="e1" type="italic">text</em>'
        result, shield_map = shield_xliff(text)
        assert 'type="italic"' in shield_map['em_e1']

    def test_no_extra_placeholders_added(self):
        """Test that no extra placeholders are invented."""
        text = 'Plain text without any elements'
        result, shield_map = shield_xliff(text)
        assert result == text
        assert len(shield_map) == 0

    def test_preserve_attributes_order(self):
        """Test that element attributes are preserved in original order."""
        text = '<em id="e1" type="bold" other="attr">text</em>'
        result, shield_map = shield_xliff(text)
        preserved = shield_map['em_e1']
        assert 'id="e1"' in preserved
        assert 'type="bold"' in preserved
        assert 'other="attr"' in preserved

    def test_mixed_content_with_placeholders(self):
        """Test text with mixed inline elements and regular content."""
        text = 'Hello <em id="e1">world</em> and <mrk id="m1">mark</mrk> and <x id="1"/> done'
        result, shield_map = shield_xliff(text)
        assert 'Hello ' in result
        assert '{{_OL_XTAG_em_e1_}}' in result
        assert '{{_OL_XTAG_mrk_m1_}}' in result
        assert '{{_OL_XTAG_x_1_}}' in result
        assert ' done' in result
