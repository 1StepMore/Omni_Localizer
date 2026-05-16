"""XLIFF bus tests for Omni-Localizer."""
import pytest
from pathlib import Path
from ol_buses.xliff_bus import (
    validate_xliff_structure,
    load_xliff,
    iterate_trans_units,
)
from ol_buses.xliff_shield import (
    extract_tags,
    replace_tags_with_placeholders,
    restore_tags,
)
from ol_core.dataclass import ChannelType

class TestXLIFFBus:
    """Test XLIFF bus functionality."""

    def test_validate_xliff_structure_valid(self):
        """Test validation of valid XLIFF file."""
        assert validate_xliff_structure('tests/fixtures/sample.xliff') == True

    def test_validate_xliff_structure_invalid(self):
        """Test validation of invalid XLIFF file."""
        assert validate_xliff_structure('tests/fixtures/sample.md') == False

    def test_load_xliff_returns_context(self):
        """Test load_xliff returns TranslationContext with XLIFF channel."""
        ctx = load_xliff('tests/fixtures/sample.xliff')
        assert ctx.channel_type == ChannelType.XLIFF
        assert ctx.file_path.endswith('.xliff')

    def test_load_xliff_has_units(self):
        """Test XLIFF loading produces translation units."""
        ctx = load_xliff('tests/fixtures/sample.xliff')
        assert len(ctx.units) >= 1

    def test_iterate_trans_units(self):
        """Test iterating trans-units from XLIFF."""
        units = list(iterate_trans_units(Path('tests/fixtures/sample.xliff')))
        assert len(units) >= 1
        assert all(u.unit_id for u in units)

    def test_extract_tags(self):
        """Test tag extraction from XLIFF XML."""
        xml = '<seg>Hello <x id="1" type="bold"/> world</seg>'
        tags = extract_tags(xml)
        assert len(tags) >= 1

    def test_replace_tags_with_placeholders(self):
        """Test tag replacement with placeholders."""
        xml = '<x id="1"/>'
        text, shield = replace_tags_with_placeholders(xml)
        assert '{{_OL_XTAG_' in text
        assert len(shield) >= 1

    def test_restore_tags(self):
        """Test tag restoration from placeholders."""
        shield_map = {'x_1': '<x id="1"/>'}
        translated = 'Bonjour {{_OL_XTAG_x_1_}} world'
        restored = restore_tags(translated, shield_map)
        assert '<x' in restored