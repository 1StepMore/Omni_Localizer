from ol_md.shield import get_placeholders_in_text, shield_markdown, unshield_markdown


class TestMDShield:
    def test_link_protection(self):
        text = 'Check [this link](https://example.com) please'
        result, shield_map = shield_markdown(text)
        assert '[OL:LINK:0000]' in result
        assert 'link_0000' in shield_map

    def test_image_protection(self):
        text = '![alt text](https://example.com/image.png)'
        result, shield_map = shield_markdown(text)
        assert '[OL:IMG:0000]' in result
        assert 'image_0000' in shield_map

    def test_html_block_protection(self):
        text = '<div class="test">content</div>'
        result, shield_map = shield_markdown(text)
        assert '[OL:HTML:0000]' in result
        assert 'html_block_0000' in shield_map

    def test_autolink_protection(self):
        text = 'Visit <https://example.com> for info'
        result, shield_map = shield_markdown(text)
        assert '[OL:AUTOLINK:0000]' in result
        assert any(k.startswith('autolink_') for k in shield_map.keys())

    def test_code_still_protected(self):
        text = 'Use `code` and $\\alpha$ expressions'
        result, shield_map = shield_markdown(text)
        assert '[OL:CODE_i:0000]' in result or '[OL:CODE:0000]' in result
        assert 'inline_code_0000' in shield_map or 'code_' in shield_map

    def test_unshield_restoration(self):
        text = 'Hello [OL:LINK:0000] world'
        shield_map = {'link_0000': '[click](https://example.com)'}
        restored = unshield_markdown(text, shield_map)
        assert '[click](https://example.com)' in restored

    def test_unshield_single_marker_happy_path(self):
        text = 'Before [OL:IMG:0000] after'
        shield_map = {'image_0000': '![Image 1](source_images/image1.png)'}
        result = unshield_markdown(text, shield_map)
        assert result == 'Before ![Image 1](source_images/image1.png) after'

    def test_unshield_duplicate_marker_does_not_duplicate_content(self):
        """LLM duplicating a shielded marker must not duplicate the restored content."""
        shield_map = {'image_0000': '![Image 1](source_images/image1.png)'}
        translated = 'Some text [OL:IMG:0000] [OL:IMG:0000] more text'
        result = unshield_markdown(translated, shield_map)
        assert result.count('![Image 1](source_images/image1.png)') == 1
        assert '[OL:IMG:0000]' not in result
        assert '![Image 1](source_images/image1.png)' in result

    def test_get_placeholders(self):
        text = 'text [OL:CODE:0000] more [OL:LINK:0001]'
        placeholders = get_placeholders_in_text(text)
        assert 'CODE' in placeholders
        assert 'LINK' in placeholders
