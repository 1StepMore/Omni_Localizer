"""Tests for ModelPool.profile() — Issue #36.

The real ModelPool class has translate() and judge() methods but is missing
profile(). When OMNI_TEST_FAKE_LLM != "1", calling ol_style.doc_profiler
.profile_document() crashes with AttributeError: 'ModelPool' object has
no attribute 'profile'. The fake seam (_FakeModelPool) has profile() so
FAKE_LLM mode is unaffected.

These tests verify that ModelPool.profile() exists, has the same signature
as _FakeModelPool.profile(content, source_lang, **kwargs) -> dict, and
routes through the 'profiling' role group when in real LLM mode.
"""
import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestModelPoolProfile:
    """ModelPool.profile() must exist and mirror _FakeModelPool.profile()."""

    def test_model_pool_has_profile_method(self):
        """ModelPool must define profile() (Issue #36 — was missing)."""
        from ol_pool.router import ModelPool
        assert hasattr(ModelPool, "profile"), (
            "ModelPool is missing profile() — 'ol profile-doc' crashes in real LLM mode"
        )
        assert inspect.iscoroutinefunction(ModelPool.profile), (
            "ModelPool.profile() must be a coroutine function to match _FakeModelPool.profile()"
        )

    def test_model_pool_profile_signature_matches_fake(self):
        """ModelPool.profile() signature must be compatible with the call site
        in ol_style/doc_profiler.py:171: ``await model_pool.profile(prompt, source_lang)``."""
        from ol_pool.router import ModelPool
        from ol_pool.fake import _FakeModelPool
        import inspect

        real_sig = inspect.signature(ModelPool.profile)
        fake_sig = inspect.signature(_FakeModelPool.profile)

        real_params = [p for p in real_sig.parameters.keys() if p != "self"]
        assert real_params[0] in ("content", "prompt", "text"), (
            f"First param must be content/prompt/text, got {real_params[0]!r}"
        )
        assert "source_lang" in real_params or "src" in real_params, (
            f"profile() must accept source_lang, got params {real_params}"
        )
        # Both should return a dict (StyleGuide shape)
        assert real_sig.return_annotation != inspect.Signature.empty, (
            "ModelPool.profile() should declare its return type (dict)"
        )

    def test_model_pool_profile_test_mode_delegates_to_fake(self):
        """In test_mode (FAKE_LLM=1), ModelPool.profile() must delegate to
        _FakeModelPool.profile() so the existing doc_profiler tests still pass."""
        from ol_pool.router import ModelPool
        from ol_style.schema import StyleGuide

        # FAKE_LLM is set by conftest.py — we just need the pool to short-circuit
        pool = ModelPool.get_instance()
        # Force test_mode in case get_instance hit a different path
        if not pool._test_mode:
            pytest.skip("test_mode not active in this environment")

        result = asyncio.run(pool.profile("Sample content for profiling.", "en"))
        assert isinstance(result, dict)
        # Must contain StyleGuide fields (mirrors _FakeModelPool.profile contract)
        assert "tone" in result
        assert "summary" in result
        assert result.get("_source_lang") == "en"
        assert result.get("_content_length") == len("Sample content for profiling.")

    def test_model_pool_profile_in_real_mode_routes_via_profiling_role(self):
        """In real LLM mode (not _test_mode), ModelPool.profile() must call
        self._router.acompletion with model='profiling' (matching the role
        group registered in self._breakers)."""
        from ol_pool.router import ModelPool

        # Construct a ModelPool instance and force non-test mode without
        # actually calling litellm. We patch _router to a MagicMock after init.
        with patch("ol_pool.router.Router", MagicMock()):
            # Clear singleton so we get a fresh instance
            from ol_pool.router import _pool_cache
            _pool_cache.clear()
            pool = ModelPool("config/default.yaml")
            # If Router is a MagicMock, isinstance(Router, MagicMock) is True
            # and _test_mode would be True. Force it False to exercise the
            # real path (still mocked at _router.acompletion level).
            pool._test_mode = False
            pool._router = MagicMock()
            pool._router.acompletion = AsyncMock(
                return_value=MagicMock(
                    choices=[MagicMock(message=MagicMock(content='{"tone": "ok", "register": "general", "target_audience": "x", "key_conventions": [], "vocabulary": [], "avoid": [], "summary": "ok"}'))]
                )
            )
            # Bypass the pre-existing _breakers init bug (test_e2e_83_large_content
            # has the same workaround). _call_with_breaker just delegates to
            # the router.acompletion mock; we don't care about breaker state.
            async def fake_breaker(role, coro_func, *args, **kwargs):
                return await coro_func(*args, **kwargs)
            pool._call_with_breaker = fake_breaker

            # Now call profile() — it must not AttributeError
            result = asyncio.run(pool.profile("Test content", "en"))
            # Verify the routing call
            assert pool._router.acompletion.called, (
                "ModelPool.profile() must call self._router.acompletion (via _call_with_breaker)"
            )
            call_kwargs = pool._router.acompletion.call_args.kwargs
            assert call_kwargs.get("model") == "profiling", (
                f"profile() must route via 'profiling' role, got model={call_kwargs.get('model')!r}"
            )
            # Must produce a parseable dict
            assert isinstance(result, dict)
            assert "tone" in result

    def test_ol_profile_doc_cli_does_not_crash_in_real_mode(self, tmp_path, monkeypatch):
        """The actual ol profile-doc CLI must work in real LLM mode without
        raising AttributeError. We test the import path that calls
        ModelPool.profile() by using a real ModelPool instance with mocked Router.
        """
        # Build a real-ModeP pool entrypoint
        from ol_style.doc_profiler import profile_document

        with patch("ol_pool.router.Router", MagicMock()):
            from ol_pool.router import ModelPool, _pool_cache
            _pool_cache.clear()
            pool = ModelPool("config/default.yaml")
            pool._test_mode = False
            pool._router = MagicMock()
            pool._router.acompletion = AsyncMock(
                return_value=MagicMock(
                    choices=[MagicMock(message=MagicMock(content='{"tone": "professional", "register": "general", "target_audience": "developers", "key_conventions": [], "vocabulary": [], "avoid": [], "summary": "OK"}'))]
                )
            )
            # Bypass the pre-existing _breakers init bug (test_e2e_83_large_content
            # has the same workaround). _call_with_breaker just delegates to
            # the router.acompletion mock; we don't care about breaker state.
            async def fake_breaker(role, coro_func, *args, **kwargs):
                return await coro_func(*args, **kwargs)
            pool._call_with_breaker = fake_breaker

            from ol_style.cache import ProfileCache
            # profile_document() must reach the LLM call (no AttributeError)
            result = asyncio.run(profile_document(
                content="# Test\n\nSome content.",
                source_lang="en",
                model_pool=pool,
                cache=ProfileCache(),
            ))
            # Must return a parsed StyleGuide
            from ol_style.schema import StyleGuide
            assert isinstance(result, StyleGuide)
            assert result.tone == "professional"
            # And the underlying LLM was actually called
            assert pool._router.acompletion.called
