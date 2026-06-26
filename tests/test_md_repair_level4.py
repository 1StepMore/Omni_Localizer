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


class TestRepairLevel4PositionInsertion:
    def test_missing_placeholder_inserted_near_surviving_marker(self):
        text = 'See [OL:CODE:0000] for details. More text follows here.'
        missing = {'link_0001': 'https://example.com'}
        result = level4_safe_fallback(text, missing)

        assert 'https://example.com' in result
        assert 'OL_WARN' in result
        link_pos = result.index('https://example.com')
        warn_pos = result.index('OL_WARN')
        assert link_pos < warn_pos, (
            "Missing placeholder should be inserted before the OL_WARN comment, "
            f"but link at pos {link_pos} is after OL_WARN at pos {warn_pos}"
        )

    def test_no_surviving_markers_falls_back_to_append(self):
        text = 'Hello world.'
        missing = {'code_0000': '<code>`code`</code>'}
        result = level4_safe_fallback(text, missing)
        assert '<code>`code`</code>' in result
        assert 'OL_WARN' in result

    def test_empty_text_appends(self):
        missing = {'code_0000': '<code>`code`</code>'}
        result = level4_safe_fallback('', missing)
        assert '<code>`code`</code>' in result
        assert 'OL_WARN' in result

    def test_no_missing_placeholders(self):
        result = level4_safe_fallback('Hello world.', {})
        assert 'Hello world.' in result
        assert 'OL_WARN' in result

    def test_multiple_missing_near_surviving_marker(self):
        text = 'See [OL:CODE:0000] and [OL:CODE:0001] here. End of text follows.'
        missing = {
            'link_0000': 'https://a.com',
            'image_0000': '![img](pic.png)',
        }
        result = level4_safe_fallback(text, missing)
        assert 'https://a.com' in result
        assert '![img](pic.png)' in result
        assert 'OL_WARN' in result

    def test_missing_content_not_appended_after_all_trailing_text(self):
        text = 'Prefix [OL:LINK:0000] middle. ' + 'x' * 200
        missing = {'code_0000': '<code>test</code>'}
        result = level4_safe_fallback(text, missing)

        code_pos = result.index('<code>test</code>')
        trailing_start = result.index('x' * 200)
        assert code_pos < trailing_start, (
            f"Missing placeholder at pos {code_pos} should be before "
            f"trailing text at pos {trailing_start}"
        )
