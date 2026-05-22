from ol_md.repair.level4 import level4_safe_fallback


class TestRepairLevel4:
    def test_append_to_sentence_end(self):
        text = 'Hello world.'
        missing = {'CODE_0000': '<code>`code`</code>', 'LINK_0001': 'https://example.com'}
        result = level4_safe_fallback(text, missing)
        assert 'OL_WARN' in result
        assert '<code>' in result
        assert 'CODE_0000' not in result

    def test_no_sentence_end(self):
        text = 'Hello world'
        missing = {'CODE_0000': '<code>`code`</code>'}
        result = level4_safe_fallback(text, missing)
        assert '<code>' in result
        assert 'CODE_0000' not in result
