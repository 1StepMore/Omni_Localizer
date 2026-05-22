from ol_md.repair.level4 import level4_safe_fallback


class TestRepairLevel4:
    def test_append_to_sentence_end(self):
        text = 'Hello world.'
        missing = {'CODE_0000': 'world', 'LINK_0001': 'link'}
        result = level4_safe_fallback(text, missing)
        assert 'OL_WARN' in result

    def test_no_sentence_end(self):
        text = 'Hello world'
        missing = {'CODE_0000': 'world'}
        result = level4_safe_fallback(text, missing)
        assert 'CODE_0000' in result or 'world' in result
