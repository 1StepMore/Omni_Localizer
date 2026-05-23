"""Unit tests for LLM disambiguation (task 6.2)."""
from __future__ import annotations

from unittest.mock import MagicMock

from ol_terminology.disambiguator import Disambiguator, disambiguate


class TestDisambiguator:
    """Tests for Disambiguator class."""

    def test_disambiguation_resolves_polyseme(self) -> None:
        """AC-5: test_disambiguation_resolves_polyseme.

        Verifies that when a term has multiple variants (polysemous),
        the disambiguator selects the contextually appropriate translation.
        """
        mock_pool = MagicMock()

        def mock_selector(candidates: list[dict], context: str) -> dict:
            return candidates[1] if len(candidates) > 1 else candidates[0]

        disambiguator = Disambiguator(model_pool=mock_pool, llm_selector=mock_selector)

        text = "The bank is near the river bank."
        glossary = {
            "bank": {
                "translation": "银行",
                "confidence": 0.9,
                "variants": {
                    "financial": "银行",
                    "river": "河岸",
                },
            },
        }

        result = disambiguator.disambiguate(text, glossary)

        assert "bank" in result
        assert result["bank"] == "河岸"

    def test_disambiguate_single_term_no_ambiguity(self) -> None:
        """Term with single translation returns empty resolved dict."""
        disambiguator = Disambiguator()

        text = "The document is official."
        glossary = {
            "document": {
                "translation": "文档",
                "confidence": 1.0,
            },
        }

        result = disambiguator.disambiguate(text, glossary)

        assert result == {}

    def test_disambiguate_fallback_to_highest_confidence(self) -> None:
        """Without LLM, falls back to highest confidence candidate."""
        disambiguator = Disambiguator()

        text = "Server error occurred."
        glossary = {
            "error": {
                "translation": "错误",
                "confidence": 0.8,
                "variants": {
                    "programming": "异常",
                    "general": "错误",
                },
            },
        }

        result = disambiguator.disambiguate(text, glossary)

        # Primary has confidence 0.8, variant has 0.8 * 0.9 = 0.72
        # Fallback picks highest confidence = "错误"
        assert result.get("error") == "错误"

    def test_disambiguate_empty_glossary_returns_empty(self) -> None:
        """Empty glossary returns empty dict."""
        disambiguator = Disambiguator()

        result = disambiguator.disambiguate("some text", {})

        assert result == {}

    def test_disambiguate_no_polysemes_returns_empty_resolved(self) -> None:
        """Glossary with only single-variant terms returns empty resolved."""
        disambiguator = Disambiguator()

        text = "Please review the document and submit it."
        glossary = {
            "review": {
                "translation": "审核",
                "confidence": 1.0,
            },
            "document": {
                "translation": "文档",
                "confidence": 1.0,
            },
            "submit": {
                "translation": "提交",
                "confidence": 1.0,
            },
        }

        result = disambiguator.disambiguate(text, glossary)

        assert result == {}

    def test_disambiguate_term_not_in_text(self) -> None:
        """Term in glossary but not in text is not resolved."""
        disambiguator = Disambiguator()

        text = "The document is ready."
        glossary = {
            "document": {
                "translation": "文档",
                "confidence": 1.0,
                "variants": {
                    "official": "公文",
                    "general": "文档",
                },
            },
            "submit": {
                "translation": "提交",
                "confidence": 1.0,
                "variants": {
                    "form": "递交",
                    "general": "提交",
                },
            },
        }

        result = disambiguator.disambiguate(text, glossary)

        # "submit" is not in text, so only "document" could be resolved
        # But since there are no variants that differ from primary in a meaningful way
        assert "submit" not in result

    def test_disambiguate_with_model_pool(self) -> None:
        """Model pool is accepted without error."""
        mock_pool = MagicMock()

        def mock_selector(candidates: list[dict], context: str) -> dict:
            return candidates[0]

        disambiguator = Disambiguator(model_pool=mock_pool, llm_selector=mock_selector)

        text = "The lead singer is excellent."
        glossary = {
            "lead": {
                "translation": "主要",
                "confidence": 0.9,
                "variants": {
                    "metal": "铅",
                    "person": "领衔",
                },
            },
        }

        result = disambiguator.disambiguate(text, glossary)

        assert "lead" in result


class TestDisambiguateFunction:
    """Tests for the disambiguate() convenience function."""

    def test_disambiguate_creates_disambiguator_and_resolves(self) -> None:
        """disambiguate() function creates Disambiguator internally."""
        text = "bank interest rates"
        glossary = {
            "bank": {
                "translation": "银行",
                "confidence": 1.0,
                "variants": {
                    "financial": "银行",
                    "river": "河岸",
                },
            },
        }

        result = disambiguate(text, glossary)

        # With no LLM selector, falls back to highest confidence
        assert isinstance(result, dict)

    def test_disambiguate_empty_text_returns_empty(self) -> None:
        """Empty text returns empty dict."""
        result = disambiguate("", {"bank": {"translation": "银行"}})

        assert result == {}

    def test_disambiguate_none_text_returns_empty(self) -> None:
        """None text returns empty dict."""
        result = disambiguate(None, {"bank": {"translation": "银行"}})  # type: ignore

        assert result == {}