"""Tests for Issue #30: judge-text should not return score=0 in FAKE_LLM mode.

Root cause: ModelPool.__init__ did not check OMNI_TEST_FAKE_LLM, so when
litellm.Router init failed (in test env with stubbed Router), it fell
through to test_mode and judge() returned {"score": 0, "reason": "placeholder"}.

Fix: ModelPool.__init__ now detects OMNI_TEST_FAKE_LLM=1 and uses
_FakeModelPool. ModelPool.judge() delegates to _FakeModelPool.judge().

The test patches litellm.Router to MagicMock to trigger _test_mode via
the isinstance(Router, MagicMock) check.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch


class TestModelPoolJudgeInFakeMode:
    """When test_mode is active, ModelPool.judge should not return score=0."""

    def test_judge_returns_non_zero_score_with_router_mock(self):
        """Patching Router to MagicMock triggers test_mode; judge should NOT return score=0."""
        from ol_pool.router import ModelPool, _pool_cache

        _pool_cache.clear()

        async def main():
            with patch("ol_pool.router.Router", MagicMock()):
                pool = ModelPool.get_instance("config/default.yaml")
                result = await pool.judge(
                    source="hello world",
                    target="bonjour le monde",
                    source_lang="en",
                    target_lang="fr",
                )
                return result

        result = asyncio.run(main())
        assert result["score"] > 0, f"Expected score > 0, got {result['score']}"
        assert "accuracy" in result
        assert "fluency" in result
        assert "adequacy" in result
        assert "terminology_consistency" in result, (
            "ModelPool.judge output should include terminology_consistency for JudgeService compatibility"
        )
        _pool_cache.clear()

    def test_judge_with_fake_llm_env_var(self):
        """When OMNI_TEST_FAKE_LLM=1 (the production test seam), judge returns non-zero."""
        from ol_pool.router import ModelPool, _pool_cache

        _pool_cache.clear()
        # conftest.py already sets OMNI_TEST_FAKE_LLM=1

        async def main():
            pool = ModelPool.get_instance("config/default.yaml")
            return await pool.judge(
                source="hello world",
                target="bonjour le monde",
                source_lang="en",
                target_lang="fr",
            )

        result = asyncio.run(main())
        assert result["score"] > 0, f"Expected score > 0, got {result['score']}"
        _pool_cache.clear()


class TestModelPoolInitDetectsFakeLLM:
    """ModelPool.__init__ should short-circuit to _FakeModelPool on FAKE_LLM."""

    def test_init_stores_fake_pool_when_omni_test_fake_llm(self):
        from ol_pool.router import ModelPool, _pool_cache

        _pool_cache.clear()
        # conftest.py already sets OMNI_TEST_FAKE_LLM=1

        pool = ModelPool.get_instance("config/default.yaml")
        assert hasattr(pool, "_fake_pool"), (
            "ModelPool should store _fake_pool in FAKE_LLM mode"
        )
        assert pool._fake_pool is not None
        _pool_cache.clear()
