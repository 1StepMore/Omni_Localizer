from ol_md.repair.level2 import level2_span_align


class TestRepairLevel2:
    def test_anchor_mapping_empty(self):
        result = level2_span_align('', {}, '')
        assert result == ''

    def test_returns_text_unchanged_if_no_span_aligner(self):
        text = 'Some text with placeholders'
        result = level2_span_align(text, {}, 'original text')
        assert result == text
