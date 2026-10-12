"""E2E regression tests for round 5 fixes (2026-06-17).

Covers the YAML → Pydantic → ConcurrencyLimiter full chain for
`max_xliff_concurrent`, and verifies the per-model RPM + Router
enforcement wiring for `requests_per_minute`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the OL src/ importable
_OL_SRC = Path(__file__).resolve().parents[1] / "Omni_Localizer" / "src"
if str(_OL_SRC) not in sys.path:
    sys.path.insert(0, str(_OL_SRC))

from ol_config.loader import load_config
from ol_pool.router import ModelPool


_LOCAL_YAML_PATH = Path(__file__).resolve().parents[1] / "config" / "local.yaml"
_DEFAULT_YAML_PATH = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


@pytest.mark.skipif(
    not _LOCAL_YAML_PATH.exists(),
    reason="config/local.yaml is a gitignored local-only config; not present in CI",
)
class TestMaxXliffConcurrentE2E:
    """FIX-#13: max_xliff_concurrent flows from YAML to ConcurrencyLimiter.

    Scoped to `config/local.yaml` only. Assertions about the *tracked* pool
    live in `TestCanonicalPool` below, which runs in CI — they used to sit
    here under this class-level skipif, so a check reading the tracked
    `default.yaml` was silently skipped everywhere except a maintainer's
    machine.
    """

    def test_local_yaml_has_max_xliff_5(self):
        """local.yaml must set max_xliff_concurrent: 5 (round 3 fix)."""
        cfg, _ = load_config(str(_LOCAL_YAML_PATH))
        assert cfg.max_xliff_concurrent == 5, (
            f"Expected max_xliff_concurrent=5 in local.yaml; "
            f"got {cfg.max_xliff_concurrent}"
        )


class TestCanonicalPool:
    """Assertions about `config/default.yaml` — tracked, so these run in CI.

    Three tests that used to live under the local.yaml skipif were removed
    2026-10-12. They asserted that NVIDIA carried `rpm=40` and that
    OPENCODE_GO carried a low rpm, against the canonical `translation` /
    `judging` pools. Both providers are gone: NVIDIA NIM returned HTTP 410
    (recorded in CHANGELOG), and OPENCODE_GO no longer appears anywhere in
    the product. They could only ever fail, and only on a machine that has a
    `config/local.yaml`.

    Nothing real was lost with them: the mechanism they policed — rpm acting
    as *hard* 429 enforcement — was deliberately removed in E2E-83, which
    dropped `enforce_model_rate_limits` from the Router. `rpm` is now a
    routing weight only. `test_modelpool_rpm_per_deployment` below still
    locks the surviving half of the FIX-#7 contract.
    """

    def test_default_yaml_has_max_xliff_5(self):
        """default.yaml must set max_xliff_concurrent: 5 (round 3 fix).

        This test was named for default.yaml but loaded _LOCAL_YAML_PATH;
        it now actually reads the tracked file. No OL_ALLOW_HARDCODED_KEYS
        dance is needed: `load_config` only warns on unset ${VAR}
        (`schema.py:_check_env_vars`), and resolution failure is raised
        later, per-model, when a model is actually invoked.
        """
        cfg, _ = load_config(str(_DEFAULT_YAML_PATH))
        assert cfg.max_xliff_concurrent == 5, (
            f"Expected max_xliff_concurrent=5 in default.yaml; "
            f"got {cfg.max_xliff_concurrent}"
        )

    def test_modelpool_rpm_per_deployment(self):
        """FIX-#7: per-deployment rpm in litellm_params (canonical location).

        Provider-agnostic: it asserts the wiring (rpm lands in
        litellm_params, never top-level, and mirrors the config value), not
        any particular provider's quota. The previous form keyed off NVIDIA
        model ids (`deepseek-ai` / `kimi` / `k2.6`) and is therefore
        provider-agnostic only by accident of the rename.
        """
        cfg, _ = load_config(str(_DEFAULT_YAML_PATH))
        from unittest.mock import patch

        with patch("ol_pool.router.load_config", return_value=(cfg, None)):
            mp = ModelPool()
            model_list = mp._build_model_list(cfg.llm_pool)

        assert model_list, "canonical pool produced no deployments"
        for entry in model_list:
            assert "rpm" not in entry, (
                f"Top-level rpm should be removed (FIX-#7). Got: {entry}"
            )
            assert "rpm" in entry["litellm_params"], (
                f"rpm must live in litellm_params for {entry.get('model_name')}"
            )

        # The old NVIDIA block keyed off provider model ids; this is the same
        # invariant generalised to whatever the canonical pool actually holds.
        configured = {
            f"{m.provider}/{m.model}": m.requests_per_minute
            for role in ("translation", "judging", "restoration", "profiling")
            for m in getattr(cfg.llm_pool, role, [])
        }
        for entry in model_list:
            model_id = entry["litellm_params"]["model"]
            assert entry["litellm_params"]["rpm"] == configured[model_id], (
                f"{model_id}: litellm rpm {entry['litellm_params']['rpm']} "
                f"!= configured {configured[model_id]}"
            )


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
