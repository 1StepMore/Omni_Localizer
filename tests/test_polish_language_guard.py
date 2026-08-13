"""Tests for the source-language residual guard in the polish pass.

Verifies that polish_translated_units() and polish_md_text() skip
corrections that would revert translated text back to the source language.
"""
import logging

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestXliffPolishLanguageGuard:
    """Guard: polish_translated_units rejects source-language reverts."""

    @pytest.mark.asyncio
    async def test_zh_to_en_rejects_chinese_fix(self, caplog):
        """zh→en: correction containing Chinese characters is skipped."""
        from types import SimpleNamespace
        from ol_xliff.polish import polish_translated_units

        caplog.set_level(logging.WARNING)

        unit = SimpleNamespace(
            unit_id="u1",
            source_text="你好世界",
            target_text="Hello World",  # already correct
        )

        llm_response = (
            "id: u1\n"
            "fix: 你好 World\n"   # still has Chinese → source residual
            "reason: SPELLING: capitalize Hello"
        )

        pool = MagicMock()
        pool.translate = AsyncMock(return_value=llm_response)

        warnings = await polish_translated_units([unit], "zh", "en", pool)

        # target should NOT have changed
        assert unit.target_text == "Hello World"
        # warning should contain skip message
        assert any(
            "SKIPPED" in record.message and "u1" in record.message
            for record in caplog.records
        )
        # the correction was NOT applied so no unit-level warning
        assert "u1" not in warnings

    @pytest.mark.asyncio
    async def test_zh_to_en_rejects_chinese_fix_v2(self, caplog):
        """zh→en: correction that reverts to Chinese is skipped (variant 2)."""
        from types import SimpleNamespace
        from ol_xliff.polish import polish_translated_units

        caplog.set_level(logging.WARNING)

        unit = SimpleNamespace(
            unit_id="u2",
            source_text="今天天气很好",
            target_text="The weather is nice today",  # already correct
        )

        llm_response = (
            "id: u2\n"
            "fix: 今天天气很好\n"  # fully Chinese → source residual
            "reason: TERM_INCONSISTENCY: mixed language"
        )

        pool = MagicMock()
        pool.translate = AsyncMock(return_value=llm_response)

        warnings = await polish_translated_units([unit], "zh", "en", pool)

        # target should NOT have changed
        assert unit.target_text == "The weather is nice today"
        # warning should contain skip message
        assert any(
            "SKIPPED" in record.message and "u2" in record.message
            for record in caplog.records
        )
        assert "u2" not in warnings

    @pytest.mark.asyncio
    async def test_normal_fix_is_applied(self):
        """Correction that does NOT revert to source language is applied."""
        from types import SimpleNamespace
        from ol_xliff.polish import polish_translated_units

        unit = SimpleNamespace(
            unit_id="u1",
            source_text="hello world",
            target_text="hola mundo",
        )

        llm_response = (
            "id: u1\n"
            "fix: ¡Hola mundo!\n"
            "reason: PUNCTUATION: missing opening exclamation"
        )

        pool = MagicMock()
        pool.translate = AsyncMock(return_value=llm_response)

        warnings = await polish_translated_units([unit], "en", "es", pool)

        # fix should be applied
        assert unit.target_text == "¡Hola mundo!"
        assert "u1" in warnings
        assert "PUNCTUATION" in warnings["u1"][0]


class TestMdPolishLanguageGuard:
    """Guard: polish_md_text rejects source-language reverts."""

    @pytest.mark.asyncio
    async def test_md_zh_to_en_rejects_chinese_fix(self, caplog):
        """MD zh→en: correction with Chinese characters is skipped."""
        from ol_xliff.polish import polish_md_text

        caplog.set_level(logging.WARNING)

        text = "你好世界"
        llm_response = (
            "id: md-para-0\n"
            "fix: 你好 World\n"  # has Chinese → source residual
            "reason: TERM_INCONSISTENCY"
        )

        pool = MagicMock()
        pool.translate = AsyncMock(return_value=llm_response)

        result = await polish_md_text(text, "zh", "en", pool)

        # result should remain unchanged
        assert result == "你好世界"
        assert any(
            "SKIPPED" in record.message and "md-para-0" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_md_zh_to_en_rejects_chinese_fix_v2(self, caplog):
        """MD zh→en: correction that reverts to Chinese is skipped (variant 2)."""
        from ol_xliff.polish import polish_md_text

        caplog.set_level(logging.WARNING)

        text = "The weather is nice today"
        llm_response = (
            "id: md-para-0\n"
            "fix: 今天天气很好天气很好天气很好天气很好天气很好天气很好天气很好天气很好天气很好\n"  # fully Chinese → source residual for zh→en
            "reason: TERM_INCONSISTENCY"
        )

        pool = MagicMock()
        pool.translate = AsyncMock(return_value=llm_response)

        result = await polish_md_text(text, "zh", "en", pool)

        # result should remain unchanged
        assert result == "The weather is nice today"
        assert any(
            "SKIPPED" in record.message and "md-para-0" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_md_normal_fix_is_applied(self):
        """MD correction that does NOT revert to source language is applied."""
        from ol_xliff.polish import polish_md_text

        text = "hello world"
        llm_response = (
            "id: md-para-0\n"
            "fix: ¡Hola mundo!\n"
            "reason: PUNCTUATION: missing opening exclamation"
        )

        pool = MagicMock()
        pool.translate = AsyncMock(return_value=llm_response)

        result = await polish_md_text(text, "en", "es", pool)

        assert result == "¡Hola mundo!"
