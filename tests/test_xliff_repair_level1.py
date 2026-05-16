"""Tests for XLIFF repair level 1 (regex cleaning)."""
import pytest
from ol_xliff.repair.level1 import level1_regex_clean


class TestRepairLevel1:
    """Test level1_regex_clean() function."""

    def test_leading_whitespace_removed(self):
        """Test that leading whitespace before placeholder is removed."""
        text = 'Hello   {{_OL_XTAG_x_1_}}'
        result, modified = level1_regex_clean(text)
        assert result == 'Hello{{_OL_XTAG_x_1_}}'
        assert modified is True

    def test_trailing_whitespace_removed(self):
        """Test that trailing whitespace after placeholder is removed."""
        text = '{{_OL_XTAG_x_1_}}   world'
        result, modified = level1_regex_clean(text)
        assert result == '{{_OL_XTAG_x_1_}}world'
        assert modified is True

    def test_non_placeholder_preserved(self):
        """Test that non-placeholder content is preserved exactly."""
        text = 'Hello world. This is a normal sentence.'
        result, modified = level1_regex_clean(text)
        assert result == text
        assert modified is False

    def test_punctuation_after_placeholder(self):
        """Test that punctuation before placeholder is moved after."""
        text = 'Hello . {{_OL_XTAG_x_1_}}'
        result, modified = level1_regex_clean(text)
        assert result == 'Hello .{{_OL_XTAG_x_1_}}'
        assert modified is True

    def test_punctuation_move_multiple(self):
        """Test punctuation move for multiple placeholders."""
        text = 'Hello . {{_OL_XTAG_x_1_}} world , {{_OL_XTAG_mrk_m1_}}'
        result, modified = level1_regex_clean(text)
        # Only first punctuation match is moved (count=1)
        assert '.{{_OL_XTAG_x_1_}}' in result

    def test_no_modification_needed(self):
        """Test text that already has proper formatting."""
        text = 'Hello{{_OL_XTAG_x_1_}}world'
        result, modified = level1_regex_clean(text)
        assert result == text
        assert modified is False

    def test_multiple_placeholders(self):
        """Test cleaning with multiple placeholders."""
        text = '   {{_OL_XTAG_x_1_}}   {{_OL_XTAG_mrk_m1_}}   '
        result, modified = level1_regex_clean(text)
        assert not result.startswith('   ')
        assert modified is True

    def test_empty_string(self):
        """Test handling of empty string."""
        text = ''
        result, modified = level1_regex_clean(text)
        assert result == ''
        assert modified is False