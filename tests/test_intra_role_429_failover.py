"""Intra-role 429 failover: step to the next translation priority, never across roles.

The Router registers every model of a role under one litellm group name, so a
rate-limited translation group has no expressible fallback. ``translate()``
therefore steps through ``_usable_by_role["translation"]`` by ``priority`` with
direct ``litellm.acompletion`` calls. Cross-role downgrade stays forbidden.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ol_pool.router as router_mod
from ol_config.schema import LLMModelConfig, LLMModelRole, LLMPoolConfig
from ol_pool.router import ModelPool, RateLimitError as _RateLimitError


def _rate_limit_error(model: str = "unknown") -> BaseException:
    """Build a rate-limit error usable with both the stub and real litellm."""
    try:
        return _RateLimitError(
            "rate limited", model=model, llm_provider="test",
        )
    except TypeError:  # OMNI_TEST_FAKE_LLM stub: plain Exception
        return _RateLimitError("rate limited", model, "test")


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
                provider="amd", model="deepseek-v4.1-flash", priority=1,
                role=LLMModelRole.TRANSLATION,
                api_key="amd-key", base_url="https://amd.example/v1",
            ),
            LLMModelConfig(
                provider="zhipu", model="glm-4.7-flash", priority=2,
                role=LLMModelRole.TRANSLATION,
                api_key="zhipu-key", base_url="https://zhipu.example/v1",
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
        # A non-subscriptable result makes ModelPool take the "config is the
        # whole object" branch instead of result[0].
        load_config.return_value = SimpleNamespace(llm_pool=config)
        pool = ModelPool()
        pool._test_mode = False
        yield pool, router_cls.return_value


@pytest.mark.asyncio
async def test_rate_limited_first_model_switches_to_next_same_role_model(
    pool_and_router, monkeypatch, caplog,
):
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_rate_limit_error())

    direct_calls: list[str] = []

    async def _direct(**kwargs):
        direct_calls.append(kwargs["model"])
        if kwargs["model"].startswith("amd/"):
            raise _rate_limit_error(kwargs["model"])
        return _response("翻译文本")

    fake_litellm = MagicMock()
    fake_litellm.acompletion = AsyncMock(side_effect=_direct)
    monkeypatch.setattr(router_mod, "litellm", fake_litellm)
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())
    caplog.set_level(logging.WARNING, logger="ol.pool")

    result = await pool.translate("hello", "en", "zh")

    assert result == "翻译文本", "a later same-role tier must return its translation"
    assert direct_calls == [
        "amd/deepseek-v4.1-flash",
        "zhipu/glm-4.7-flash",
    ], "must step through translation models in priority order"
    # First-tier calls stay on the role group; direct calls stay on translation.
    assert all(
        call.kwargs["model"] == "translation"
        for call in router.acompletion.await_args_list
    )
    assert all("judging" not in model for model in direct_calls)
    assert "switching to" in caplog.text


@pytest.mark.asyncio
async def test_all_same_role_models_rate_limited_raises_and_never_crosses_roles(
    pool_and_router, monkeypatch,
):
    pool, router = pool_and_router
    router.acompletion = AsyncMock(side_effect=_rate_limit_error())
    assert pool._usable_by_role["judging"], "judging must be available but unused"

    direct_calls: list[str] = []

    async def _direct(**kwargs):
        direct_calls.append(kwargs["model"])
        raise _rate_limit_error(kwargs["model"])

    fake_litellm = MagicMock()
    fake_litellm.acompletion = AsyncMock(side_effect=_direct)
    monkeypatch.setattr(router_mod, "litellm", fake_litellm)
    monkeypatch.setattr(router_mod.asyncio, "sleep", AsyncMock())

    with pytest.raises(_RateLimitError):
        await pool.translate("hello", "en", "zh")

    assert direct_calls == [
        "amd/deepseek-v4.1-flash",
        "zhipu/glm-4.7-flash",
    ], "every same-role model is tried exactly once, in priority order"
    every_model = direct_calls + [
        call.kwargs["model"] for call in router.acompletion.await_args_list
    ]
    assert every_model, "translate() must actually attempt calls"
    assert all("judging" not in model for model in every_model), (
        f"cross-role downgrade is forbidden; calls={every_model}"
    )
