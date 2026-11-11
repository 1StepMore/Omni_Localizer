"""OL#184: backup tier must take over on hard failures, not only on 429.

Two disjoint failover paths:

* HTTP 429 — handled by OL's own ``_intra_role_failover``, which steps through
  the role's models by priority with direct ``litellm.acompletion`` calls.
* Hard failures (connection refused / timeout / 5xx) — the real re-pick happens
  inside litellm. Without ``enable_weighted_failover`` the group-level retry can
  draw the same broken deployment again, so the backup tier never gets a turn.
  Enabling it makes a retryable failure re-pick (weighted) across the same model
  group (one role == one group here) before cross-role fallback.

The actual re-pick lives in litellm, so the contract this repo can defend is
that the flag reaches the Router together with the strategy it depends on.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ol_config.schema import LLMModelConfig, LLMModelRole, LLMPoolConfig
from ol_pool.router import ModelPool


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
def router_spy(monkeypatch):
    """Record the kwargs ModelPool hands to litellm's Router."""
    monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
    config = _pool_config()
    with patch("ol_pool.router.load_config") as load_config, \
            patch("ol_pool.router.Router") as router_cls:
        # A non-subscriptable result makes ModelPool treat it as the whole
        # config object instead of taking result[0].
        load_config.return_value = SimpleNamespace(llm_pool=config)
        ModelPool()
        yield router_cls


def test_weighted_failover_is_passed_to_router(router_spy):
    assert router_spy.call_count == 1, "ModelPool must build exactly one Router"
    kwargs = router_spy.call_args.kwargs

    assert kwargs["enable_weighted_failover"] is True, (
        "hard failures (timeout / connection / 5xx) only re-pick within the "
        "group when enable_weighted_failover is on (OL#184)"
    )
    assert kwargs["routing_strategy"] == "simple-shuffle", (
        "enable_weighted_failover only takes effect under simple-shuffle; the "
        "two settings must stay paired"
    )


def test_every_role_still_registers_two_tiers(router_spy):
    model_list = router_spy.call_args.kwargs["model_list"]
    by_role: dict[str, list[dict]] = {}
    for entry in model_list:
        by_role.setdefault(entry["model_name"], []).append(entry)

    for role in ("translation", "judging", "restoration"):
        assert len(by_role.get(role, [])) == 2, (
            f"role {role!r} must keep both priority tiers; got "
            f"{by_role.get(role, [])}"
        )

    translation_deps = [
        entry["litellm_params"]["model"] for entry in by_role["translation"]
    ]
    assert translation_deps == [
        "amd/deepseek-v4.1-flash",
        "zhipu/glm-4.7-flash",
    ], "translation tiers must stay in priority order"
