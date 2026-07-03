"""Tests for polish_md_text() wrapper."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from ol_xliff.polish import polish_md_text


class TestPolishMdText:
    def test_polish_md_text_returns_string(self):
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="NO_ISSUES")
        result = asyncio.run(polish_md_text(
            "# Hello\n\nThis is a test paragraph.",
            "en", "zh", pool,
        ))
        assert isinstance(result, str)
        assert len(result) > 0

    def test_polish_md_text_preserves_paragraphs(self):
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="NO_ISSUES")
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        result = asyncio.run(polish_md_text(text, "en", "zh", pool))
        # Paragraphs should be rejoined with \n\n
        assert "\n\n" in result
        # Original paragraphs should all be present
        for p in ["Paragraph one.", "Paragraph two.", "Paragraph three."]:
            assert p in result

    def test_polish_md_text_empty_input(self):
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="NO_ISSUES")
        result = asyncio.run(polish_md_text("", "en", "zh", pool))
        assert result == ""

    def test_polish_md_text_single_paragraph(self):
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="NO_ISSUES")
        result = asyncio.run(polish_md_text("Just one paragraph.", "en", "zh", pool))
        assert "Just one paragraph." in result
