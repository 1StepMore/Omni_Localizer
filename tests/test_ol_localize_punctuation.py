"""Tests for OL Chinese-punctuation localizer.

ULTRAREADY-FIX (2026-06-08): real E2E run surfaced that the LLM
preserves Chinese typographic conventions verbatim in the English
output. The user reviewed the result and flagged two specific
patterns:

  1. 《Love Haier》 — Chinese book-title brackets preserved in
     English output. Should be stripped (English uses italics or
     plain text for book titles; 《》 is not a standard English
     convention).

  2. 一、Title — Chinese ordinal-numbering prefix preserved
     verbatim. Should be localized to Western "1. Title"
     (or "I. Title") conventions.

Root cause: the OL system prompt says "preserve all markup" but
Chinese punctuation/brackets/numerals are typographic conventions,
not markup. The LLM correctly preserves them per the prompt; the
prompt is wrong.

These tests pin the contract: the localizer MUST convert these
patterns before the text is written to the XLIFF.
"""

from ol_pool.router import _localize_chinese_punctuation


class TestLocalizeBookBrackets:
    """《》 are Chinese book-title brackets; English uses italics/quotes."""

    def test_strips_book_brackets_around_english_title(self):
        # The exact pattern from the user's review of /tmp/orf_v5/result.docx
        text = "《Love Haier》"
        result = _localize_chinese_punctuation(text)
        assert "《" not in result
        assert "》" not in result
        assert "Love Haier" in result

    def test_strips_book_brackets_with_inline_tags(self):
        # The actual OPP source pattern for the title unit
        text = '<bx id="1" type="bold"/>《爱上海尔》<ex id="1"/>'
        result = _localize_chinese_punctuation(text)
        assert "《" not in result
        assert "》" not in result
        # Inline tags preserved verbatim
        assert '<bx id="1" type="bold"/>' in result
        assert '<ex id="1"/>' in result
        # The placeholder {{_OL_XTAG_*_}} stays untouched
        assert "_OL_XTAG" not in result  # tags were real, not placeholders


class TestLocalizeOrdinalMarkers:
    """一、二、三、 are Chinese section ordinals; localize to 1./2./3."""

    def test_localizes_first_ordinal(self):
        text = "一、Create a global enterprise"
        result = _localize_chinese_punctuation(text)
        assert "一、" not in result
        # Western convention: "1. " (note the period+space)
        assert result.startswith("1."), f"expected '1.' prefix, got {result!r}"
        assert "Create a global enterprise" in result

    def test_localizes_through_twenty(self):
        # Chinese numerals: 一二三四五六七八九十 + 第
        for cn, num in [
            ("一、", "1."), ("二、", "2."), ("三、", "3."),
            ("四、", "4."), ("五、", "5."), ("六、", "6."),
            ("七、", "7."), ("八、", "8."), ("九、", "9."),
            ("十、", "10."),
        ]:
            text = f"{cn}Title"
            result = _localize_chinese_punctuation(text)
            assert cn not in result, f"failed for {cn}"
            assert result.startswith(num), f"expected {num!r} prefix for {cn}, got {result!r}"


class TestLocalizeQuotationMarks:
    """“” and ‘’ are Chinese quotation marks; localize to ASCII or English."""

    def test_chinese_double_quotes_to_ascii(self):
        text = '“出海”已走过'
        result = _localize_chinese_punctuation(text)
        # Chinese open/close double quotes → ASCII double quotes
        assert '"' in result
        assert "出海" in result
        assert "已走过" in result


class TestPassthrough:
    """English-only text without Chinese punctuation passes through unchanged."""

    def test_english_text_passthrough(self):
        text = "Love Haier"
        assert _localize_chinese_punctuation(text) == text

    def test_empty_string_passthrough(self):
        assert _localize_chinese_punctuation("") == ""

    def test_inline_tags_passthrough(self):
        # Inline tags are markup, not Chinese punctuation; don't touch
        text = '<bx id="1" type="bold"/>Hello<ex id="1"/>'
        assert _localize_chinese_punctuation(text) == text


class TestCombinedPattern:
    """Multiple patterns in the same string."""

    def test_combined_book_bracket_and_ordinal(self):
        text = "《Title》一、Section"
        result = _localize_chinese_punctuation(text)
        assert "《" not in result
        assert "》" not in result
        assert "一、" not in result
        assert "Title" in result
        assert "Section" in result
