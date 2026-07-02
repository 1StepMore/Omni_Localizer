"""Unit tests for glossary loading and relevance-based term retrieval."""
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

class TestLoadGlossaryV1Format:
    """Issue #7: v1 format {"terms": [{"source": "API", "targets": [...]}]} must
    be auto-converted to the legacy dict form instead of being silently corrupted.
    
    Reproduces the bug: previously v1 files produced 1 garbage entry with
    key='terms' and the entire list stored as a string in 'translation'.
    """

    def test_v1_format_loads_all_terms(self, tmp_path):
        """v1 format with N terms in 'terms' list must load all N terms."""
        import json
        from ol_terminology.glossary import load_glossary

        v1_data = {
            "terms": [
                {"source": "API", "targets": ["应用程序接口", "API"]},
                {"source": "rendering", "targets": ["渲染"]},
                {"source": "pipeline", "targets": ["管线", "流水线"]},
            ]
        }
        p = tmp_path / "v1_glossary.json"
        p.write_text(json.dumps(v1_data, ensure_ascii=False), encoding="utf-8")

        result = load_glossary(p)

        # Must have 3 terms, not 1 garbage entry
        assert len(result) == 3, f"Expected 3 terms, got {len(result)}: {list(result)}"
        assert "API" in result
        assert "rendering" in result
        assert "pipeline" in result
        # First target becomes translation
        assert result["API"]["translation"] == "应用程序接口"
        assert result["rendering"]["translation"] == "渲染"
        assert result["pipeline"]["translation"] == "管线"

    def test_v1_format_default_confidence(self, tmp_path):
        """v1 format terms get confidence=1.0 since v1 has no confidence field."""
        import json
        from ol_terminology.glossary import load_glossary

        p = tmp_path / "v1_glossary.json"
        p.write_text(json.dumps({"terms": [{"source": "API", "targets": ["API"]}]}), encoding="utf-8")

        result = load_glossary(p)

        assert result["API"]["confidence"] == 1.0

    def test_v1_format_multiple_targets_become_variants(self, tmp_path):
        """v1 format with N>1 targets: first is translation, rest are variants."""
        import json
        from ol_terminology.glossary import load_glossary

        p = tmp_path / "v1_glossary.json"
        p.write_text(
            json.dumps({"terms": [{"source": "API", "targets": ["应用程序接口", "API"]}]}),
            encoding="utf-8",
        )

        result = load_glossary(p)

        assert result["API"]["translation"] == "应用程序接口"
        # Second target should be a variant
        assert "API" in result["API"]["variants"].values()

    def test_v1_format_from_load_glossary_from_path(self, tmp_path):
        """load_glossary_from_path also handles v1 format."""
        import json
        from ol_terminology.glossary import load_glossary_from_path

        v1_data = {
            "terms": [
                {"source": "API", "targets": ["API 端点"]},
                {"source": "endpoint", "targets": ["端点"]},
            ]
        }
        p = tmp_path / "v1_glossary.json"
        p.write_text(json.dumps(v1_data, ensure_ascii=False), encoding="utf-8")

        result = load_glossary_from_path(p)

        assert len(result) == 2
        assert "API" in result
        assert "endpoint" in result

    def test_legacy_format_still_works(self, tmp_path):
        """Legacy format {"API": {"translation": "..."}} must still work after fix."""
        import json
        from ol_terminology.glossary import load_glossary

        legacy_data = {
            "API endpoint": {
                "translation": "API 端点",
                "variants": {"API endpoint": "API 端点"},
                "confidence": 0.9,
            }
        }
        p = tmp_path / "legacy_glossary.json"
        p.write_text(json.dumps(legacy_data, ensure_ascii=False), encoding="utf-8")

        result = load_glossary(p)

        assert len(result) == 1
        assert result["API endpoint"]["translation"] == "API 端点"
        assert result["API endpoint"]["confidence"] == 0.9

    def test_v1_format_does_not_produce_garbage_entry(self, tmp_path):
        """Regression test: the v1 bug produced a single 'terms' key with a
        stringified list. After fix, the result should have no garbage entry
        named 'terms' and the translation field should never be a stringified list."""
        import json
        from ol_terminology.glossary import load_glossary

        p = tmp_path / "v1_glossary.json"
        p.write_text(
            json.dumps({"terms": [{"source": "API", "targets": ["API"]}]}),
            encoding="utf-8",
        )

        result = load_glossary(p)

        # No key should be "terms" (the old bug)
        assert "terms" not in result
        # No translation should look like a stringified list
        for term, meta in result.items():
            assert not meta["translation"].startswith("["), (
                f"Translation for {term!r} looks like a stringified list: {meta['translation']!r}"
            )
            assert not meta["translation"].startswith("{"), (
                f"Translation for {term!r} looks like a stringified dict: {meta['translation']!r}"
            )
