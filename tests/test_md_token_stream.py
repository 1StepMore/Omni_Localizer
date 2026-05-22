from ol_md.token_stream import TokenPositionTracker


class TestMDTokenStream:
    def test_validate_balance(self):
        from markdown_it import MarkdownIt
        md = MarkdownIt()
        tokens = md.parse('# Hello\n\nParagraph with `code`.')
        tracker = TokenPositionTracker(tokens)
        assert tracker.validate_balance() == True

    def test_rebuild_produces_markdown(self):
        from markdown_it import MarkdownIt

        from ol_core.dataclass import TranslationUnit
        md = MarkdownIt()
        original = '# Hello\n\nParagraph text.'
        tokens = md.parse(original)
        units = [TranslationUnit(unit_id='u1', source_text='Hello', target_text='世界')]
        rebuilt = TokenPositionTracker.rebuild(tokens, units)
        assert isinstance(rebuilt, str)

    def test_self_closing_tokens(self):
        from markdown_it import MarkdownIt
        md = MarkdownIt()
        tokens = md.parse('Inline `code` and ![alt](img.png)')
        tracker = TokenPositionTracker(tokens)
        self_closing = [t for t in tracker.tokens if t.nesting == 0]
        assert len(self_closing) >= 2
