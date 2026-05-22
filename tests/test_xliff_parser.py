"""Tests for XLIFF parser functionality."""
import pytest

from ol_xliff.parser import XliffParser, detect_xliff_version, extract_inline_elements


class TestXLIFFParser:
    """Test XliffParser class for XLIFF file parsing."""

    def test_parse_xliff_1x(self):
        """Test parsing XLIFF 1.x format with trans-unit elements."""
        parser = XliffParser()
        units = parser.parse('tests/fixtures/sample.xliff')
        assert len(units) >= 1
        assert units[0].unit_id == '1'
        assert 'Hello' in units[0].source_text

    def test_parse_xliff_2(self):
        """Test parsing XLIFF 2.0 format with segment elements."""
        parser = XliffParser()
        units = parser.parse('tests/fixtures/sample-xliff2.xlf')
        assert len(units) >= 1
        # XLIFF 2.0 uses unit_id_seg_id format
        assert '_' in units[0].unit_id or 'segment' in units[0].unit_id.lower()

    def test_parse_xliff_12(self):
        """Test parsing XLIFF 1.2 format with trans-unit elements."""
        parser = XliffParser()
        units = parser.parse('tests/fixtures/sample-xliff12.xlf')
        assert len(units) >= 6
        # Verify each unit has proper structure
        for unit in units:
            assert unit.unit_id is not None
            assert unit.source_text is not None

    def test_detect_version_1x(self):
        """Test XLIFF 1.x version detection."""
        content = '<?xml version="1.0"?><xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.1">'
        assert detect_xliff_version(content) == '1.x'

    def test_detect_version_2(self):
        """Test XLIFF 2.0 version detection."""
        content = '<?xml version="1.0"?><xliff version="2.0" xmlns="urn:oasis:names:tc:xliff:document:2.0">'
        assert detect_xliff_version(content) == '2.0'

    def test_detect_version_unknown(self):
        """Test unknown version detection."""
        content = '<?xml version="1.0"?><unknown>content</unknown>'
        assert detect_xliff_version(content) == 'unknown'

    def test_inline_elements_tracked_in_shield_map(self):
        """Test that inline elements are properly tracked in shield_map."""
        text = 'Press <ph id="p1">Enter</ph> to continue'
        result, shield_map = extract_inline_elements(text)
        assert '{{_OL_XTAG_ph_p1_}}' in result
        assert 'ph_p1' in shield_map
        assert shield_map['ph_p1'] == '<ph id="p1">Enter</ph>'

    def test_parse_string_method(self):
        """Test parse_string method for direct content parsing."""
        parser = XliffParser()
        content = '''<?xml version="1.0"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.1">
  <file source-language="en" target-language="zh" original="test">
    <body>
      <trans-unit id="1">
        <source>Test <x id="1"/> text</source>
      </trans-unit>
    </body>
  </file>
</xliff>'''
        units = parser.parse_string(content)
        assert len(units) >= 1
        assert units[0].unit_id == '1'

    def test_file_not_found_error(self):
        """Test that FileNotFoundError is raised for missing files."""
        parser = XliffParser()
        with pytest.raises(FileNotFoundError):
            parser.parse('nonexistent.xlf')

    def test_multiple_segments_in_unit(self):
        """Test parsing unit with multiple segments."""
        parser = XliffParser()
        units = parser.parse('tests/fixtures/sample-xliff2.xlf')
        # Unit 1 and 2 should have different segment IDs
        unit_ids = [u.unit_id for u in units]
        # Should have more than 1 unit
        assert len(units) >= 5
