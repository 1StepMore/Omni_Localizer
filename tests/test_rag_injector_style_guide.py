"""Tests for the style_guide parameter of build_translate_prompt().

Verifies the new optional style_guide parameter injects a [Style Guide]
section into the prompt without breaking backward compatibility.
"""
from __future__ import annotations



class TestBuildTranslatePromptBackwardCompat:
    """Without style_guide, behavior is unchanged."""

    def test_no_style_guide_default(self):
        from ol_terminology.rag_injector import build_translate_prompt
        prompt = build_translate_prompt("Hello", "en", "zh")
        assert "[Style Guide]" not in prompt

    def test_no_style_guide_explicit_none(self):
        from ol_terminology.rag_injector import build_translate_prompt
        prompt = build_translate_prompt("Hello", "en", "zh", style_guide=None)
        assert "[Style Guide]" not in prompt

    def test_no_style_guide_empty_string(self):
        from ol_terminology.rag_injector import build_translate_prompt
        prompt = build_translate_prompt("Hello", "en", "zh", style_guide="")
        assert "[Style Guide]" not in prompt

    def test_existing_tm_and_glossary_still_work(self):
        from ol_terminology.rag_injector import build_translate_prompt
        prompt = build_translate_prompt(
            "Hello",
            "en",
            "zh",
            tm_matches=[{"source": "Hi", "target": "你好", "score": 0.9}],
            glossary_terms=[{"term": "API", "translation": "API 端点"}],
        )
        assert "[Translation Memory" in prompt
        assert "[Glossary Terms" in prompt
        assert "[Source Text" in prompt


class TestBuildTranslatePromptWithStyleGuide:
    """With style_guide, a [Style Guide] section is injected."""

    def test_style_guide_section_present(self):
        from ol_terminology.rag_injector import build_translate_prompt
        guide = "[Style Guide]\nTone: formal\nRegister: technical"
        prompt = build_translate_prompt("Hello", "en", "zh", style_guide=guide)
        assert "[Style Guide]" in prompt
        assert "Tone: formal" in prompt

    def test_style_guide_appears_after_glossary(self):
        """The style_guide section should appear between context and source text."""
        from ol_terminology.rag_injector import build_translate_prompt
        guide = "[Style Guide]\nTone: formal"
        prompt = build_translate_prompt(
            "Hello",
            "en",
            "zh",
            glossary_terms=[{"term": "API", "translation": "API 端点"}],
            style_guide=guide,
        )
        # Find positions
        glossary_pos = prompt.find("[Glossary Terms")
        style_pos = prompt.find("[Style Guide]")
        source_pos = prompt.find("[Source Text")
        assert glossary_pos < style_pos < source_pos

    def test_style_guide_alone(self):
        """style_guide without TM or glossary should still inject."""
        from ol_terminology.rag_injector import build_translate_prompt
        guide = "[Style Guide]\nTone: formal"
        prompt = build_translate_prompt("Hello", "en", "zh", style_guide=guide)
        assert "[Style Guide]" in prompt
        assert "Tone: formal" in prompt
        assert "[Source Text" in prompt

    def test_style_guide_with_tm_and_glossary(self):
        """All three context sections should appear in correct order."""
        from ol_terminology.rag_injector import build_translate_prompt
        guide = "[Style Guide]\nTone: formal"
        prompt = build_translate_prompt(
            "Hello",
            "en",
            "zh",
            tm_matches=[{"source": "Hi", "target": "你好", "score": 0.9}],
            glossary_terms=[{"term": "API", "translation": "API 端点"}],
            style_guide=guide,
        )
        tm_pos = prompt.find("[Translation Memory")
        glossary_pos = prompt.find("[Glossary Terms")
        style_pos = prompt.find("[Style Guide]")
        source_pos = prompt.find("[Source Text")
        assert tm_pos < glossary_pos < style_pos < source_pos


class TestBuildTranslatePromptEdgeCases:
    """Edge cases: empty content, special characters."""

    def test_style_guide_with_cjk_content(self):
        from ol_terminology.rag_injector import build_translate_prompt
        guide = "[Style Guide]\n语气: 正式"  # CJK
        prompt = build_translate_prompt("你好", "zh", "en", style_guide=guide)
        assert "语气: 正式" in prompt

    def test_style_guide_with_multiline_content(self):
        from ol_terminology.rag_injector import build_translate_prompt
        guide = "[Style Guide]\nTone: formal\nRegister: technical\nKey conventions:\n  - Use active voice\n  - Avoid jargon"
        prompt = build_translate_prompt("Hello", "en", "zh", style_guide=guide)
        assert "Use active voice" in prompt
        assert "Avoid jargon" in prompt
