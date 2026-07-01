"""Tests for ol_style module (StyleGuide schema + ProfileCache)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestStyleGuideDataclass:
    """StyleGuide dataclass basic behavior."""

    def test_minimal_construction(self):
        from ol_style.schema import StyleGuide
        g = StyleGuide()
        assert g.tone == ""
        assert g.register == ""
        assert g.target_audience == ""
        assert g.key_conventions == []
        assert g.vocabulary == []
        assert g.avoid == []
        assert g.summary == ""

    def test_full_construction(self):
        from ol_style.schema import StyleGuide
        g = StyleGuide(
            tone="formal",
            register="technical",
            target_audience="software developers",
            key_conventions=["Use active voice", "Avoid jargon"],
            vocabulary=["API", "endpoint", "middleware"],
            avoid=["simplistic", "trivial"],
            summary="A technical guide for backend engineers.",
        )
        assert g.tone == "formal"
        assert g.register == "technical"
        assert len(g.key_conventions) == 2
        assert len(g.vocabulary) == 3

    def test_to_dict_round_trip(self):
        from ol_style.schema import StyleGuide
        original = StyleGuide(
            tone="formal",
            register="technical",
            target_audience="developers",
            key_conventions=["Convention 1"],
            vocabulary=["Term1", "Term2"],
            avoid=["Bad1"],
            summary="A test summary.",
        )
        d = original.to_dict()
        restored = StyleGuide.from_dict(d)
        assert restored == original

    def test_from_dict_ignores_unknown_keys(self):
        from ol_style.schema import StyleGuide
        d = {
            "tone": "informal",
            "register": "conversational",
            "unknown_future_field": "ignored",
        }
        g = StyleGuide.from_dict(d)
        assert g.tone == "informal"

    def test_to_prompt_section_empty(self):
        from ol_style.schema import StyleGuide
        g = StyleGuide()
        section = g.to_prompt_section()
        # Empty guide should produce a placeholder, not crash
        assert isinstance(section, str)

    def test_to_prompt_section_includes_all_fields(self):
        from ol_style.schema import StyleGuide
        g = StyleGuide(
            tone="formal",
            register="technical",
            target_audience="developers",
            key_conventions=["Use active voice", "Avoid jargon"],
            vocabulary=["API", "endpoint"],
            avoid=["simplistic"],
            summary="Tech doc summary.",
        )
        section = g.to_prompt_section()
        assert "formal" in section
        assert "technical" in section
        assert "developers" in section
        assert "Use active voice" in section
        assert "API" in section
        assert "simplistic" in section
        assert "Tech doc summary." in section


class TestStyleGuideIO:
    """StyleGuide JSON file I/O."""

    def test_to_json_file_and_back(self, tmp_path):
        from ol_style.schema import StyleGuide
        g = StyleGuide(
            tone="formal",
            register="academic",
            target_audience="researchers",
            key_conventions=["Cite sources"],
            vocabulary=["methodology"],
            avoid=["obvious"],
            summary="Research paper.",
        )
        path = tmp_path / "guide.json"
        g.to_json_file(path)
        assert path.exists()
        loaded = StyleGuide.from_json_file(path)
        assert loaded == g

    def test_to_json_file_creates_valid_json(self, tmp_path):
        from ol_style.schema import StyleGuide
        g = StyleGuide(tone="casual", summary="Hi.")
        path = tmp_path / "g.json"
        g.to_json_file(path)
        data = json.loads(path.read_text())
        assert data["tone"] == "casual"
        assert data["summary"] == "Hi."


class TestProfileCache:
    """ProfileCache file-hash based caching."""

    def test_cache_miss_returns_none(self):
        from ol_style.cache import ProfileCache
        from ol_style.schema import StyleGuide
        cache = ProfileCache()
        result = cache.get("some content never seen before")
        assert result is None

    def test_cache_put_then_get(self):
        from ol_style.cache import ProfileCache
        from ol_style.schema import StyleGuide
        cache = ProfileCache()
        guide = StyleGuide(tone="formal", summary="test")
        cache.put("content A", guide)
        result = cache.get("content A")
        assert result == guide

    def test_cache_different_content_different_keys(self):
        from ol_style.cache import ProfileCache
        from ol_style.schema import StyleGuide
        cache = ProfileCache()
        g1 = StyleGuide(tone="formal", summary="A")
        g2 = StyleGuide(tone="informal", summary="B")
        cache.put("content A", g1)
        cache.put("content B", g2)
        assert cache.get("content A") == g1
        assert cache.get("content B") == g2

    def test_cache_overwrite(self):
        from ol_style.cache import ProfileCache
        from ol_style.schema import StyleGuide
        cache = ProfileCache()
        g1 = StyleGuide(tone="formal", summary="first")
        g2 = StyleGuide(tone="informal", summary="second")
        cache.put("content", g1)
        cache.put("content", g2)
        assert cache.get("content") == g2

    def test_cache_with_disk_persistence(self, tmp_path):
        from ol_style.cache import ProfileCache
        from ol_style.schema import StyleGuide
        cache1 = ProfileCache(cache_dir=tmp_path)
        guide = StyleGuide(tone="formal", summary="persistent")
        cache1.put("content", guide)
        # Reload from disk
        cache2 = ProfileCache(cache_dir=tmp_path)
        loaded = cache2.get("content")
        assert loaded == guide

    def test_cache_hash_deterministic(self):
        from ol_style.cache import ProfileCache
        cache = ProfileCache()
        h1 = cache._hash("same content")
        h2 = cache._hash("same content")
        assert h1 == h2
        h3 = cache._hash("different content")
        assert h1 != h3

    def test_cache_size_property(self):
        from ol_style.cache import ProfileCache
        from ol_style.schema import StyleGuide
        cache = ProfileCache()
        assert cache.size == 0
        cache.put("a", StyleGuide(tone="a"))
        cache.put("b", StyleGuide(tone="b"))
        assert cache.size == 2

    def test_cache_clear(self):
        from ol_style.cache import ProfileCache
        from ol_style.schema import StyleGuide
        cache = ProfileCache()
        cache.put("a", StyleGuide(tone="a"))
        cache.put("b", StyleGuide(tone="b"))
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None
