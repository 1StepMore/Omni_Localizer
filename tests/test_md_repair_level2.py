from ol_md.repair.level2 import level2_span_align


class TestRepairLevel2:
    def test_anchor_mapping_empty(self):
        # A10: returns (text, l2_applied). Don't assert l2_applied here —
        # the conftest stubs span_aligner so it's "available" in tests.
        text, _l2_applied = level2_span_align('', {}, '')
        assert text == ''

    def test_returns_text_unchanged_if_no_span_aligner(self):
        text = 'Some text with placeholders'
        result_text, _l2_applied = level2_span_align(text, {}, 'original text')
        assert result_text == text
