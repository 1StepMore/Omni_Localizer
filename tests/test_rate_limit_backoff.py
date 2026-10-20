"""429 backoff: exponential + Retry-After + jitter, no fixed blind waits.

Covers the pure ``compute_rate_limit_backoff`` helper and both wait sites in
``ModelPool`` (the first-tier retry loop and intra-role failover).
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ol_pool.router as router_mod
from ol_config.schema import (
    LLMModelConfig,
    LLMModelRole,
    LLMPoolConfig,
    RateLimitBackoffConfig,
)
from ol_pool.router import (
    ModelPool,
    RateLimitError as _RateLimitError,
    compute_rate_limit_backoff,
)


def _rate_limit_error(model: str = "translation", **extra) -> BaseException:
    """Build a rate-limit error usable with both the stub and real litellm."""
    try:
        exc = _RateLimitError("rate limited", model=model, llm_provider="test")
    except TypeError:  # OMNI_TEST_FAKE_LLM stub: plain Exception
        exc = _RateLimitError("rate limited")
    for key, value in extra.items():
        setattr(exc, key, value)
    return exc


def _response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].finish_reason = "stop"
    response.choices[0].message.content = content
    response.usage = None
    return response


def _pool_config(
    *,
    translation_models: int = 2,
    max_attempts: int = 4,
    base: float = 5.0,
    max_delay: float = 60.0,
    jitter: bool = False,
) -> LLMPoolConfig:
    providers = [("amd", "deepseek-v4.1-flash"), ("zhipu", "glm-4.7-flash"),
                 ("stealth", "cat-jam:free")]
    translation = [
        LLMModelConfig(
            provider=providers[i][0], model=providers[i][1], priority=i + 1,
            role=LLMModelRole.TRANSLATION,
            api_key=f"key-{i}", base_url=f"https://{providers[i][0]}.example/v1",
        )
        for i in range(translation_models)
    ]
    return LLMPoolConfig(
        translation=translation,
        judging=[
            LLMModelConfig(provider="judge", model="j1", priority=1,
                           role=LLMModelRole.JUDGING, api_key="jk"),
            LLMModelConfig(provider="judge", model="j2", priority=2,
                           role=LLMModelRole.JUDGING, api_key="jk"),
        ],
        restoration=[
            LLMModelConfig(provider="restore", model="r1", priority=1,
                           role=LLMModelRole.RESTORATION, api_key="rk"),
            LLMModelConfig(provider="restore", model="r2", priority=2,
                           role=LLMModelRole.RESTORATION, api_key="rk"),
        ],
        rate_limit_backoff=RateLimitBackoffConfig(
            base_delay_s=base,
            max_delay_s=max_delay,
            max_attempts_per_model=max_attempts,
            jitter=jitter,
        ),
    )


@pytest.fixture
def make_pool(monkeypatch):
    """Build a real ModelPool wired to a mocked Router (not FAKE_LLM mode)."""
    created = []

    def _make(config: LLMPoolConfig):
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
        with patch("ol_pool.router.load_config") as load_config, \
                patch("ol_pool.router.Router") as router_cls:
            load_config.return_value = SimpleNamespace(llm_pool=config)
            pool = ModelPool()
            pool._test_mode = False
            created.append(pool)
            return pool, router_cls.return_value

    return _make


@pytest.fixture
def sleep_recorder(monkeypatch):
    waits: list[float] = []

    async def _sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(router_mod.asyncio, "sleep", _sleep)
    return waits


class TestComputeRateLimitBackoff:
    def test_exponential_series_is_capped_and_deterministic(self):
        cfg = RateLimitBackoffConfig(
            base_delay_s=5.0, max_delay_s=60.0, jitter=False,
        )
        assert [compute_rate_limit_backoff(a, None, cfg) for a in range(4)] == [
            5.0, 10.0, 20.0, 40.0,
        ]
        assert compute_rate_limit_backoff(4, None, cfg) == 60.0
        assert compute_rate_limit_backoff(8, None, cfg) == 60.0

    def test_retry_after_header_wins_and_is_capped(self):
        cfg = RateLimitBackoffConfig(
            base_delay_s=5.0, max_delay_s=60.0, jitter=False,
        )
        exc = _rate_limit_error(
            response=SimpleNamespace(headers={"retry-after": "42"}),
        )
        assert compute_rate_limit_backoff(0, exc, cfg) == 42.0

        slow = _rate_limit_error(
            response=SimpleNamespace(headers={"retry-after": "120"}),
        )
        assert compute_rate_limit_backoff(0, slow, cfg) == 60.0

    def test_retry_after_alternate_headers_and_http_date(self):
        cfg = RateLimitBackoffConfig(jitter=False)
        assert compute_rate_limit_backoff(
            0, _rate_limit_error(response_headers={"Retry-After": "7"}), cfg,
        ) == 7.0
        assert compute_rate_limit_backoff(
            0, _rate_limit_error(headers={"retry-after": "9"}), cfg,
        ) == 9.0
        # A past HTTP-date must not produce a negative wait.
        assert compute_rate_limit_backoff(
            0,
            _rate_limit_error(headers={"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}),
            cfg,
        ) == 0.0

    def test_missing_or_malformed_retry_after_falls_back_to_exponential(self):
        cfg = RateLimitBackoffConfig(base_delay_s=5.0, jitter=False)
        assert compute_rate_limit_backoff(1, _rate_limit_error(headers={"retry-after": "n/a"}), cfg) == 10.0
        assert compute_rate_limit_backoff(1, None, cfg) == 10.0

    def test_jitter_adds_at_most_25_percent(self, monkeypatch):
        cfg = RateLimitBackoffConfig(base_delay_s=10.0, jitter=True)
        monkeypatch.setattr(router_mod.random, "uniform", lambda lo, hi: hi)
        assert compute_rate_limit_backoff(0, None, cfg) == 12.5


class TestBackoffConfiguration:
    def test_defaults_apply_without_a_rate_limit_backoff_block(self):
        pool = _pool_config()
        # Rebuild without the explicit block the helper adds.
        data = pool.model_dump()
        data.pop("rate_limit_backoff")
        bare = LLMPoolConfig(**data)
        assert bare.rate_limit_backoff == RateLimitBackoffConfig()
        assert bare.rate_limit_backoff.enabled is True
        assert bare.rate_limit_backoff.max_attempts_per_model == 4
        wait = compute_rate_limit_backoff(0, None, bare.rate_limit_backoff)
        assert 5.0 <= wait <= 6.25  # base 5s + up to 25% jitter

    def test_pool_uses_config_and_falls_back_for_test_doubles(self, make_pool):
        cfg = _pool_config(base=3.0, max_attempts=2, jitter=False)
        pool, _router = make_pool(cfg)
        assert pool._rate_limit_backoff is cfg.rate_limit_backoff

        doubled = ModelPool.__new__(ModelPool)
        doubled._rate_limit_backoff = RateLimitBackoffConfig()
        assert doubled._rate_limit_backoff.enabled is True


class TestTranslateLoopBackoff:
    @pytest.mark.asyncio
    async def test_two_429s_then_success_uses_configured_waits(
        self, make_pool, sleep_recorder,
    ):
        pool, router = make_pool(_pool_config())
        router.acompletion = AsyncMock(
            side_effect=[_rate_limit_error(), _rate_limit_error(), _response("翻译文本")],
        )

        result = await pool.translate("hello", "en", "zh")

        assert result == "翻译文本"
        assert router.acompletion.await_count == 3
        assert sleep_recorder == [5.0, 10.0]

    @pytest.mark.asyncio
    async def test_retry_after_is_honoured_in_the_retry_loop(
        self, make_pool, sleep_recorder,
    ):
        pool, router = make_pool(_pool_config())
        router.acompletion = AsyncMock(
            side_effect=[
                _rate_limit_error(
                    response=SimpleNamespace(headers={"retry-after": "12"}),
                ),
                _response("翻译文本"),
            ],
        )

        assert await pool.translate("hello", "en", "zh") == "翻译文本"
        assert sleep_recorder == [12.0]

    @pytest.mark.asyncio
    async def test_second_failure_switches_model_when_max_attempts_is_2(
        self, make_pool, sleep_recorder, monkeypatch,
    ):
        pool, router = make_pool(_pool_config(max_attempts=2))
        router.acompletion = AsyncMock(side_effect=_rate_limit_error())

        direct_calls: list[str] = []

        async def _direct(model, messages, temperature, max_tokens):
            direct_calls.append(f"{model.provider}/{model.model}")
            if model.provider == "amd":
                raise _rate_limit_error(f"{model.provider}/{model.model}")
            return _response("翻译文本")

        monkeypatch.setattr(pool, "_direct_acompletion", _direct)

        result = await pool.translate("hello", "en", "zh")

        assert result == "翻译文本"
        assert router.acompletion.await_count == 2
        assert direct_calls == ["amd/deepseek-v4.1-flash", "zhipu/glm-4.7-flash"]
        assert sleep_recorder == [5.0, 5.0, 10.0]

    @pytest.mark.asyncio
    async def test_intra_role_failover_uses_the_same_computed_backoff(
        self, make_pool, sleep_recorder, monkeypatch, caplog,
    ):
        pool, router = make_pool(_pool_config(max_attempts=1, translation_models=3))
        router.acompletion = AsyncMock(side_effect=_rate_limit_error())

        direct_calls: list[str] = []

        async def _direct(model, messages, temperature, max_tokens):
            direct_calls.append(f"{model.provider}/{model.model}")
            raise _rate_limit_error(f"{model.provider}/{model.model}")

        monkeypatch.setattr(pool, "_direct_acompletion", _direct)
        caplog.set_level(logging.WARNING, logger="ol.pool")

        with pytest.raises(_RateLimitError):
            await pool.translate("hello", "en", "zh")

        assert router.acompletion.await_count == 1
        assert direct_calls == [
            "amd/deepseek-v4.1-flash",
            "zhipu/glm-4.7-flash",
            "stealth/cat-jam:free",
        ]
        assert sleep_recorder == [5.0, 10.0, 20.0]
        assert "retry_after=none" in caplog.text
        assert "remaining same-role models=" in caplog.text

    @pytest.mark.asyncio
    async def test_all_models_rate_limited_re_raises_original_fail_closed(
        self, make_pool, sleep_recorder, monkeypatch,
    ):
        pool, router = make_pool(_pool_config(translation_models=2))
        original = _rate_limit_error()
        router.acompletion = AsyncMock(side_effect=original)

        async def _direct(model, messages, temperature, max_tokens):
            raise _rate_limit_error(f"{model.provider}/{model.model}")

        monkeypatch.setattr(pool, "_direct_acompletion", _direct)

        with pytest.raises(_RateLimitError) as excinfo:
            await pool.translate("hello", "en", "zh")

        assert excinfo.value is original
        assert all("judging" not in str(call) for call in router.acompletion.await_args_list)
