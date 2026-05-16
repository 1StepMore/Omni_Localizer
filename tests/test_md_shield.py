import pytest
from ol_md.shield import shield_markdown, unshield_markdown, get_placeholders_in_text


class TestMDShield:
    def test_link_protection(self):
        text = 'Check [this link](https://example.com) please'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_LINK_' in result
        assert 'link_0000' in shield_map

    def test_image_protection(self):
        text = '![alt text](https://example.com/image.png)'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_IMG_' in result
        assert 'image_0000' in shield_map

    def test_html_block_protection(self):
        text = '<div class="test">content</div>'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_HTML_' in result
        assert 'html_block_0000' in shield_map

    def test_autolink_protection(self):
        text = 'Visit <https://example.com> for info'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_AUTOLINK_' in result
        assert any(k.startswith('autolink_') for k in shield_map.keys())

    def test_code_still_protected(self):
        text = 'Use `code` and $math$ expressions'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_CODE_' in result
        assert 'inline_code_0000' in shield_map or 'code_' in shield_map

    def test_unshield_restoration(self):
        text = 'Hello \x00OL_LINK_0000\x00 world'
        shield_map = {'link_0000': '[click](https://example.com)'}
        restored = unshield_markdown(text, shield_map)
        assert '[click](https://example.com)' in restored

    def test_get_placeholders(self):
        text = 'text \x00OL_CODE_0000\x00 more \x00OL_LINK_0001\x00'
        placeholders = get_placeholders_in_text(text)
        assert 'CODE' in placeholders or 'link' in str(placeholders)