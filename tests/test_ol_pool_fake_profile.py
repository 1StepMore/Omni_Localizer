"""Tests for _FakeModelPool.profile() test seam."""
from __future__ import annotations

import asyncio
import inspect



class TestFakeModelPoolProfile:
    """_FakeModelPool.profile() is the test seam for doc_profiler."""

    def test_profile_is_coroutine(self):
        from ol_pool.fake import _FakeModelPool
        pool = _FakeModelPool()
        result = pool.profile("some content")
        assert inspect.iscoroutine(result)
        # Resolve the coroutine
        data = asyncio.run(pool.profile("some content"))
        assert isinstance(data, dict)

    def test_profile_returns_style_guide_dict(self):
        from ol_pool.fake import _FakeModelPool
        pool = _FakeModelPool()
        data = asyncio.run(pool.profile("Test content for profiling."))
        # Must contain StyleGuide fields
        assert "tone" in data
        assert "register" in data
        assert "target_audience" in data
        assert "key_conventions" in data
        assert "vocabulary" in data
        assert "avoid" in data
        assert "summary" in data

    def test_profile_is_deterministic(self):
        from ol_pool.fake import _FakeModelPool
        pool = _FakeModelPool()
        a = asyncio.run(pool.profile("Content A"))
        b = asyncio.run(pool.profile("Content A"))
        assert a == b

    def test_profile_accepts_optional_source_lang(self):
        from ol_pool.fake import _FakeModelPool
        pool = _FakeModelPool()
        # Should not raise
        data = asyncio.run(pool.profile("content", source_lang="zh"))
        assert isinstance(data, dict)

    def test_profile_value_is_loadable_into_styleguide(self):
        """The dict returned by profile() should be loadable as a StyleGuide."""
        from ol_pool.fake import _FakeModelPool
        from ol_style.schema import StyleGuide
        pool = _FakeModelPool()
        data = asyncio.run(pool.profile("content"))
        guide = StyleGuide.from_dict(data)
        assert isinstance(guide, StyleGuide)
        assert guide.tone == data["tone"]
        assert guide.summary == data["summary"]
        assert "_source_lang" in data
        assert "_content_length" in data
