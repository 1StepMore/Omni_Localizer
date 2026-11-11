"""Hard transport failures step to the next priority tier (OL#187).

``translate()`` used to retry timeouts on the same deployment and let
connection / 5xx errors fall straight through, so litellm's internal retry
chain — not OL's priority semantics — decided when the backup tier got a turn.
These tests pin the new contract: a retryable transport failure skips the
failed tier immediately, without a 429-style backoff.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ol_pool.router as router_mod
from ol_config.schema import LLMModelConfig, LLMModelRole, LLMPoolConfig
from ol_pool.router import APIConnectionError as _APIConnectionError
from ol_pool.router import ModelPool
from ol_pool.router import Timeout as _Timeout


def _api_connection_error() -> BaseException:
    """Build an APIConnectionError usable with both stubs and real litellm."""
    try:
        return _APIConnectionError(
            "connection refused", llm_provider="test", model="translation",
        )
    except TypeError:  # OMNI_TEST_FAKE_LLM stub: plain Exception
        return _APIConnectionError("connection refused")


def _timeout_error() -> BaseException:
    try:
        return _Timeout(
            "timed out", model="translation", llm_provider="test",
        )
    except TypeError:  # OMNI_TEST_FAKE_LLM stub: plain Exception
        return _Timeout("timed out")


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
async def test_connection_failure_switches_to_next_tier_without_same_tier_retry(
    pool_and_router, monkeypatch, caplog,
):
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_api_connection_error())

    direct_calls: list[str] = []
    caplog.set_level(logging.WARNING, logger="ol.pool")
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        result = await pool.translate("hello", "en", "zh")

    assert result == "翻译文本"
    assert direct_calls == ["openai/deepseek-flash"], (
        "a hard failure must skip the failed tier and use the next priority"
    )
    assert router.acompletion.await_count == 1, (
        "hard failures must not be retried on the same deployment"
    )
    assert "stepping to the next priority tier" in caplog.text


@pytest.mark.asyncio
async def test_timeout_switches_tier_without_same_tier_retry(
    pool_and_router, monkeypatch,
):
    """OL#187: a timeout must step to the next tier immediately.

    Retrying the SAME deployment multiplied the wait by
    ``max_attempts_per_model`` (measured 4 x 120s on a dead primary) before
    any failover could happen.
    """
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_timeout_error())

    direct_calls: list[str] = []
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        result = await pool.translate("hello", "en", "zh")

    assert result == "翻译文本", "timeout must fail over instead of raising"
    assert router.acompletion.await_count == 1, (
        "a timed-out deployment must not be retried on the same tier"
    )
    assert direct_calls == ["openai/deepseek-flash"], (
        "timeout failover must skip the tier that timed out"
    )


@pytest.mark.asyncio
async def test_non_retryable_error_raises_and_never_fails_over(
    pool_and_router, monkeypatch,
):
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=ValueError("bad request"))
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    direct = AsyncMock()
    with patch.object(ModelPool, "_direct_acompletion", new=direct):
        with pytest.raises(ValueError):
            await pool.translate("hello", "en", "zh")

    assert direct.await_count == 0, (
        "non-retryable errors (bad request / auth) must fail fast, not fail over"
    )


@pytest.mark.asyncio
async def test_hard_failure_does_not_backoff(pool_and_router, monkeypatch):
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_api_connection_error())

    direct_calls: list[str] = []
    sleep = AsyncMock()
    monkeypatch.setattr(router_mod.asyncio, "sleep", sleep)

    with patch.object(
        ModelPool, "_direct_acompletion", new=AsyncMock(
            side_effect=_direct_recorder(direct_calls),
        ),
    ):
        result = await pool.translate("hello", "en", "zh")

    assert result == "翻译文本"
    assert sleep.await_count >= 1, "failover keeps a cancellable sleep(0)"
    assert all(call.args == (0,) for call in sleep.await_args_list), (
        "hard failures must not inherit the 429 rate-limit backoff"
    )
