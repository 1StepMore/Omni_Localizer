"""TDD unit tests for self_reflect module (Gate 8, Issue #64)."""
from __future__ import annotations

import pytest

from ol_core.dataclass import TranslationUnit
from ol_xliff.self_reflect import (
    _build_self_reflect_prompt,
    _parse_self_reflect_response,
    self_reflect_md_text,
    self_reflect_translated_units,
)


class TestBuildSelfReflectPrompt:
    """Unit tests for _build_self_reflect_prompt()."""

    def test_basic_prompt_structure(self) -> None:
        pairs = [{"id": "u1", "src": "Hello", "tgt": "你好"}]
        prompt = _build_self_reflect_prompt(pairs)
        assert "id: u1" in prompt
        assert "src: Hello" in prompt
        assert "tgt: 你好" in prompt
        assert "NO_ISSUES" in prompt

    def test_with_warnings(self) -> None:
        pairs = [{"id": "u1", "src": "Hello", "tgt": "Hello", "warnings": "OL_WARN: SOURCE_COPY"}]
        prompt = _build_self_reflect_prompt(pairs)
        assert "quality_gate_warnings" in prompt
        assert "SOURCE_COPY" in prompt

    def test_without_src(self) -> None:
        pairs = [{"id": "u1", "src": "", "tgt": "你好世界"}]
        prompt = _build_self_reflect_prompt(pairs)
        assert "id: u1" in prompt
        assert "tgt: 你好世界" in prompt


class TestParseSelfReflectResponse:
    """Unit tests for _parse_self_reflect_response()."""

    def test_no_issues(self) -> None:
        assert _parse_self_reflect_response("NO_ISSUES") == []

    def test_empty_response(self) -> None:
        assert _parse_self_reflect_response("") == []

    def test_single_correction(self) -> None:
        response = (
            "id: u1\n"
            "fix: Bonjour le monde\n"
            "reason: improved greeting\n"
        )
        corrections = _parse_self_reflect_response(response)
        assert len(corrections) == 1
        assert corrections[0]["id"] == "u1"
        assert corrections[0]["fix"] == "Bonjour le monde"
        assert corrections[0]["reason"] == "improved greeting"

    def test_multiple_corrections(self) -> None:
        response = (
            "id: u1\n"
            "fix: Bonjour\n"
            "reason: greeting\n"
            "\n"
            "id: u2\n"
            "fix: Au revoir\n"
            "reason: farewell\n"
        )
        corrections = _parse_self_reflect_response(response)
        assert len(corrections) == 2

    def test_fallback_parsing(self) -> None:
        """Non-standard whitespace still parses via fallback path."""
        response = "id: u1\nfix: Bonjour\nreason: greeting"
        corrections = _parse_self_reflect_response(response)
        assert len(corrections) == 1
        assert corrections[0]["id"] == "u1"

    def test_no_corrections_found(self) -> None:
        assert _parse_self_reflect_response("Some random text without format") == []


class TestSelfReflectTranslatedUnits:
    """Integration tests for self_reflect_translated_units()."""

    @pytest.mark.asyncio
    async def test_no_issues_found(self) -> None:
        units = [
            TranslationUnit(
                unit_id="u1", source_text="Hello", target_text="你好",
                shield_map={},
            ),
        ]
        pool = MockEmptyPool()
        result = await self_reflect_translated_units(units, "en", "zh", pool)
        assert result == {}

    @pytest.mark.asyncio
    async def test_correction_applied(self) -> None:
        units = [
            TranslationUnit(
                unit_id="u1", source_text="Hello", target_text="你好",
                shield_map={},
            ),
        ]
        pool = FakeResponsePool(
            "id: u1\nfix: 您好\nreason: more polite greeting\n"
        )
        result = await self_reflect_translated_units(units, "en", "zh", pool)
        assert "u1" in result
        assert units[0].target_text == "您好"

    @pytest.mark.asyncio
    async def test_skip_when_no_target(self) -> None:
        units = [
            TranslationUnit(
                unit_id="u1", source_text="Hello", target_text=None,
                shield_map={},
            ),
        ]
        pool = FakeResponsePool(
            "id: u1\nfix: 您好\nreason: greeting\n"
        )
        result = await self_reflect_translated_units(units, "en", "zh", pool)
        assert result == {}

    @pytest.mark.asyncio
    async def test_budget_guard(self) -> None:
        """If total source+target chars exceeds _MAX_SELF_REFLECT_CHARS, skipped."""
        from types import SimpleNamespace
        from ol_xliff.self_reflect import _MAX_SELF_REFLECT_CHARS

        units = [
            SimpleNamespace(
                unit_id=f"u{i}",
                source_text="A" * 500,
                target_text="B" * 500,
            )
            for i in range(200)
        ]
        pool = MockEmptyPool()
        result = await self_reflect_translated_units(units, "en", "zh", pool)
        assert "_self_reflect" in result
        assert "Skipped" in result["_self_reflect"][0]

    @pytest.mark.asyncio
    async def test_source_language_residual_skipped(self) -> None:
        """Correction that reverts to source language is skipped."""
        from unittest.mock import patch

        units = [
            TranslationUnit(
                unit_id="u1", source_text="Hello", target_text="你好",
                shield_map={},
            ),
        ]
        pool = FakeResponsePool(
            "id: u1\nfix: Hello\nreason: reverted to source\n"
        )
        with patch(
            "ol_xliff.self_reflect.has_source_language_residual",
            return_value=True,
        ):
            result = await self_reflect_translated_units(units, "en", "zh", pool)
        assert result == {}
        assert units[0].target_text == "你好"

    @pytest.mark.asyncio
    async def test_unknown_unit_id_skipped(self) -> None:
        units = [
            TranslationUnit(
                unit_id="u1", source_text="Hello", target_text="你好",
                shield_map={},
            ),
        ]
        pool = FakeResponsePool(
            "id: unknown\nfix: Bonjour\nreason: greeting\n"
        )
        result = await self_reflect_translated_units(units, "en", "zh", pool)
        assert result == {}

    @pytest.mark.asyncio
    async def test_same_text_no_correction(self) -> None:
        units = [
            TranslationUnit(
                unit_id="u1", source_text="Hello", target_text="Hello",
                shield_map={},
            ),
        ]
        pool = FakeResponsePool(
            "id: u1\nfix: Hello\nreason: unchanged\n"
        )
        result = await self_reflect_translated_units(units, "en", "zh", pool)
        assert result == {}


class TestSelfReflectMdText:
    """Tests for self_reflect_md_text()."""

    @pytest.mark.asyncio
    async def test_empty_text(self) -> None:
        pool = MockEmptyPool()
        result = await self_reflect_md_text("", "en", "zh", pool)
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_issues(self) -> None:
        pool = MockEmptyPool()
        text = "Hello world.\n\nHow are you?"
        result = await self_reflect_md_text(text, "en", "zh", pool)
        assert result == text

    @pytest.mark.asyncio
    async def test_corrections_applied(self) -> None:
        pool = FakeResponsePool(
            "id: md-para-0\nfix: 您好世界。\nreason: polite form\n"
        )
        text = "你好世界。\n\n最近怎么样？"
        result = await self_reflect_md_text(text, "en", "zh", pool)
        # md-para-0 should have been corrected
        assert "您好世界" in result


# Helper pools used by tests


class MockEmptyPool:
    async def translate(self, text, src, tgt, **kwargs):
        return "NO_ISSUES"


class FakeResponsePool:
    def __init__(self, response: str):
        self._response = response

    async def translate(self, text, src, tgt, **kwargs):
        return self._response
