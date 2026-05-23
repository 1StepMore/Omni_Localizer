"""Unit tests for glossary loading and relevance-based term retrieval."""
import json
from pathlib import Path

import pytest

from ol_terminology.glossary import get_relevant_terms, load_glossary


# Path to fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"
GLOSSARY_JSON = FIXTURES_DIR / "glossary.json"


class TestLoadGlossary:
    """Tests for load_glossary() function."""

    def test_glossary_loaded_from_json_path(self):
        """AC-1: test_glossary_loaded_from_json_path - loads from fixtures/glossary.json."""
        glossary = load_glossary(GLOSSARY_JSON)

        assert len(glossary) == 5
        assert "API endpoint" in glossary
        assert glossary["API endpoint"]["translation"] == "API 端点"
        assert glossary["API endpoint"]["confidence"] == 0.95
        assert glossary["batch processing"]["variants"]["batch"] == "批处理"

    def test_load_glossary_missing_file_returns_empty_dict(self):
        """Missing glossary file returns empty dict (no exception raised)."""
        missing_path = FIXTURES_DIR / "nonexistent.json"
        glossary = load_glossary(missing_path)

        assert glossary == {}

    def test_load_glossary_malformed_json(self):
        """Malformed JSON raises ValueError with descriptive message."""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("{ invalid json }")
            temp_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Malformed glossary JSON"):
                load_glossary(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)


class TestGetRelevantTerms:
    """Tests for get_relevant_terms() function."""

    def test_top_terms_relevance_selected(self):
        """AC-3: test_top_terms_relevance_selected - top-k terms selected by relevance."""
        glossary = load_glossary(GLOSSARY_JSON)

        text = "I need quality assurance for the source file translation."
        results = get_relevant_terms(text, glossary, top_k=3)

        assert len(results) <= 3
        # Exact matches should appear first
        term_names = [r["term"] for r in results]
        assert "quality assurance" in term_names
        assert "source file" in term_names

    def test_get_relevant_terms_exact_match_preferred(self):
        """Exact substring matches rank higher than case-insensitive matches."""
        glossary = {
            "API endpoint": {
                "translation": "API 端点",
                "variants": {},
                "confidence": 0.8,
            },
            "api endpoint": {
                "translation": "api 端点",
                "variants": {},
                "confidence": 0.9,
            },
        }

        text = "The API endpoint is defined here."
        results = get_relevant_terms(text, glossary, top_k=5)

        term_names = [r["term"] for r in results]
        # Exact match "API endpoint" should come before case-only variant
        assert term_names.index("API endpoint") < term_names.index("api endpoint")

    def test_get_relevant_terms_partial_match(self):
        """Partial/substring matches are still returned when no exact match."""
        glossary = {
            "quality assurance": {
                "translation": "质量保证",
                "variants": {"质量保证": "QA"},
                "confidence": 0.85,
            },
        }

        text = "We need QA support."
        results = get_relevant_terms(text, glossary, top_k=5)

        assert len(results) == 1
        assert results[0]["term"] == "quality assurance"
        assert results[0]["translation"] == "质量保证"

    def test_get_relevant_terms_empty_glossary(self):
        """Empty glossary returns empty list."""
        results = get_relevant_terms("some text", {}, top_k=5)
        assert results == []

    def test_get_relevant_terms_empty_text(self):
        """Empty text returns empty list."""
        glossary = {
            "test": {
                "translation": "测试",
                "variants": {},
                "confidence": 1.0,
            },
        }
        results = get_relevant_terms("", glossary, top_k=5)
        assert results == []

    def test_get_relevant_terms_no_matching_terms(self):
        """Text with no glossary matches returns empty list."""
        glossary = {
            "API endpoint": {
                "translation": "API 端点",
                "variants": {},
                "confidence": 0.95,
            },
        }

        results = get_relevant_terms("unrelated text without matches", glossary, top_k=5)
        assert results == []