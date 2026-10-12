"""Regression: `max_parallel_requests` reaches litellm_params.

`requests_per_minute` is a routing weight only — E2E-83 removed
`enforce_model_rate_limits` from the Router, so nothing rejects a request
locally on rpm any more. Both providers in the canonical pool are capped by
CONCURRENT requests instead: AMD Radeon answers 429
`model_concurrency_rate_limit_exceeded` naming a concurrency number, Zhipu
answers `code 1305 该模型当前访问量过大`.

`max_parallel_requests` is the knob for that shape of limit. It lands in the
same `litellm_params` dict as rpm (both are `updateLiteLLMParams` fields),
and litellm enforces it with a per-deployment semaphore — no Router flag
required.

These tests lock the wiring and the opt-in contract: unset must mean "no
client-side cap", not "cap of 0".
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_OL_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_OL_SRC) not in sys.path:
    sys.path.insert(0, str(_OL_SRC))

from ol_config.loader import load_config
from ol_config.schema import LLMModelConfig
from ol_pool.router import ModelPool

_DEFAULT_YAML = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


def _build(pool):
    with patch("ol_pool.router.load_config", return_value=(pool, None)):
        return ModelPool()._build_model_list(pool)


class TestMaxParallelRequestsWiring:
    def test_absent_by_default_so_existing_configs_get_no_cap(self):
        model_list = _build(load_config(str(_DEFAULT_YAML))[0].llm_pool)

        assert model_list, "canonical pool produced no deployments"
        for entry in model_list:
            assert "max_parallel_requests" not in entry["litellm_params"], (
                f"{entry['litellm_params']['model']}: the key must be omitted "
                f"when unset, not emitted with a default — an absent cap and a "
                f"cap of 0 are different things"
            )

    def test_declared_value_reaches_only_that_deployment(self):
        pool = load_config(str(_DEFAULT_YAML))[0].llm_pool
        pool.translation[0].max_parallel_requests = 4
        # litellm_params['model'] is the provider-qualified form.
        target = f"{pool.translation[0].provider}/{pool.translation[0].model}"

        model_list = _build(pool)
        capped = [
            e for e in model_list
            if "max_parallel_requests" in e["litellm_params"]
        ]

        assert len(capped) == 1, (
            f"expected exactly 1 capped deployment, got {len(capped)}"
        )
        assert capped[0]["litellm_params"]["max_parallel_requests"] == 4
        assert capped[0]["litellm_params"]["model"] == target
        assert capped[0]["model_name"] == "translation"

    def test_sits_next_to_rpm_in_the_same_dict(self):
        """rpm and max_parallel_requests are both updateLiteLLMParams fields."""
        pool = load_config(str(_DEFAULT_YAML))[0].llm_pool
        pool.translation[0].max_parallel_requests = 4

        entry = _build(pool)[0]
        lp = entry["litellm_params"]

        assert "rpm" in lp, "rpm must remain present (FIX-#7)"
        assert lp["max_parallel_requests"] == 4
        assert "max_parallel_requests" not in entry, (
            "must not be duplicated at the deployment top level"
        )


class TestMaxParallelRequestsSchema:
    @pytest.mark.parametrize("value", [1, 2, 4, 64])
    def test_accepts_positive(self, value):
        model = LLMModelConfig(
            provider="openai", model="m", api_key="k", role="translation",
            max_parallel_requests=value,
        )
        assert model.max_parallel_requests == value

    def test_defaults_to_none(self):
        model = LLMModelConfig(
            provider="openai", model="m", api_key="k", role="translation",
        )
        assert model.max_parallel_requests is None

    @pytest.mark.parametrize("value", [0, -1])
    def test_rejects_non_positive(self, value):
        with pytest.raises(Exception):
            LLMModelConfig(
                provider="openai", model="m", api_key="k", role="translation",
                max_parallel_requests=value,
            )