"""T3.0 tests for the --polish post-translation consistency pass."""
import pytest


class TestBuildPolishPrompt:
    def test_basic_prompt_structure(self):
        from ol_xliff.polish import _build_polish_prompt
        pairs = [{"id": "u1", "src": "Hello", "tgt": "你好"}]
        prompt = _build_polish_prompt(pairs)
        assert "consistency checker" in prompt
        assert "id: u1" in prompt
        assert "src: Hello" in prompt
        assert "tgt: 你好" in prompt

    def test_multiple_pairs(self):
        from ol_xliff.polish import _build_polish_prompt
        pairs = [
            {"id": "u1", "src": "Hello", "tgt": "你好"},
            {"id": "u2", "src": "World", "tgt": "世界"},
        ]
        prompt = _build_polish_prompt(pairs)
        assert prompt.count("id: u1") >= 1
        assert prompt.count("id: u2") >= 1


class TestParsePolishResponse:
    def test_no_issues(self):
        from ol_xliff.polish import _parse_polish_response
        assert _parse_polish_response("NO_ISSUES") == []
        assert _parse_polish_response("") == []
        assert _parse_polish_response("   ") == []

    def test_single_correction(self):
        from ol_xliff.polish import _parse_polish_response
        response = (
            "id: u1\n"
            "fix: Carrier is a leading manufacturer\n"
            "reason: TERM_INCONSISTENCY: Carrie corrected to Carrier"
        )
        corrections = _parse_polish_response(response)
        assert len(corrections) == 1
        assert corrections[0]["id"] == "u1"
        assert "Carrier" in corrections[0]["fix"]
        assert "TERM_INCONSISTENCY" in corrections[0]["reason"]

    def test_multiple_corrections(self):
        from ol_xliff.polish import _parse_polish_response
        response = (
            "id: u1\n"
            "fix: Carrier\n"
            "reason: TERM_INCONSISTENCY\n"
            "\n"
            "id: u2\n"
            "fix: premium, high-end\n"
            "reason: FORMAT"
        )
        corrections = _parse_polish_response(response)
        assert len(corrections) == 2
        assert corrections[0]["id"] == "u1"
        assert corrections[1]["id"] == "u2"

    def test_malformed_skipped_gracefully(self):
        from ol_xliff.polish import _parse_polish_response
        corrections = _parse_polish_response("some random text without structure")
        assert corrections == []


class TestPolishBudgetGuard:
    @pytest.mark.asyncio
    async def test_polish_skipped_when_too_large(self):
        """If total source+target chars exceeds _MAX_POLISH_CHARS, polish returns a warning."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from ol_xliff.polish import polish_translated_units, _MAX_POLISH_CHARS

        pool = MagicMock()
        pool.translate = AsyncMock()

        units = [
            SimpleNamespace(
                unit_id=f"u{i}",
                source_text="A" * 500,
                target_text="B" * 500,
            )
            for i in range(200)
        ]
        warnings = await polish_translated_units(units, "en", "zh", pool)
        pool.translate.assert_not_called()
        assert "_polish" in warnings
        assert "Skipped" in warnings["_polish"][0]


class TestPolishEmptyUnits:
    @pytest.mark.asyncio
    async def test_polish_empty_units_returns_empty(self):
        from ol_xliff.polish import polish_translated_units
        from unittest.mock import MagicMock

        pool = MagicMock()
        warnings = await polish_translated_units([], "en", "zh", pool)
        assert warnings == {}


class TestPolishAppliesCorrections:
    @pytest.mark.asyncio
    async def test_polish_applies_corrections_to_units(self):
        """When LLM returns corrections, units' target_text is updated."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from ol_xliff.polish import polish_translated_units

        unit1 = SimpleNamespace(
            unit_id="u1", source_text="hello", target_text="carrie",
        )
        unit2 = SimpleNamespace(
            unit_id="u2", source_text="world", target_text="globe",
        )
        units = [unit1, unit2]

        llm_response = (
            "id: u1\n"
            "fix: Carrier\n"
            "reason: TERM_INCONSISTENCY"
        )

        pool = MagicMock()

        async def fake_translate(text, src, tgt, context=None, **kwargs):
            return llm_response

        pool.translate = AsyncMock(side_effect=fake_translate)

        warnings = await polish_translated_units(units, "en", "zh", pool)
        assert unit1.target_text == "Carrier"
        assert unit2.target_text == "globe"
        assert "u1" in warnings
        assert "TERM_INCONSISTENCY" in warnings["u1"][0]
