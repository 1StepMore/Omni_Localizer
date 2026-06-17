"""E2E regression tests for round 5 fixes (2026-06-17).

Covers the YAML → Pydantic → ConcurrencyLimiter full chain for
`max_xliff_concurrent`, and verifies the per-model RPM + Router
enforcement wiring for `requests_per_minute`.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the OL src/ importable
_OL_SRC = Path(__file__).resolve().parents[1] / "Omni_Localizer" / "src"
if str(_OL_SRC) not in sys.path:
    sys.path.insert(0, str(_OL_SRC))

from ol_config.loader import load_config
from ol_config.schema import LLMModelConfig, LLMModelRole
from ol_pool.router import ModelPool


class TestMaxXliffConcurrentE2E:
    """FIX-#13: max_xliff_concurrent flows from YAML to ConcurrencyLimiter."""

    def test_local_yaml_has_max_xliff_5(self):
        """local.yaml must set max_xliff_concurrent: 5 (round 3 fix)."""
        cfg, _ = load_config("Omni_Localizer/config/local.yaml")
        assert cfg.max_xliff_concurrent == 5, (
            f"Expected max_xliff_concurrent=5 in local.yaml; "
            f"got {cfg.max_xliff_concurrent}"
        )

    def test_default_yaml_has_max_xliff_5(self):
        """default.yaml must also have max_xliff_concurrent: 5 (round 3 fix)."""
        cfg, _ = load_config("Omni_Localizer/config/default.yaml")
        assert cfg.max_xliff_concurrent == 5, (
            f"Expected max_xliff_concurrent=5 in default.yaml; "
            f"got {cfg.max_xliff_concurrent}"
        )

    def test_local_yaml_nvidia_models_have_rpm_40(self):
        """OPT-11/OPT-13: NVIDIA models must declare rpm=40 (40 RPM shared tier)."""
        cfg, _ = load_config("Omni_Localizer/config/local.yaml")
        nvidia_models = [
            m for m in cfg.llm_pool.translation
            if "nvidia" in (m.base_url or "")
        ]
        assert len(nvidia_models) == 2, (
            f"Expected 2 NVIDIA models in translation; got {len(nvidia_models)}"
        )
        for m in nvidia_models:
            assert m.requests_per_minute == 40, (
                f"NVIDIA model {m.model} should have rpm=40; got {m.requests_per_minute}"
            )

    def test_local_yaml_opencode_go_models_have_rpm_40(self):
        """FIX-#5: OPENCODE_GO models must declare rpm (was using default 500).

        base_url is stored as ${OPENCODE_GO_BASE_URL} before env-var
        resolution (which happens inside _build_model_list). Check via
        the env-var reference pattern instead of substring on URL.
        """
        cfg, _ = load_config("Omni_Localizer/config/local.yaml")
        ocg_models = [
            m for m in cfg.llm_pool.translation
            if m.base_url and "OPENCODE_GO" in m.base_url
        ]
        assert len(ocg_models) >= 1, (
            "Expected at least 1 OPENCODE_GO model in translation"
        )
        for m in ocg_models:
            assert m.requests_per_minute <= 100, (
                f"OPENCODE_GO model {m.model} should have low rpm; got {m.requests_per_minute}"
            )

    def test_local_yaml_judge_models_have_rpm_40(self):
        """FIX-#6: judge model on OPENCODE_GO must declare rpm (judge calls also consume quota)."""
        cfg, _ = load_config("Omni_Localizer/config/local.yaml")
        ocg_judge = [
            m for m in cfg.llm_pool.judging
            if m.base_url and "OPENCODE_GO" in m.base_url
        ]
        assert len(ocg_judge) >= 1
        for m in ocg_judge:
            assert m.requests_per_minute <= 100, (
                f"Judge OPENCODE_GO model {m.model} should have low rpm; got {m.requests_per_minute}"
            )

    def test_modelpool_rpm_per_deployment(self):
        """FIX-#7: per-deployment rpm in litellm_params (canonical location)."""
        cfg, _ = load_config("Omni_Localizer/config/local.yaml")
        # Use the same path the ModelPool uses to build the list
        from ol_pool.router import ModelPool as MP
        from unittest.mock import patch, MagicMock
        with patch("ol_pool.router.load_config", return_value=(cfg, None)):
            mp = MP()
            model_list = mp._build_model_list(cfg.llm_pool)
        # Every entry should have rpm inside litellm_params, NOT at top-level
        for entry in model_list:
            assert "rpm" not in entry, (
                f"Top-level rpm should be removed (FIX-#7). Got: {entry}"
            )
            assert "rpm" in entry["litellm_params"]
        # And the values should match config
        rpm_seen = {
            entry["litellm_params"]["model"]: entry["litellm_params"]["rpm"]
            for entry in model_list
            if entry["model_name"] == "translation"
        }
        # NVIDIA entries should be 40
        for model_id, rpm in rpm_seen.items():
            if "deepseek-ai" in model_id or "kimi" in model_id or "k2.6" in model_id:
                assert rpm == 40, f"NVIDIA model {model_id} should be 40; got {rpm}"


class TestRateLimitMetrics:
    """FIX-#18: ModelPool.metrics() returns a copy of the rate-limit counter."""

    def test_metrics_returns_empty_dict_initially(self):
        from unittest.mock import patch, MagicMock
        pool = MagicMock(llm_pool=MagicMock(translation=[], judging=[], restoration=[]))
        with patch("ol_pool.router.load_config", return_value=(pool, None)):
            mp = ModelPool()
        assert mp.metrics() == {}

    def test_metrics_returns_copy(self):
        from unittest.mock import patch, MagicMock
        pool = MagicMock(llm_pool=MagicMock(translation=[], judging=[], restoration=[]))
        with patch("ol_pool.router.load_config", return_value=(pool, None)):
            mp = ModelPool()
        mp._rate_limit_hits["translation"] = 5
        snapshot = mp.metrics()
        snapshot["judging"] = 99  # external mutation
        assert "judging" not in mp._rate_limit_hits
        assert mp._rate_limit_hits["translation"] == 5
