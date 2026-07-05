"""Tests for XLIFF repair level 1 (regex cleaning)."""
from ol_xliff.repair.level1 import level1_regex_clean, normalize_raw_xml_tags


class TestNormalizeRawXmlTags:
    """Test normalize_raw_xml_tags() function."""

    def test_known_x_tag_replaced(self):
        """Test that a known <x id="..."/> tag is replaced with placeholder."""
        text = 'Some text <x id="1" type="bold"/> more text'
        shield_map = {'x_1': '<x id="1" type="bold"/>'}
        result, modified = normalize_raw_xml_tags(text, shield_map)
        assert result == 'Some text {{_OL_XTAG_x_1_}} more text'
        assert modified is True

    def test_known_bx_tag_replaced(self):
        """Test that a known <bx id="..."/> tag is replaced."""
        text = '<bx id="2" type="italic"/>Hello'
        shield_map = {'bx_2': '<bx id="2" type="italic"/>'}
        result, modified = normalize_raw_xml_tags(text, shield_map)
        assert result == '{{_OL_XTAG_bx_2_}}Hello'
        assert modified is True

    def test_known_ex_tag_replaced(self):
        """Test that a known <ex id="..."/> tag is replaced."""
        text = 'World<ex id="2" type="italic"/>'
        shield_map = {'ex_2': '<ex id="2" type="italic"/>'}
        result, modified = normalize_raw_xml_tags(text, shield_map)
        assert result == 'World{{_OL_XTAG_ex_2_}}'
        assert modified is True

    def test_unknown_tag_not_replaced(self):
        """Test that a tag NOT in shield_map is left untouched."""
        text = 'Some <x id="99"/> text'
        shield_map = {'x_1': '<x id="1"/>'}
        result, modified = normalize_raw_xml_tags(text, shield_map)
        assert result == text
        assert modified is False

    def test_mixed_known_and_unknown(self):
        """Test that known tags are replaced while unknown are preserved."""
        text = '<x id="1"/> keep <bx id="2"/> <x id="99"/>'
        shield_map = {
            'x_1': '<x id="1"/>',
            'bx_2': '<bx id="2"/>',
        }
        result, modified = normalize_raw_xml_tags(text, shield_map)
        assert result == '{{_OL_XTAG_x_1_}} keep {{_OL_XTAG_bx_2_}} <x id="99"/>'
        assert modified is True

    def test_no_tags_in_text(self):
        """Test text with no raw XML tags is unchanged."""
        text = 'Hello world. This has no tags.'
        shield_map = {'x_1': '<x id="1"/>'}
        result, modified = normalize_raw_xml_tags(text, shield_map)
        assert result == text
        assert modified is False

    def test_empty_string(self):
        """Test empty string handling."""
        result, modified = normalize_raw_xml_tags('', {'x_1': '<x id="1"/>'})
        assert result == ''
        assert modified is False

    def test_tags_with_extra_attributes(self):
        """Test tags with multiple attributes are matched correctly."""
        text = 'Before <x id="5" type="bold" ctype="bold" equiv-external="bold1"/> after'
        shield_map = {'x_5': '<x id="5" type="bold" ctype="bold" equiv-external="bold1"/>'}
        result, modified = normalize_raw_xml_tags(text, shield_map)
        assert result == 'Before {{_OL_XTAG_x_5_}} after'
        assert modified is True

    def test_multiple_known_tags(self):
        """Test multiple known tags of different types."""
        text = '<bx id="1"/> text <ex id="1"/> <x id="2"/>'
        shield_map = {
            'bx_1': '<bx id="1"/>',
            'ex_1': '<ex id="1"/>',
            'x_2': '<x id="2"/>',
        }
        result, modified = normalize_raw_xml_tags(text, shield_map)
        assert result == '{{_OL_XTAG_bx_1_}} text {{_OL_XTAG_ex_1_}} {{_OL_XTAG_x_2_}}'
        assert modified is True

    def test_empty_shield_map(self):
        """Test with empty shield_map — no tags should be replaced."""
        text = '<x id="1"/> text'
        result, modified = normalize_raw_xml_tags(text, {})
        assert result == text
        assert modified is False


