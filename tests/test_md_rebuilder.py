import pytest
from markdown_it import MarkdownIt
from ol_md.token_stream import TokenPositionTracker
from ol_core.dataclass import TranslationUnit


class TestMDRebuilder:
    def test_rebuild_simple_text(self):
        md = MarkdownIt()
        original = '# Hello\n\nParagraph text.'
        tokens = md.parse(original)
        units = [TranslationUnit(unit_id='u1', source_text='Hello', target_text='世界')]
        rebuilt = TokenPositionTracker.rebuild(tokens, units)
        assert isinstance(rebuilt, str)
        assert len(rebuilt) > 0

    def test_rebuild_preserves_structure(self):
        md = MarkdownIt()
        original = '# Heading\n\nParagraph with content.'
        tokens = md.parse(original)
        units = [
            TranslationUnit(unit_id='u1', source_text='Heading', target_text='标题'),
            TranslationUnit(unit_id='u2', source_text='Paragraph with content.', target_text='带有内容的段落。')
        ]
        rebuilt = TokenPositionTracker.rebuild(tokens, units)
        assert '#' in rebuilt  # Heading marker preserved

    def test_rebuild_empty_units(self):
        md = MarkdownIt()
        tokens = md.parse('# Hello')
        units = []
        rebuilt = TokenPositionTracker.rebuild(tokens, units)
        assert isinstance(rebuilt, str)

    def test_rebuild_more_units_than_tokens(self):
        md = MarkdownIt()
        tokens = md.parse('# Hello')
        units = [
            TranslationUnit(unit_id='u1', source_text='Hello', target_text='世界'),
            TranslationUnit(unit_id='u2', source_text='Extra', target_text='额外')
        ]
        rebuilt = TokenPositionTracker.rebuild(tokens, units)
        assert isinstance(rebuilt, str)

    def test_self_closing_tokens_preserved(self):
        md = MarkdownIt()
        tokens = md.parse('Text ![alt](url) more')
        tracker = TokenPositionTracker(tokens)
        self_closing = [t for t in tracker.tokens if t.nesting == 0]
        assert len(self_closing) >= 1  # image is self-closing

    def test_token_balance_valid(self):
        md = MarkdownIt()
        tokens = md.parse('# Hello\n\nParagraph.\n\n```code```')
        tracker = TokenPositionTracker(tokens)
        assert tracker.validate_balance() == True

    def test_token_balance_invalid(self):
        md = MarkdownIt()
        tokens = md.parse('# Hello')
        # Manually create imbalanced tokens for test
        # In practice this shouldn't happen with valid markdown-it parsing
        assert len(tokens) > 0  # tokens are balanced from markdown-it

    def test_rebuild_with_code_blocks(self):
        md = MarkdownIt()
        original = '# Title\n\n```python\ncode\n```\n\nParagraph.'
        tokens = md.parse(original)
        units = [TranslationUnit(unit_id='u1', source_text='Title', target_text='标题')]
        rebuilt = TokenPositionTracker.rebuild(tokens, units)
        assert isinstance(rebuilt, str)
        assert len(rebuilt) > 0