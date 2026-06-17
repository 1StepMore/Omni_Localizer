from unittest.mock import MagicMock, patch

import pytest

from ol_config.schema import LLMModelConfig, LLMModelRole, LLMPoolConfig
from ol_pool.router import ModelPool


class TestModelPool:
    @pytest.fixture
    def mock_config(self):
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(
                    provider="openai",
                    model="gpt-4o-mini",
                    priority=1,
                    role=LLMModelRole.TRANSLATION,
                ),
                LLMModelConfig(
                    provider="openai",
                    model="gpt-4o",
                    priority=2,
                    role=LLMModelRole.TRANSLATION,
                ),
            ],
            judging=[
                LLMModelConfig(
                    provider="anthropic",
                    model="claude-3-sonnet",
                    priority=1,
                    role=LLMModelRole.JUDGING,
                ),
                LLMModelConfig(
                    provider="anthropic",
                    model="claude-3-opus",
                    priority=2,
                    role=LLMModelRole.JUDGING,
                ),
            ],
            restoration=[
                LLMModelConfig(
                    provider="openai",
                    model="gpt-4o-mini",
                    priority=1,
                    role=LLMModelRole.RESTORATION,
                ),
                LLMModelConfig(
                    provider="openai",
                    model="gpt-4o-mini",
                    priority=2,
                    role=LLMModelRole.RESTORATION,
                ),
            ],
        )
        return MagicMock(llm_pool=pool)

    @patch("src.ol_pool.router.load_config")
    @patch("src.ol_pool.router.Router")
    def test_model_pool_initializes_router(self, mock_router_class, mock_load_config, mock_config):
        mock_load_config.return_value = mock_config
        pool = ModelPool()
        mock_router_class.assert_called_once()
        call_kwargs = mock_router_class.call_args.kwargs
        assert call_kwargs["routing_strategy"] == "simple-shuffle"
        assert call_kwargs["num_retries"] == 2
        assert call_kwargs["timeout"] == 120.0
        assert "fallbacks" in call_kwargs

    @patch("src.ol_pool.router.load_config")
    def test_build_model_list_creates_correct_structure(self, mock_load_config, mock_config):
        mock_load_config.return_value = mock_config
        pool = ModelPool()
        model_list = pool._build_model_list(mock_config.llm_pool)
        translation_models = [m for m in model_list if m["model_name"] == "translation"]
        judging_models = [m for m in model_list if m["model_name"] == "judging"]
        assert len(translation_models) == 2
        assert len(judging_models) == 2
        assert translation_models[0]["litellm_params"]["model"] == "openai/gpt-4o-mini"
        assert judging_models[0]["litellm_params"]["model"] == "anthropic/claude-3-sonnet"

    @patch("src.ol_pool.router.load_config")
    def test_build_model_list_uses_per_model_rpm(self, mock_load_config):
        """2026-06-17 round 3 (OPT-11): each model entry's `rpm` must come
        from LLMModelConfig.requests_per_minute, NOT a hardcoded constant.
        Regression guard for the NVIDIA 40 RPM fix where 3 NVIDIA models
        sharing 40 RPM previously inflated the budget to 1500 RPM via
        the hardcoded 500 in _build_model_list()."""
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(
                    provider="openai", model="glm-4-flash", priority=1,
                    role=LLMModelRole.TRANSLATION, requests_per_minute=500,
                ),
                LLMModelConfig(
                    provider="openai", model="deepseek-ai/deepseek-v4-flash",
                    priority=2, role=LLMModelRole.TRANSLATION,
                    requests_per_minute=40,
                ),
                LLMModelConfig(
                    provider="openai", model="moonshotai/kimi-k2.6",
                    priority=3, role=LLMModelRole.TRANSLATION,
                    requests_per_minute=40,
                ),
            ],
            judging=[
                LLMModelConfig(provider="openai", model="agnes-2.0-flash",
                               priority=1, role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="openai", model="glm-4-flash",
                               priority=2, role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="glm-4-flash",
                               priority=1, role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="openai", model="agnes-2.0-flash",
                               priority=2, role=LLMModelRole.RESTORATION),
            ],
        )
        cfg = MagicMock(llm_pool=pool)
        mock_load_config.return_value = cfg
        mp = ModelPool()
        model_list = mp._build_model_list(pool)

        rpm_by_model = {
            m["litellm_params"]["model"]: m["litellm_params"]["rpm"]
            for m in model_list if m["model_name"] == "translation"
        }
        assert rpm_by_model["openai/glm-4-flash"] == 500
        assert rpm_by_model["openai/deepseek-ai/deepseek-v4-flash"] == 40
        assert rpm_by_model["openai/moonshotai/kimi-k2.6"] == 40

    @patch("src.ol_pool.router.load_config")
    def test_build_model_list_rpm_in_litellm_params_canonical(self, mock_load_config):
        """FIX-#7: rpm lives inside litellm_params (canonical per litellm types/router.py:201-203)."""
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(
                    provider="openai", model="glm-4-flash", priority=1,
                    role=LLMModelRole.TRANSLATION, requests_per_minute=500,
                ),
                LLMModelConfig(
                    provider="openai", model="deepseek-ai/deepseek-v4-flash",
                    priority=2, role=LLMModelRole.TRANSLATION,
                    requests_per_minute=40,
                ),
            ],
            judging=[
                LLMModelConfig(provider="openai", model="a", priority=1,
                               role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="openai", model="b", priority=2,
                               role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="a", priority=1,
                               role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="openai", model="b", priority=2,
                               role=LLMModelRole.RESTORATION),
            ],
        )
        cfg = MagicMock(llm_pool=pool)
        mock_load_config.return_value = cfg
        mp = ModelPool()
        model_list = mp._build_model_list(pool)
        for entry in model_list:
            assert "rpm" not in entry, (
                f"Top-level 'rpm' should be removed (FIX-#7). Got entry: {entry}"
            )
            assert "rpm" in entry["litellm_params"], (
                f"rpm must be in litellm_params. Got: {entry['litellm_params']}"
            )

    @patch("src.ol_pool.router.load_config")
    @patch("src.ol_pool.router.Router")
    def test_router_init_enables_enforce_model_rate_limits(
        self, mock_router_class, mock_load_config,
    ):
        """OPT-13: Router init must pass enforce_model_rate_limits so per-model rpm is hard-enforced."""
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(provider="openai", model="a", priority=1,
                               role=LLMModelRole.TRANSLATION),
                LLMModelConfig(provider="openai", model="b", priority=2,
                               role=LLMModelRole.TRANSLATION),
            ],
            judging=[
                LLMModelConfig(provider="openai", model="a", priority=1,
                               role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="openai", model="b", priority=2,
                               role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="a", priority=1,
                               role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="openai", model="b", priority=2,
                               role=LLMModelRole.RESTORATION),
            ],
        )
        cfg = MagicMock(llm_pool=pool)
        mock_load_config.return_value = cfg
        ModelPool()
        call_kwargs = mock_router_class.call_args.kwargs
        assert "optional_pre_call_checks" in call_kwargs
        assert "enforce_model_rate_limits" in call_kwargs["optional_pre_call_checks"]

    @patch("src.ol_pool.router.load_config")
    def test_metrics_returns_rate_limit_counter_copy(self, mock_load_config):
        """FIX-#18: `metrics()` returns a shallow copy of the internal rate-limit hit counter."""
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(provider="openai", model="a", priority=1,
                               role=LLMModelRole.TRANSLATION),
                LLMModelConfig(provider="openai", model="b", priority=2,
                               role=LLMModelRole.TRANSLATION),
            ],
            judging=[
                LLMModelConfig(provider="openai", model="a", priority=1,
                               role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="openai", model="b", priority=2,
                               role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="a", priority=1,
                               role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="openai", model="b", priority=2,
                               role=LLMModelRole.RESTORATION),
            ],
        )
        cfg = MagicMock(llm_pool=pool)
        mock_load_config.return_value = cfg
        mp = ModelPool()
        assert mp.metrics() == {}
        mp._rate_limit_hits["translation"] = 3
        assert mp.metrics() == {"translation": 3}
        snapshot = mp.metrics()
        snapshot["judging"] = 99
        assert "judging" not in mp._rate_limit_hits

    @patch("src.ol_pool.router.load_config")
    def test_build_fallbacks_skips_zero_rpm_models(self, mock_load_config):
        """FIX-#17: models with requests_per_minute <= 0 are excluded from
        fallback chains. Pydantic ge=1 prevents this at config load, but
        attribute mutation after construction (e.g. test setup) can bypass
        validation. The filter is belt-and-suspenders.
        """
        from ol_pool.router import _pool_cache as router_cache
        router_cache.clear()
        alive = LLMModelConfig(
            provider="openai", model="alive", priority=1,
            role=LLMModelRole.TRANSLATION, requests_per_minute=40,
        )
        dead = LLMModelConfig(
            provider="openai", model="dead", priority=2,
            role=LLMModelRole.TRANSLATION, requests_per_minute=10,
        )
        # Bypass Pydantic ge=1 by mutating after construction
        dead.requests_per_minute = 0
        pool = LLMPoolConfig(
            translation=[alive, dead],
            judging=[
                LLMModelConfig(provider="openai", model="j1", priority=1,
                               role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="openai", model="j2", priority=2,
                               role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="r1", priority=1,
                               role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="openai", model="r2", priority=2,
                               role=LLMModelRole.RESTORATION),
            ],
        )
        cfg = MagicMock(llm_pool=pool)
        mock_load_config.return_value = cfg
        mp = ModelPool()
        fallbacks = mp._build_fallbacks(pool)
        for entry in fallbacks:
            if "translation" in entry:
                assert "openai/dead" not in entry["translation"], (
                    f"rpm=0 model should be excluded; got {entry}"
                )

    def test_litellm_local_model_cost_map_env_set(self):
        """FIX-A (round 6): router.py must set LITELLM_LOCAL_MODEL_COST_MAP
        before importing litellm so the remote cost-map fetch is skipped
        on every Router init (no more WARNING spam in OMO logs).
        """
        import os
        assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP", "").lower() == "true", (
            "LITELLM_LOCAL_MODEL_COST_MAP must be 'True' (or 'true') at import time"
        )

    def test_get_instance_invalidates_on_config_mtime_change(self, tmp_path):
        """FIX-#11: _pool_cache mtime invalidation. When the config file
        is modified on disk, get_instance() must return a freshly-built
        ModelPool (not the cached one) so the new config takes effect
        without restarting the process.
        """
        from ol_pool.router import _pool_cache as router_cache
        # Clear cache for isolation
        router_cache.clear()
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text("project_id: test\n")
        # First call: caches an instance
        with patch("ol_pool.router.load_config") as mock_load:
            mock_load.return_value = MagicMock(llm_pool=MagicMock(
                translation=[
                    LLMModelConfig(provider="openai", model="a", priority=1,
                                   role=LLMModelRole.TRANSLATION),
                    LLMModelConfig(provider="openai", model="b", priority=2,
                                   role=LLMModelRole.TRANSLATION),
                ],
                judging=[
                    LLMModelConfig(provider="openai", model="a", priority=1,
                                   role=LLMModelRole.JUDGING),
                    LLMModelConfig(provider="openai", model="b", priority=2,
                                   role=LLMModelRole.JUDGING),
                ],
                restoration=[
                    LLMModelConfig(provider="openai", model="a", priority=1,
                                   role=LLMModelRole.RESTORATION),
                    LLMModelConfig(provider="openai", model="b", priority=2,
                                   role=LLMModelRole.RESTORATION),
                ],
            ))
            mp1 = ModelPool.get_instance(str(cfg_file))
            # Touch the file to update mtime (os.utime to ensure forward change)
            import os
            new_mtime = os.stat(cfg_file).st_mtime + 5
            os.utime(cfg_file, (new_mtime, new_mtime))
            mp2 = ModelPool.get_instance(str(cfg_file))
            # Different instance after mtime change
            assert mp1 is not mp2, (
                f"Expected new ModelPool after mtime change; got same instance"
            )
        # Clean up
        router_cache.clear()

    @pytest.mark.asyncio
    @patch("src.ol_pool.router.load_config")
    async def test_translate_returns_placeholder(self, mock_load_config, mock_config):
        mock_load_config.return_value = mock_config
        pool = ModelPool()
        result = await pool.translate("hello", "en", "zh")
        assert result == "placeholder"

    @pytest.mark.asyncio
    @patch("src.ol_pool.router.load_config")
    async def test_judge_returns_placeholder(self, mock_load_config, mock_config):
        mock_load_config.return_value = mock_config
        pool = ModelPool()
        result = await pool.judge("hello", "你好", "en", "zh")
        assert result["score"] == 0
        assert result["reason"] == "placeholder"
