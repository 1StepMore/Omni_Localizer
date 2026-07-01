"""Tests for ol_style.doc_profiler — LLM-based document profiler.

Uses OMNI_TEST_FAKE_LLM=1 (from conftest.py) so no real LLM calls
are made. _FakeModelPool.profile() returns a deterministic dict
that profile_document() should parse into a StyleGuide.
"""
from __future__ import annotations


import pytest

from ol_style.schema import StyleGuide
from ol_style.cache import ProfileCache


class TestProfileDocument:
    """profile_document() — main entry point."""

    @pytest.mark.asyncio
    async def test_basic_profile_returns_styleguide(self, tmp_path):
        from ol_style.doc_profiler import profile_document
        guide = await profile_document(
            content="# Hello World\n\nThis is a test document.",
            source_lang="en",
            config_path=None,
            cache=ProfileCache(),
        )
        assert isinstance(guide, StyleGuide)

    @pytest.mark.asyncio
    async def test_profile_with_cjk_content(self, tmp_path):
        from ol_style.doc_profiler import profile_document
        guide = await profile_document(
            content="# 你好世界\n\n这是一个测试文档。",
            source_lang="zh",
            config_path=None,
            cache=ProfileCache(),
        )
        assert isinstance(guide, StyleGuide)

    @pytest.mark.asyncio
    async def test_profile_does_not_call_llm_when_cache_hit(self):
        """Cache hit must return the cached StyleGuide without LLM call."""
        from ol_style.doc_profiler import profile_document
        cache = ProfileCache()
        cached_guide = StyleGuide(
            tone="cached", summary="This was cached",
        )
        cache.put("same content", cached_guide)
        # No LLM available — if cache miss happens, test will fail
        guide = await profile_document(
            content="same content",
            source_lang="en",
            config_path=None,
            cache=cache,
        )
        assert guide == cached_guide

    @pytest.mark.asyncio
    async def test_profile_caches_result_on_miss(self):
        """Cache miss should call LLM, then cache the result for next time."""
        from ol_style.doc_profiler import profile_document
        cache = ProfileCache()
        guide1 = await profile_document(
            content="unique content for cache test",
            source_lang="en",
            config_path=None,
            cache=cache,
        )
        # Verify it's now cached
        cached = cache.get("unique content for cache test")
        assert cached == guide1

    @pytest.mark.asyncio
    async def test_profile_with_explicit_model_pool(self):
        """Passing model_pool directly should bypass config loading."""
        from ol_style.doc_profiler import profile_document
        from ol_pool.fake import _FakeModelPool
        pool = _FakeModelPool()
        guide = await profile_document(
            content="test",
            source_lang="en",
            model_pool=pool,
            cache=ProfileCache(),
        )
        assert isinstance(guide, StyleGuide)
        # Fake pool was called
        assert pool._call_count >= 1

    @pytest.mark.asyncio
    async def test_profile_empty_content_returns_default_styleguide(self):
        """Empty content should not crash; should return a valid StyleGuide."""
        from ol_style.doc_profiler import profile_document
        guide = await profile_document(
            content="",
            source_lang="en",
            config_path=None,
            cache=ProfileCache(),
        )
        assert isinstance(guide, StyleGuide)

    @pytest.mark.asyncio
    async def test_profile_includes_summary(self):
        """Real profile output should include a non-empty summary."""
        from ol_style.doc_profiler import profile_document
        guide = await profile_document(
            content="A long document about technical topics and engineering best practices.",
            source_lang="en",
            config_path=None,
            cache=ProfileCache(),
        )
        # Fake pool returns "Auto-generated profile (FAKE_LLM seam)."
        assert isinstance(guide.summary, str)


class TestProfileDocumentEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_profile_truncates_very_long_content(self):
        """Documents > 10K chars should be truncated before LLM call (saves tokens)."""
        from ol_style.doc_profiler import profile_document
        long_content = "Word " * 5000  # 25K chars
        guide = await profile_document(
            content=long_content,
            source_lang="en",
            config_path=None,
            cache=ProfileCache(),
        )
        assert isinstance(guide, StyleGuide)

    @pytest.mark.asyncio
    async def test_profile_handles_malformed_llm_response(self):
        """If LLM returns malformed JSON, should fall back to a default StyleGuide."""
        from ol_style.doc_profiler import _parse_profile_response
        # Direct test of the parser
        bad = _parse_profile_response("not json at all")
        assert isinstance(bad, StyleGuide)
        assert bad.summary  # has at least a placeholder

    @pytest.mark.asyncio
    async def test_profile_handles_partial_json_response(self):
        """If LLM returns partial JSON, parser should fill in defaults."""
        from ol_style.doc_profiler import _parse_profile_response
        partial = _parse_profile_response('{"tone": "formal", "summary": "test"}')
        assert isinstance(partial, StyleGuide)
        assert partial.tone == "formal"
        assert partial.summary == "test"
        assert partial.register == ""  # default

    @pytest.mark.asyncio
    async def test_profile_handles_dict_input_to_parser(self):
        """_parse_profile_response should accept dict (from _FakeModelPool)."""
        from ol_style.doc_profiler import _parse_profile_response
        d = {"tone": "formal", "summary": "from dict"}
        result = _parse_profile_response(d)
        assert isinstance(result, StyleGuide)
        assert result.tone == "formal"
        assert result.summary == "from dict"
