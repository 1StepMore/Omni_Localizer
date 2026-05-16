import pytest
from ol_md.repair.level1 import level1_regex_clean


class TestRepairLevel1:
    def test_remove_leading_whitespace(self):
        text = 'Hello   \x00OL_CODE_0000\x00'
        result, modified = level1_regex_clean(text)
        assert '\x00OL_CODE_0000\x00' in result

    def test_remove_trailing_whitespace(self):
        text = '\x00OL_CODE_0000\x00   world'
        result, modified = level1_regex_clean(text)
        assert '\x00OL_CODE_0000\x00' in result

    def test_non_placeholder_preserved(self):
        text = 'Hello world. This is a normal sentence.'
        result, modified = level1_regex_clean(text)
        assert result == text
        assert modified == False