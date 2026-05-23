"""Unit tests for RAG prompt injection (ol_terminology.rag_injector)."""
from ol_terminology.rag_injector import (
    build_translate_prompt,
    TM_MATCH_LIMIT,
    GLOSSARY_TERM_LIMIT,
)


class TestBuildTranslatePrompt:
    """Tests for build_translate_prompt()."""

    def test_build_translate_prompt_basic(self):
        """No context (tm_matches, glossary_terms) returns basic prompt."""
        text = "Hello world"
        result = build_translate_prompt(text, "en", "zh")
        assert "[Source Text (en -> zh)]" in result
        assert text in result
        assert "Translate the following en text to zh" in result
        assert "[Translation Memory" not in result
        assert "[Glossary Terms" not in result

    def test_build_translate_prompt_with_tm_matches(self):
        """TM matches are injected with top-3 limit."""
        tm_matches = [
            {"source": "hello", "target": "你好", "score": 0.95},
            {"source": "world", "target": "世界", "score": 0.90},
            {"source": "foo", "target": "bar", "score": 0.85},
        ]
        text = "Hello world"
        result = build_translate_prompt(text, "en", "zh", tm_matches=tm_matches)
        assert "[Translation Memory" in result
        assert "hello" in result
        assert "你好" in result
        assert "world" in result
        assert "世界" in result

    def test_build_translate_prompt_with_glossary_terms(self):
        """Glossary terms are injected with top-5 limit."""
        glossary_terms = [
            {"term": "hello", "translation": "你好"},
            {"term": "world", "translation": "世界"},
        ]
        text = "Hello world"
        result = build_translate_prompt(text, "en", "zh", glossary_terms=glossary_terms)
        assert "[Glossary Terms" in result
        assert "hello -> 你好" in result
        assert "world -> 世界" in result

    def test_build_translate_prompt_with_both_tm_and_glossary(self):
        """Both TM matches and glossary terms are injected."""
        tm_matches = [
            {"source": "hello", "target": "你好", "score": 0.95},
        ]
        glossary_terms = [
            {"term": "world", "translation": "世界"},
        ]
        text = "Hello world"
        result = build_translate_prompt(
            text, "en", "zh", tm_matches=tm_matches, glossary_terms=glossary_terms
        )
        assert "[Translation Memory" in result
        assert "[Glossary Terms" in result
        assert "hello" in result
        assert "world" in result

    def test_tm_matches_hardcoded_limit_3(self):
        """TM matches are limited to 3 regardless of input size."""
        tm_matches = [
            {"source": f"src{i}", "target": f"tgt{i}", "score": 0.9}
            for i in range(10)
        ]
        result = build_translate_prompt("test", "en", "zh", tm_matches=tm_matches)
        assert result.count("src0") == 1
        assert result.count("src2") == 1
        assert "src3" not in result
        assert "src9" not in result
        assert f"(top {TM_MATCH_LIMIT} matches)" in result

    def test_glossary_terms_hardcoded_limit_5(self):
        """Glossary terms are limited to 5 regardless of input size."""
        glossary_terms = [
            {"term": f"term{i}", "translation": f"trans{i}"}
            for i in range(10)
        ]
        result = build_translate_prompt(
            "test", "en", "zh", glossary_terms=glossary_terms
        )
        assert "term0" in result
        assert "term4" in result
        assert "term5" not in result
        assert "term9" not in result
        assert f"(top {GLOSSARY_TERM_LIMIT} terms)" in result

    def test_empty_tm_and_glossary_returns_basic_prompt(self):
        """Empty TM and empty glossary returns the basic prompt without context."""
        text = "Hello world"
        result = build_translate_prompt(text, "en", "zh", tm_matches=[], glossary_terms=[])
        assert "[Source Text (en -> zh)]" in result
        assert text in result
        assert "[Translation Memory" not in result
        assert "[Glossary Terms" not in result