class TestRepairLevel1:
    """Test level1_regex_clean() function."""

    def test_leading_whitespace_removed(self):
        """Test that leading whitespace before placeholder is removed."""
        text = 'Hello   {{_OL_XTAG_x_1_}}'
        result, modified = level1_regex_clean(text)
        assert result == 'Hello{{_OL_XTAG_x_1_}}'
        assert modified is True

    def test_trailing_whitespace_removed(self):
        """Test that trailing whitespace after placeholder is removed."""
        text = '{{_OL_XTAG_x_1_}}   world'
        result, modified = level1_regex_clean(text)
        assert result == '{{_OL_XTAG_x_1_}}world'
        assert modified is True

    def test_non_placeholder_preserved(self):
        """Test that non-placeholder content is preserved exactly."""
        text = 'Hello world. This is a normal sentence.'
        result, modified = level1_regex_clean(text)
        assert result == text
        assert modified is False

    def test_punctuation_after_placeholder(self):
        """Test that punctuation before placeholder is moved after."""
        text = 'Hello . {{_OL_XTAG_x_1_}}'
        result, modified = level1_regex_clean(text)
        assert result == 'Hello .{{_OL_XTAG_x_1_}}'
        assert modified is True

    def test_punctuation_move_multiple(self):
        """Test punctuation move for multiple placeholders."""
        text = 'Hello . {{_OL_XTAG_x_1_}} world , {{_OL_XTAG_mrk_m1_}}'
        result, modified = level1_regex_clean(text)
        # Only first punctuation match is moved (count=1)
        assert '.{{_OL_XTAG_x_1_}}' in result

    def test_no_modification_needed(self):
        """Test text that already has proper formatting."""
        text = 'Hello{{_OL_XTAG_x_1_}}world'
        result, modified = level1_regex_clean(text)
        assert result == text
        assert modified is False

    def test_multiple_placeholders(self):
        """Test cleaning with multiple placeholders."""
        text = '   {{_OL_XTAG_x_1_}}   {{_OL_XTAG_mrk_m1_}}   '
        result, modified = level1_regex_clean(text)
        assert not result.startswith('   ')
        assert modified is True

    def test_empty_string(self):
        """Test handling of empty string."""
        text = ''
        result, modified = level1_regex_clean(text)
        assert result == ''
        assert modified is False

    # — Shield-map integration tests —

    def test_with_shield_map_normalizes_xml_tags(self):
        """Test that shield_map triggers raw XML tag normalization."""
        text = 'Hello <x id="1" type="bold"/> world'
        shield_map = {'x_1': '<x id="1" type="bold"/>'}
        result, modified = level1_regex_clean(text, shield_map)
        # Both normalization and whitespace cleaning apply:
        #   normalization: <x id="1".../> → {{_OL_XTAG_x_1_}}
        #   whitespace clean: removes space before {{ (after Hello) and after }}
        assert result == 'Hello{{_OL_XTAG_x_1_}}world'
        assert modified is True

    def test_with_shield_map_no_tags(self):
        """Test shield_map with no raw XML tags in text."""
        text = 'Hello {{_OL_XTAG_x_1_}} world'
        shield_map = {'x_1': '<x id="1" type="bold"/>'}
        result, modified = level1_regex_clean(text, shield_map)
        assert result == 'Hello{{_OL_XTAG_x_1_}}world'
        assert modified is True

    def test_with_shield_map_unknown_tags_untouched(self):
        """Test shield_map with tags not in map — they remain as raw XML."""
        text = '<x id="99"/> text'
        shield_map = {'x_1': '<x id="1"/>'}
        result, modified = level1_regex_clean(text, shield_map)
        # No normalization happens (id 99 not in map), but whitespace around
        # existing placeholders could still be modified
        assert result == '<x id="99"/> text'
        assert modified is False

    def test_with_shield_map_and_whitespace_cleaning(self):
        """Test that both normalization and whitespace cleaning work together."""
        text = '  <bx id="1"/>   Hello   {{_OL_XTAG_ex_1_}}'
        shield_map = {
            'bx_1': '<bx id="1"/>',
            'ex_1': '<ex id="1"/>',
        }
        result, modified = level1_regex_clean(text, shield_map)
        assert '{{_OL_XTAG_bx_1_}}' in result
        assert '{{_OL_XTAG_ex_1_}}' in result
        assert modified is True

    def test_with_shield_map_empty_string(self):
        """Test shield_map with empty string."""
        result, modified = level1_regex_clean('', {'x_1': '<x id="1"/>'})
        assert result == ''
        assert modified is False

    def test_backward_compatible_no_shield_map(self):
        """Test that calling without shield_map still works (backward compat)."""
        text = 'Hello{{_OL_XTAG_x_1_}}world'
        result, modified = level1_regex_clean(text)
        assert result == text
        assert modified is False

    def test_backward_compatible_whitespace(self):
        """Test that existing behavior without shield_map is unchanged."""
        text = 'Hello   {{_OL_XTAG_x_1_}}'
        result, modified = level1_regex_clean(text)
        assert result == 'Hello{{_OL_XTAG_x_1_}}'
        assert modified is True
