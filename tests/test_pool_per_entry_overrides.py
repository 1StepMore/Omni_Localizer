"""Regression: per-entry `max_tokens` and `extra_body` reach litellm_params.

Both knobs are opt-in per pool entry. Reasoning providers (iFlytek Spark
`spark-x2.6`) spend the token budget on hidden thinking, so a single entry
may need a larger `max_tokens` and a provider-specific body that disables
thinking. LiteLLM only forwards provider-specific body parameters through
`extra_body`; `additional_body` is silently dropped.

Unset must mean "the key is absent", not "emitted with a default", so every
existing config keeps producing the same litellm_params as before.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

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


class TestPerEntryOverridesWiring:
    def test_absent_unless_declared(self):
        model_list = _build(load_config(str(_DEFAULT_YAML))[0].llm_pool)

        assert model_list, "canonical pool produced no deployments"
        for entry in model_list:
            lp = entry["litellm_params"]
            assert "max_tokens" not in lp, (
                f"{lp['model']}: unset max_tokens must not be emitted"
            )
            assert "extra_body" not in lp, (
                f"{lp['model']}: unset extra_body must not be emitted"
            )

    def test_declared_values_reach_only_that_deployment(self):
        pool = load_config(str(_DEFAULT_YAML))[0].llm_pool
        first = pool.translation[0]
        extra_body = {"thinking": {"type": "disabled"}}
        first.max_tokens = 8192
        first.extra_body = extra_body
        target = f"{first.provider}/{first.model}"

        model_list = _build(pool)
        matched = [
            e for e in model_list
            if e["model_name"] == "translation"
            and e["litellm_params"]["model"] == target
        ]

        assert len(matched) == 1
        lp = matched[0]["litellm_params"]
        assert lp["max_tokens"] == 8192
        assert lp["extra_body"] == extra_body
        assert "extra_body" not in matched[0], (
            "must not be duplicated at the deployment top level"
        )

        # Other deployments of the SAME role opt into an explicit ceiling too:
        # the call site stops pinning max_tokens, so every sibling must carry
        # the role default (translation = 4096) instead of falling back to the
        # provider default.
        same_role_siblings = [
            e for e in model_list
            if e["model_name"] == "translation"
            and e["litellm_params"]["model"] != target
        ]
        assert same_role_siblings, "expected a fallback deployment in the role"
        for entry in same_role_siblings:
            assert entry["litellm_params"]["max_tokens"] == 4096
            assert "extra_body" not in entry["litellm_params"]

        # Other roles did not opt in: their litellm_params stay untouched.
        other_roles = [
            e for e in model_list if e["model_name"] != "translation"
        ]
        for entry in other_roles:
            assert "max_tokens" not in entry["litellm_params"]
            assert "extra_body" not in entry["litellm_params"]

    def test_router_call_kwargs_defer_to_deployments_when_role_overrides(self):
        pool = load_config(str(_DEFAULT_YAML))[0].llm_pool
        bare = ModelPool.__new__(ModelPool)
        bare._usable_by_role = {
            "translation": list(pool.translation),
            "judging": list(pool.judging),
        }
        assert bare._router_max_tokens_kwargs("translation") == {
            "max_tokens": 4096,
        }
        assert bare._router_max_tokens_kwargs("judging") == {
            "max_tokens": 2048,
        }

        pool.translation[0].max_tokens = 8192
        bare._usable_by_role["translation"] = list(pool.translation)
        assert bare._router_max_tokens_kwargs("translation") == {}

    def test_router_call_kwargs_omitted_for_judging_override(self):
        bare = ModelPool.__new__(ModelPool)
        model = LLMModelConfig(
            provider="openai",
            model="judge-x",
            api_key="${SPARK_API_KEY}",
            role="judging",
            max_tokens=8192,
        )
        bare._usable_by_role = {"judging": [model]}
        assert bare._router_max_tokens_kwargs("judging") == {}

    def test_pydantic_model_accepts_reasoning_entry(self):
        model = LLMModelConfig(
            provider="openai",
            model="spark-x2.6",
            api_key="${SPARK_API_KEY}",
            base_url="https://maas-api.cn-huabei-1.xf-yun.com/v2",
            role="translation",
            max_tokens=8192,
            extra_body={"thinking": {"type": "disabled"}},
        )
        assert model.max_tokens == 8192
        assert model.extra_body == {"thinking": {"type": "disabled"}}
