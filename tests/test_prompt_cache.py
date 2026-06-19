"""Tests for the LLM prompt cache (A3 — slim-pipeline-hardening).

The cache lives on `ModelPool` and is consulted by `translate()` and
`judge()` before any LLM call. The cache is only safe for deterministic
responses (temperature=0), so it is bypassed when:

  1. `cache_system_prompt` is False in the config, OR
  2. The caller passes a non-zero `temperature` argument.

Cache key = (model_role, sha256(messages_json), temperature).
Cache is LRU (max 1000 entries) with TTL = 300 seconds.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pybreaker
import pytest

from ol_config.schema import (
    LLMModelConfig,
    LLMModelRole,
    LLMPoolConfig,
    ProjectConfig,
)
from ol_pool.router import ModelPool, _PromptCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model_pool(
    *,
    acompletion_return=None,
    acompletion_side_effect=None,
    cache_enabled: bool = True,
    time_func=None,
) -> ModelPool:
    """Build a ModelPool with the real cache wired but the router mocked.

    Bypasses `__init__` because the standard init short-circuits to
    `_test_mode=True` when the litellm `Router` is a stub (which is the
    case under conftest). We need `_test_mode=False` so the cache path
    runs, and we need a controllable `acompletion` so we can count calls.
    """
    pool = ModelPool.__new__(ModelPool)
    pool._test_mode = False
    pool._router = MagicMock()
    if acompletion_side_effect is not None:
        pool._router.acompletion = AsyncMock(side_effect=acompletion_side_effect)
    else:
        pool._router.acompletion = AsyncMock(return_value=acompletion_return)
    pool._cache_enabled = cache_enabled
    pool._breakers = {"translation": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60), "judging": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60), "restoration": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)}
    pool._cache = _PromptCache(
        max_size=1000, ttl_seconds=300.0, time_func=time_func,
    )
    return pool


def _make_translation_response(content: str = "你好世界") -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


def _make_judge_response(score: int = 95) -> MagicMock:
    payload = json.dumps({
        "accuracy": score,
        "fluency": score,
        "adequacy": score,
        "score": score,
        "format_errors": [],
    })
    return _make_translation_response(payload)


def _make_pool_with_translation_response(content: str = "你好世界") -> ModelPool:
    return _make_model_pool(acompletion_return=_make_translation_response(content))


# ---------------------------------------------------------------------------
# A3.1 — cache hit on the second call
# ---------------------------------------------------------------------------

class TestPromptCacheHit:
    @pytest.mark.asyncio
    async def test_prompt_cache_returns_cached_response_on_second_call(self):
        """A second translate() with identical args must NOT re-invoke the LLM."""
        pool = _make_pool_with_translation_response("你好世界")

        first = await pool.translate("Hello", "en", "zh")
        second = await pool.translate("Hello", "en", "zh")

        assert first == "你好世界"
        assert second == "你好世界"
        assert pool._router.acompletion.call_count == 1, (
            f"Expected exactly 1 LLM call (the second should be a cache hit), "
            f"got {pool._router.acompletion.call_count}"
        )


# ---------------------------------------------------------------------------
# A3.2 — bypass conditions (temperature != 0 OR cache disabled)
# ---------------------------------------------------------------------------

class TestPromptCacheBypass:
    @pytest.mark.asyncio
    async def test_prompt_cache_bypassed_on_temperature_nonzero(self):
        """Non-zero temperature must bypass the cache entirely."""
        pool = _make_pool_with_translation_response("translation")

        await pool.translate("Hello", "en", "zh", temperature=0.5)
        await pool.translate("Hello", "en", "zh", temperature=0.5)

        assert pool._router.acompletion.call_count == 2, (
            f"Non-zero temperature must bypass cache; expected 2 LLM calls, "
            f"got {pool._router.acompletion.call_count}"
        )

    @pytest.mark.asyncio
    async def test_prompt_cache_bypassed_when_config_disabled(self):
        """cache_system_prompt=False must disable the cache entirely."""
        pool = _make_pool_with_translation_response("translation")
        pool._cache_enabled = False

        await pool.translate("Hello", "en", "zh")
        await pool.translate("Hello", "en", "zh")

        assert pool._router.acompletion.call_count == 2, (
            f"Disabled cache must produce 2 LLM calls, got "
            f"{pool._router.acompletion.call_count}"
        )


# ---------------------------------------------------------------------------
# A3.3 — cache key includes model and prompt content
# ---------------------------------------------------------------------------

class TestPromptCacheKey:
    @pytest.mark.asyncio
    async def test_prompt_cache_key_includes_model_and_prompt(self):
        """Changing the prompt or the model must produce a cache miss."""
        async def side_effect(*args, **kwargs):
            model = kwargs.get("model")
            if model == "translation":
                return _make_translation_response("t")
            if model == "judging":
                return _make_judge_response(95)
            return _make_translation_response("fallback")

        pool = _make_model_pool(acompletion_side_effect=side_effect)

        # Two translate calls with DIFFERENT user text → both miss
        await pool.translate("Hello", "en", "zh")
        await pool.translate("Goodbye", "en", "zh")
        # A judge call (different model) → miss
        await pool.judge("Hello", "你好", "en", "zh")

        assert pool._router.acompletion.call_count == 3, (
            f"Different prompt text and different model must each be a miss; "
            f"expected 3 LLM calls, got {pool._router.acompletion.call_count}"
        )


# ---------------------------------------------------------------------------
# A3.3 — TTL expiry
# ---------------------------------------------------------------------------

class TestPromptCacheTTL:
    @pytest.mark.asyncio
    async def test_prompt_cache_ttl_expiry(self):
        """After the TTL elapses, a fresh LLM call must be made."""
        now = [1000.0]
        def tick():
            return now[0]
        def advance(seconds: float) -> None:
            now[0] += seconds

        pool = _make_pool_with_translation_response("t")
        pool._breakers = {"translation": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60), "judging": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60), "restoration": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)}
        pool._cache = _PromptCache(max_size=1000, ttl_seconds=300.0, time_func=tick)

        # t=0 — first call: miss → store
        await pool.translate("Hello", "en", "zh")
        # t=0 — second call: hit (no time has advanced)
        await pool.translate("Hello", "en", "zh")
        assert pool._router.acompletion.call_count == 1, (
            f"Expected 1 call (second was a hit), got "
            f"{pool._router.acompletion.call_count}"
        )

        # Advance past the 300s TTL
        advance(301)
        # Now the entry is expired; a third call must miss
        await pool.translate("Hello", "en", "zh")
        assert pool._router.acompletion.call_count == 2, (
            f"After TTL expiry, expected a fresh LLM call; got "
            f"call_count={pool._router.acompletion.call_count}"
        )


# ---------------------------------------------------------------------------
# Schema field — cache_system_prompt
# ---------------------------------------------------------------------------

class TestProjectConfigCacheField:
    """A3.2 — `cache_system_prompt: bool = True` on ProjectConfig."""

    def _pool(self) -> LLMPoolConfig:
        return LLMPoolConfig(
            translation=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.TRANSLATION),
                LLMModelConfig(provider="openai", model="gpt-4o", priority=2, role=LLMModelRole.TRANSLATION),
            ],
            judging=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="anthropic", model="claude-3-sonnet", priority=2, role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="openai", model="gpt-4o", priority=2, role=LLMModelRole.RESTORATION),
            ],
        )

    def test_cache_system_prompt_defaults_to_true(self):
        config = ProjectConfig(llm_pool=self._pool())
        assert config.cache_system_prompt is True

    def test_cache_system_prompt_can_be_disabled(self):
        config = ProjectConfig(llm_pool=self._pool(), cache_system_prompt=False)
        assert config.cache_system_prompt is False
