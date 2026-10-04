from unittest.mock import MagicMock, patch

import pytest

from ol_config.schema import LLMModelConfig, LLMModelRole, LLMPoolConfig
from ol_pool.router import ModelPool, partition_usable_models


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
        import os
        original = os.environ.pop("OMNI_TEST_FAKE_LLM", None)
        try:
            mock_load_config.return_value = mock_config
            pool = ModelPool()
            mock_router_class.assert_called_once()
            call_kwargs = mock_router_class.call_args.kwargs
            assert call_kwargs["routing_strategy"] == "simple-shuffle"
            assert call_kwargs["num_retries"] == 2
            assert call_kwargs["timeout"] == 120.0
            assert "fallbacks" in call_kwargs
        finally:
            if original is not None:
                os.environ["OMNI_TEST_FAKE_LLM"] = original

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
    def test_router_init_omits_enforce_model_rate_limits(
        self, mock_router_class, mock_load_config,
    ):
        """E2E-83: Router init must NOT pass enforce_model_rate_limits.

        The previous pre-call check maintained an in-process per-model RPM
        token bucket that raised litellm.RouterRateLimitError synchronously,
        fast-failing large requests and cascading into 10/20/40s backoffs.
        Per-model RPM is still enforced via litellm_params['rpm'] entries;
        rejection now comes from the provider's HTTP 429 instead.
        """
        import os
        original = os.environ.pop("OMNI_TEST_FAKE_LLM", None)
        try:
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
            opcc = call_kwargs.get("optional_pre_call_checks")
            assert "optional_pre_call_checks" not in call_kwargs or (
                "enforce_model_rate_limits" not in opcc
            ), (
                "pre-call 'enforce_model_rate_limits' must not be set "
                "(E2E-83 root cause)"
            )
        finally:
            if original is not None:
                os.environ["OMNI_TEST_FAKE_LLM"] = original

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
        """FIX-#17: a role whose only usable model has requests_per_minute <= 0
        must never be named as a fallback TARGET — such a model is
        dead-on-arrival, and rerouting onto it converts a real retry into a
        guaranteed failure. Pydantic ge=1 prevents this at config load, but
        attribute mutation after construction (e.g. test setup) can bypass
        validation. The filter is belt-and-suspenders.

        The assertion is role-level, not model-id-level: since e2e#141
        fallback values are litellm model GROUP names (roles), not
        `provider/model` ids, so a dead model can only be excluded by
        disqualifying its whole role.
        """
        from ol_pool.router import _pool_cache as router_cache
        router_cache.clear()
        # Bypass Pydantic ge=1 by mutating after construction; both models of
        # the role must be dead for the role to lose target eligibility
        # (LLMPoolConfig itself requires >= 2 models per role).
        dead = LLMModelConfig(
            provider="openai", model="dead-1", priority=1,
            role=LLMModelRole.RESTORATION, requests_per_minute=40,
        )
        dead.requests_per_minute = 0
        dead2 = LLMModelConfig(
            provider="openai", model="dead-2", priority=2,
            role=LLMModelRole.RESTORATION, requests_per_minute=40,
        )
        dead2.requests_per_minute = 0
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(provider="openai", model="t1", priority=1,
                               role=LLMModelRole.TRANSLATION),
                LLMModelConfig(provider="openai", model="t2", priority=2,
                               role=LLMModelRole.TRANSLATION),
            ],
            judging=[
                LLMModelConfig(provider="openai", model="j1", priority=1,
                               role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="openai", model="j2", priority=2,
                               role=LLMModelRole.JUDGING),
            ],
            restoration=[dead, dead2],
        )
        cfg = MagicMock(llm_pool=pool)
        mock_load_config.return_value = cfg
        mp = ModelPool()
        registered = {
            entry["model_name"] for entry in mp._build_model_list(pool)
        }
        assert "restoration" in registered, (
            f"restoration must stay a registered group (only its TARGET "
            f"eligibility is in question); registered={sorted(registered)}"
        )
        fallbacks = mp._build_fallbacks(pool)
        targets = [t for entry in fallbacks for ts in entry.values() for t in ts]
        assert "restoration" not in targets, (
            f"rpm=0-only role must not be a fallback target; got {fallbacks}"
        )
        assert "translation" in targets, (
            f"a role with a live model must stay a usable target, else the "
            f"liveness net is empty; got {fallbacks}"
        )

    @patch("src.ol_pool.router.load_config")
    def test_fallback_keys_and_targets_are_registered_model_group_names(
        self, mock_load_config, mock_config,
    ):
        """e2e-test-suite#141: BOTH the key and every value of a litellm
        `fallbacks` entry must be names of groups registered in `model_list`.

        `_build_model_list` registers `model_name = role`, so the only legal
        fallback key/value is a ROLE name. The pre-fix `_build_fallbacks`
        emitted `{role: ["provider/model", ...]}`, which named no registered
        group: litellm logged `No fallback model group found for original
        model_group=...` and the rate-limit fallback never engaged, so a
        provider 429 became a hard failure instead of a reroute.
        """
        mock_load_config.return_value = mock_config
        mp = ModelPool()
        registered = {
            entry["model_name"]
            for entry in mp._build_model_list(mock_config.llm_pool)
        }
        assert registered, "fixture must register at least one model group"

        fallbacks = mp._build_fallbacks(mock_config.llm_pool)
        assert fallbacks, "the cross-role liveness net must not be empty"
        for entry in fallbacks:
            assert len(entry) == 1, f"one group per entry, got {entry}"
            for group, targets in entry.items():
                assert group in registered, (
                    f"fallback KEY {group!r} is not a registered model_group "
                    f"in _build_model_list; registered={sorted(registered)}; "
                    f"entry={entry}"
                )
                assert targets, f"empty target list for {group!r}: {entry}"
                for target in targets:
                    assert target in registered, (
                        f"fallback TARGET {target!r} is not a registered "
                        f"model_group — litellm routes fallback values AS "
                        f"model groups, so a provider/model id can never "
                        f"resolve. registered={sorted(registered)}; "
                        f"entry={entry}"
                    )

    @patch("src.ol_pool.router.load_config")
    def test_fallback_never_names_a_role_the_router_never_received(
        self, mock_load_config, mock_config,
    ):
        """OL#99 provenance, restated for group names: a role that lost every
        model to the env filter is unregistered, so it must appear neither as a
        fallback key nor as a fallback target. Combined with FIX-#17 (a
        zero-RPM-only role may not be a target), the fallback list may only
        name groups that are registered AND have a live model.
        """
        mock_load_config.return_value = mock_config
        mp = ModelPool()
        pool = mock_config.llm_pool
        # Same filtered mapping __init__ hands to _build_model_list (OL#99).
        # Read via partition_usable_models rather than mp._usable_by_role:
        # OMNI_TEST_FAKE_LLM=1 short-circuits __init__ before that attr exists.
        usable, _skipped = partition_usable_models(pool)

        starved = dict(usable, judging=[])
        registered = {
            entry["model_name"]
            for entry in mp._build_model_list(pool, usable=starved)
        }
        assert "judging" not in registered, "judging must be starved for this test"
        for entry in mp._build_fallbacks(pool, usable=starved):
            for group, targets in entry.items():
                assert group in registered, f"unregistered key {group!r} in {entry}"
                assert "judging" not in targets, (
                    f"starved role named as fallback target in {entry}"
                )

        rpm_dead = {
            role: [
                model.model_copy(update={"requests_per_minute": 0})
                for model in models
            ]
            for role, models in usable.items()
        }
        for entry in mp._build_fallbacks(pool, usable=rpm_dead):
            for targets in entry.values():
                assert "restoration" not in targets, (
                    f"rpm=0-only role named as fallback target in {entry}"
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
                "Expected new ModelPool after mtime change; got same instance"
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
        if hasattr(pool, "_fake_pool"):
            assert result["score"] > 0
        else:
            assert result["score"] == 0
            assert result["reason"] == "placeholder"
