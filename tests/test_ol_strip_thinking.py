"""Tests for OL output post-processing helpers.

ULTRAREADY-FIX (2026-06-08): real E2E run revealed that the LLM
leaks <think>...</think> chain-of-thought into its output, which ORF
then injects into the DOCX. These tests pin the contract that the
output is clean.
"""

from ol_pool.router import _strip_thinking_blocks


class TestStripThinkingBlocks:
    """Pin the contract that LLM chain-of-thought is stripped from output."""

    def test_strips_simple_think_block(self):
        # The actual LLM output from the real E2E run:
        text = (
            "<think>The user wants me to translate Chinese text to English "
            "while preserving all markup placeholders like {{_OL_XTAG_*_}}. "
            "Let me analyze the text: I need to translate it. "
            "I'm now working on the English translation.</think>"
            "\n\nAfter 40 years of entrepreneurial development, Haier has continued to focus on "
            "tecnological innovation and self-reliance."
        )
        result = _strip_thinking_blocks(text)
        assert "<think>" not in result
        assert "Let me analyze" not in result
        assert "I'm now working" not in result
        # The actual translation must be preserved
        assert "After 40 years of entrepreneurial development" in result
        assert "Haier has continued to focus" in result

    def test_strips_multiline_think_block(self):
        text = (
            "<think>\n"
            "The user wants me to translate.\n"
            "Let me analyze the text:\n"
            "\"<some chinese>\"\n"
            "I'm now working on the English translation.\n"
            "</think>\n"
            "\n"
            "Real translation here."
        )
        result = _strip_thinking_blocks(text)
        assert "<think>" not in result
        assert "Let me analyze" not in result
        assert "Real translation here." in result

    def test_no_think_block_passthrough(self):
        text = "No think here, just real translation text."
        assert _strip_thinking_blocks(text) == text

    def test_empty_string_passthrough(self):
        assert _strip_thinking_blocks("") == ""

    def test_multiple_think_blocks_all_stripped(self):
        text = "<think>First thought</think>Real part A<think>Second thought</think>Real part B"
        result = _strip_thinking_blocks(text)
        assert "<think>" not in result
        assert "First thought" not in result
        assert "Second thought" not in result
        # Both real parts preserved
        assert "Real part A" in result
        assert "Real part B" in result

    def test_strips_with_leading_whitespace(self):
        text = "<think>   reasoning </think>  \n\nTranslation"
        result = _strip_thinking_blocks(text)
        assert "<think>" not in result
        assert "reasoning" not in result
        assert "Translation" in result

    def test_strips_inside_inline_tags_preserves_tags(self):
        """Inline tags like <bx id="1"/> must survive; only the think content is removed."""
        text = (
            '<think>Let me think.</think>'
            '<bx id="1" type="bold"/>Hello<ex id="1"/>'
        )
        result = _strip_thinking_blocks(text)
        assert '<bx id="1" type="bold"/>' in result
        assert '<ex id="1"/>' in result
        assert "Let me think" not in result
        assert "Hello" in result
