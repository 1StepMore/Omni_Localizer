"""MD bus tests for Omni-Localizer."""
import pytest
from ol_buses.md_bus import (
    validate_md_structure,
    load_md,
    parse_md_to_tokens,
)
from ol_buses.md_shield import (
    shield_special_tokens,
    unshield_special_tokens,
)
from ol_core.dataclass import ChannelType

class TestMDBus:
    """Test MD bus functionality."""

    def test_validate_md_structure_valid(self):
        """Test validation of valid MD file."""
        assert validate_md_structure('tests/fixtures/sample.md') == True

    def test_load_md_returns_context(self):
        """Test load_md returns TranslationContext with MD channel."""
        ctx = load_md('tests/fixtures/sample.md')
        assert ctx.channel_type == ChannelType.MD
        assert ctx.file_path.endswith('.md')

    def test_parse_md_to_tokens(self):
        """Test parsing MD to tokens."""
        tokens = parse_md_to_tokens('# Hello\n\nWorld')
        assert isinstance(tokens, list)

    def test_shield_special_tokens(self):
        """Test shielding code blocks and math."""
        md = '# Hello\n\n```python\nprint("hi")\n```'
        shielded, shield_map = shield_special_tokens(md)
        assert '{{_OL_CODE_' in shielded
        assert len(shield_map) >= 1

    def test_unshield_special_tokens(self):
        """Test restoring special tokens from shield map."""
        shield_map = {'code_0000': '```python\nprint("hi")\n```'}
        translated = '# Bonjour\n\n{{_OL_CODE_0000_}}'
        restored = unshield_special_tokens(translated, shield_map)
        assert '```python' in restored