"""Cross-call dead-model memory with TTL (OL#191).

A hard failure (timeout / retryable transport error) marks the failing
deployment dead for a TTL so FOLLOW-UP translate() calls in the same process
skip it instead of burning the full Router timeout again (serial units each
paid 1 x timeout before OL#191). Pins the contract:

- a marked deployment is not re-dialed on the next call
- after the TTL expires the deployment is dialed again (peer may recover)
- the 429 path never marks anything
- ``OL_POOL_DEAD_MODEL_TTL<=0`` disables the memory entirely
- marks covering every model of a role are ignored (no starvation)
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ol_pool.router as router_mod
from ol_config.schema import LLMModelConfig, LLMModelRole, LLMPoolConfig
from ol_pool.router import APIConnectionError as _APIConnectionError
from ol_pool.router import ModelPool
from ol_pool.router import RateLimitError as _RateLimitError
from ol_pool.router import Timeout as _Timeout


def _timeout_error() -> BaseException:
    try:
        return _Timeout(
            "timed out", model="translation", llm_provider="test",
        )
    except TypeError:  # OMNI_TEST_FAKE_LLM stub: plain Exception
        return _Timeout("timed out")


def _rate_limit_error() -> BaseException:
    try:
        return _RateLimitError(
            "rate limited", model="translation", llm_provider="test",
        )
    except TypeError:  # OMNI_TEST_FAKE_LLM stub: plain Exception
        return _RateLimitError("rate limited")


def _response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].finish_reason = "stop"
    response.choices[0].message.content = content
    response.usage = None
    return response


def _pool_config() -> LLMPoolConfig:
    return LLMPoolConfig(
        translation=[
            LLMModelConfig(
                provider="openai", model="spark-x2.6", priority=1,
                role=LLMModelRole.TRANSLATION,
                api_key="spark-key", base_url="https://spark.example/v2",
                timeout=120.0,
            ),
            LLMModelConfig(
                provider="openai", model="deepseek-flash", priority=2,
                role=LLMModelRole.TRANSLATION,
                api_key="apigoto-key", base_url="https://apigoto.example/v1",
                timeout=120.0, max_tokens=8192,
            ),
        ],
        judging=[
            LLMModelConfig(
                provider="judge", model="judge-primary", priority=1,
                role=LLMModelRole.JUDGING, api_key="judge-key",
            ),
            LLMModelConfig(
                provider="judge", model="judge-backup", priority=2,
                role=LLMModelRole.JUDGING, api_key="judge-key",
            ),
        ],
        restoration=[
            LLMModelConfig(
                provider="restore", model="restore-primary", priority=1,
                role=LLMModelRole.RESTORATION, api_key="restore-key",
            ),
            LLMModelConfig(
                provider="restore", model="restore-backup", priority=2,
                role=LLMModelRole.RESTORATION, api_key="restore-key",
            ),
        ],
    )


@pytest.fixture
def pool_and_router(monkeypatch):
    """A real ModelPool wired to a mocked Router (not FAKE_LLM mode)."""
    monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
    monkeypatch.delenv("OL_POOL_DEAD_MODEL_TTL", raising=False)
    config = _pool_config()
    with patch("ol_pool.router.load_config") as load_config, \
            patch("ol_pool.router.Router") as router_cls:
        load_config.return_value = SimpleNamespace(llm_pool=config)
        pool = ModelPool()
        pool._test_mode = False
        yield pool, router_cls.return_value


def _direct_recorder(calls: list[str]):
    async def _direct(model, messages, temperature, max_tokens):
        calls.append(f"{model.provider}/{model.model}")
        return _response("翻译文本")

    return _direct


@pytest.mark.asyncio
async def test_marked_dead_model_is_not_dialed_again_within_ttl(
    pool_and_router, monkeypatch,
):
    """After one hard failure, the NEXT call skips the dead tier entirely."""
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_timeout_error())

    direct_calls: list[str] = []
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        first = await pool.translate("hello", "en", "zh")
        group_calls_after_first = router.acompletion.await_count
        second = await pool.translate("hello again", "en", "zh")

    assert first == "翻译文本"
    assert second == "翻译文本"
    # Call 1: group call burns the dead tier, failover reaches tier 2.
    assert group_calls_after_first == 1
    # Call 2: the dead tier is skipped WITHOUT another group call.
    assert router.acompletion.await_count == 1, (
        "the marked-dead deployment must not be re-dialed within its TTL"
    )
    # Both calls ended on tier 2, but only call 1 dialed the dead tier.
    assert direct_calls == [
        "openai/deepseek-flash", "openai/deepseek-flash",
    ]


@pytest.mark.asyncio
async def test_ttl_expiry_dials_the_dead_model_again(
    pool_and_router, monkeypatch, caplog,
):
    """Once the TTL expires, the marked deployment is dialed again."""
    import time

    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_timeout_error())
    monkeypatch.setenv("OL_POOL_DEAD_MODEL_TTL", "0.05")

    direct_calls: list[str] = []
    caplog.set_level(logging.WARNING, logger="ol.pool")
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        await pool.translate("hello", "en", "zh")
        # Real wall-clock sleep: router_mod.asyncio.sleep is mocked above.
        time.sleep(0.08)
        await pool.translate("hello again", "en", "zh")

    assert "TTL expired" in caplog.text, (
        "an expired mark must be announced before the deployment is retried"
    )
    # Call 2 re-dialed the (still dead) tier-1 through the Router group call.
    assert router.acompletion.await_count == 2
    assert direct_calls == [
        "openai/deepseek-flash", "openai/deepseek-flash",
    ]


@pytest.mark.asyncio
async def test_rate_limit_path_never_marks_dead(
    pool_and_router, monkeypatch,
):
    """429s are transient: they must not create dead-model marks."""
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_rate_limit_error())
    monkeypatch.setenv("OL_POOL_DEAD_MODEL_TTL", "0.05")

    direct_calls: list[str] = []
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        result = await pool.translate("hello", "en", "zh")

    assert result == "翻译文本"
    assert not pool._dead_marks_state()[0], (
        "a 429 must never leave a dead-model mark behind"
    )


@pytest.mark.asyncio
async def test_disabled_memory_restores_per_call_burn(
    pool_and_router, monkeypatch,
):
    """``OL_POOL_DEAD_MODEL_TTL<=0`` removes the memory (reverse evidence).

    Each call dials the dead tier again through the group call and pays the
    timeout — the exact pre-OL#191 behaviour.
    """
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_timeout_error())
    monkeypatch.setenv("OL_POOL_DEAD_MODEL_TTL", "0")

    direct_calls: list[str] = []
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        await pool.translate("hello", "en", "zh")
        await pool.translate("hello again", "en", "zh")

    assert router.acompletion.await_count == 2, (
        "with the memory disabled every call must re-dial the dead tier"
    )
    assert direct_calls == [
        "openai/deepseek-flash", "openai/deepseek-flash",
    ]


@pytest.mark.asyncio
async def test_marks_covering_every_model_are_ignored(
    pool_and_router, monkeypatch,
):
    """Stale marks must never starve a role: all-dead -> dial normally."""
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_timeout_error())

    direct_calls: list[str] = []
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())
    marks, _lock = pool._dead_marks_state()
    marks.update({
        ("translation", "openai/spark-x2.6"): float("inf"),
        ("translation", "openai/deepseek-flash"): float("inf"),
    })

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        result = await pool.translate("hello", "en", "zh")

    assert result == "翻译文本"
    assert router.acompletion.await_count == 1, (
        "all-dead marks must be ignored so the role stays reachable"
    )


@pytest.mark.asyncio
async def test_marking_and_skipping_are_logged(
    pool_and_router, monkeypatch, caplog,
):
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_timeout_error())

    direct_calls: list[str] = []
    caplog.set_level(logging.WARNING, logger="ol.pool")
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        await pool.translate("hello", "en", "zh")
        await pool.translate("hello again", "en", "zh")

    assert "marking openai/spark-x2.6" in caplog.text
    assert "skipping openai/spark-x2.6" in caplog.text
    assert "dead-model memory (OL#191)" in caplog.text


@pytest.mark.asyncio
async def test_api_connection_error_also_marks_dead(
    pool_and_router, monkeypatch,
):
    """Connection errors use the same hard-failure marking path."""
    pool, router = pool_and_router
    try:
        conn_exc: BaseException = _APIConnectionError(
            "connection refused", llm_provider="test", model="translation",
        )
    except TypeError:  # OMNI_TEST_FAKE_LLM stub: plain Exception
        conn_exc = _APIConnectionError("connection refused")
    router.acompletion = AsyncMock(side_effect=conn_exc)
    direct_calls: list[str] = []
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        await pool.translate("hello", "en", "zh")

    assert router.acompletion.await_count == 1
    marks, _lock = pool._dead_marks_state()
    assert ("translation", "openai/spark-x2.6") in marks
