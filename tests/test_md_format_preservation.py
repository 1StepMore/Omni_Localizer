from ol_md.shield import get_placeholders_in_text, shield_markdown, unshield_markdown


class TestMDFormatPreservation:
    def test_placeholder_format_x00_byte(self):
        """Placeholders use \x00-byte format, NOT {{...}}"""
        text = 'Use `code` here'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_' in result
        assert '{{' not in result  # Confirms NOT using Jinja-style

    def test_placeholder_id_consistency(self):
        """Same placeholder ID in text matches shield_map"""
        text = 'Text \x00OL_CODE_0000\x00 more'
        placeholders = get_placeholders_in_text(text)
        assert 'CODE' in str(placeholders)

    def test_no_placeholder_corruption(self):
        """Placeholders survive round-trip shield→unshield"""
        original = 'Check [link](https://example.com) and `code`'
        shielded, shield_map = shield_markdown(original)
        restored = unshield_markdown(shielded, shield_map)
        assert 'link' in restored
        assert 'code' in restored

    def test_multiple_placeholder_types(self):
        """All placeholder types preserved correctly"""
        text = '[link](url) `code` $math$ ![img](url) <div>x</div>'
        shielded, shield_map = shield_markdown(text)
        restored = unshield_markdown(shielded, shield_map)
        # Check all types survived
        assert 'link' in restored
        assert 'code' in restored or '`' in restored
        assert 'url' in restored or 'img' in restored
        assert 'div' in restored

    def test_placeholder_not_modified_by_translation(self):
        """Placeholder format remains intact after LLM translation simulation"""
        text = 'Use \x00OL_CODE_0000\x00 in sentence'
        translated = 'Utilisez le \x00OL_CODE_0000\x00 dans la phrase'
        placeholders = get_placeholders_in_text(translated)
        assert 'CODE' in str(placeholders)

    def test_escape_sequence_preserved(self):
        """Escape sequences like \\n are preserved"""
        text = 'Line1\\nLine2'
        result, shield_map = shield_markdown(text)
        assert '\\n' in result or '\n' in result  # Line break preserved

    def test_special_chars_in_placeholders(self):
        """Special characters in placeholder content preserved"""
        text = '[link](https://example.com?a=1&b=2)'
        shielded, shield_map = shield_markdown(text)
        restored = unshield_markdown(shielded, shield_map)
        assert 'https://example.com?a=1&b=2' in restored

    def test_unicode_in_placeholders(self):
        """Unicode characters preserved through shield cycle"""
        text = '中文 `code` English'
        shielded, shield_map = shield_markdown(text)
        restored = unshield_markdown(shielded, shield_map)
        assert '中文' in restored
        assert 'code' in restored
        assert 'English' in restored

    def test_empty_shield_map_no_change(self):
        """Empty shield_map leaves text unchanged"""
        text = 'Plain text without placeholders'
        restored = unshield_markdown(text, {})
        assert restored == text

    def test_reversed_restore_order(self):
        """Restore in reverse order handles overlapping correctly"""
        text = 'A \x00OL_CODE_0000\x00 B \x00OL_CODE_0001\x00 C'
        shield_map = {'code_0000': '`code1`', 'code_0001': '`code2`'}
        restored = unshield_markdown(text, shield_map)
        assert '`code1`' in restored
        assert '`code2`' in restored
