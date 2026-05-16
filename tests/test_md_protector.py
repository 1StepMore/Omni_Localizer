import pytest
from ol_md.shield import shield_markdown, unshield_markdown


class TestMDProtector:
    def test_fence_protection(self):
        text = '```python\nprint("hello")\n```'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_CODE_' in result
        assert 'code_0000' in shield_map

    def test_inline_code_protection(self):
        text = 'Use `inline code` here'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_CODE_i' in result
        assert 'inline_code_0000' in shield_map

    def test_math_block_protection(self):
        text = '$$E = mc^2$$'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_MATH_' in result
        assert 'math_0000' in shield_map

    def test_math_inline_protection(self):
        text = 'Formula $x^2$ here'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_MATH_' in result

    def test_link_protection(self):
        text = 'Check [this](https://example.com) please'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_LINK_' in result
        assert 'link_0000' in shield_map

    def test_image_protection(self):
        text = '![alt](https://example.com/img.png)'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_IMG_' in result
        assert 'image_0000' in shield_map

    def test_html_block_protection(self):
        text = '<div class="test">content</div>'
        result, shield_map = shield_markdown(text)
        assert '\x00OL_HTML_' in result
        assert 'html_block_0000' in shield_map

    def test_multiple_protected_elements(self):
        text = '# Title\n\nParagraph with `code` and $math$\n\n![img](url)\n\n```code block```'
        result, shield_map = shield_markdown(text)
        assert result.count('\x00OL_') >= 3

    def test_preserve_non_protectable(self):
        text = 'Plain text without special elements'
        result, shield_map = shield_markdown(text)
        assert result == text
        assert len(shield_map) == 0

    def test_nested_markers_fail_gracefully(self):
        text = '`code with $inside$`'
        result, shield_map = shield_markdown(text)
        # Should protect the outer code, inner math handled appropriately
        assert '\x00OL_CODE_' in result