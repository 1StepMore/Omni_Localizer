"""OL#99: one unset provider key must not disable the whole model pool.

`_build_model_list` resolved every model's `${VAR}` inside `__init__`, so a
missing priority-1 key raised `ModelPoolInitError` and took every role down
with it -- even when the priority-2/3 keys were present and sufficient. That
contradicted the documented two-layer env contract in README/AGENTS.md
(`schema._check_env_vars` WARNs at startup; a model is only unusable once
actually selected).

The env-var name here is deliberately unique: OL calls `load_dotenv()` at
import, which repopulates the canonical ARK/ZHIPU/NVIDIA keys from `.env`, so
a test that popped those would silently exercise the wrong path.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from ol_config.schema import LLMModelConfig, LLMModelRole, LLMPoolConfig
from ol_pool.router import ModelPool, ModelPoolInitError

_ABSENT = "OL99_DEFINITELY_UNSET_KEY"
_TRANSLATION = LLMModelRole.TRANSLATION
_JUDGING = LLMModelRole.JUDGING
_RESTORATION = LLMModelRole.RESTORATION


def _model(name: str, role: LLMModelRole, priority: int, api_key: str | None) -> LLMModelConfig:
    return LLMModelConfig(
        provider="openai", model=name, priority=priority, role=role, api_key=api_key,
    )


def _working(role: LLMModelRole) -> list[LLMModelConfig]:
    """Two credential-free models: LLMPoolConfig requires >= 2 per role."""
    return [
        _model(f"{role.value}-primary", role, 1, None),
        _model(f"{role.value}-backup", role, 2, None),
    ]


def _absent(role: LLMModelRole, priority: int, suffix: str = "") -> LLMModelConfig:
    return _model(f"absent{suffix}", role, priority, f"${{{_ABSENT}}}")


@pytest.fixture(autouse=True)
def _real_llm_path(monkeypatch):
    """Force the non-fake __init__ branch and clear the probe var."""
    monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
    monkeypatch.delenv(_ABSENT, raising=False)


def _build(pool: LLMPoolConfig) -> ModelPool:
    # conftest stubs litellm's Router with a bare class, and ol_pool.router
    # falls back to ``Router = None`` when that import fails -- so the Router
    # must be mocked here, as test_model_pool_failover.py does.
    with patch("ol_pool.router.load_config", return_value=(MagicMock(llm_pool=pool), None)), \
            patch("ol_pool.router.Router", MagicMock()):
        return ModelPool("config/default.yaml")


class TestPoolSurvivesPartialCredentials:
    def test_missing_key_skips_only_that_model(self):
        pool = LLMPoolConfig(
            translation=[_absent(_TRANSLATION, 1), *_working(_TRANSLATION)],
            judging=_working(_JUDGING),
            restoration=_working(_RESTORATION),
        )
        built = _build(pool)
        model_list = built._build_model_list(pool, usable=built._usable_by_role)
        names = [entry["litellm_params"]["model"] for entry in model_list]
        assert "openai/absent" not in names
        assert len(names) == 6

    def test_skipped_model_is_absent_from_fallbacks_too(self):
        pool = LLMPoolConfig(
            translation=[
                _absent(_TRANSLATION, 1),
                _working(_TRANSLATION)[0],
                _model("third-provider", _TRANSLATION, 3, None),
            ],
            judging=_working(_JUDGING),
            restoration=_working(_RESTORATION),
        )
        built = _build(pool)
        fallbacks = built._build_fallbacks(pool, usable=built._usable_by_role)
        flat = [mid for entry in fallbacks for mids in entry.values() for mid in mids]
        assert "openai/absent" not in flat
        assert "openai/third-provider" in flat

    def test_warns_once_per_skipped_model(self, caplog):
        pool = LLMPoolConfig(
            translation=[_absent(_TRANSLATION, 1), *_working(_TRANSLATION)],
            judging=_working(_JUDGING),
            restoration=_working(_RESTORATION),
        )
        with caplog.at_level(logging.WARNING, logger="ol.pool"):
            _build(pool)
        warnings = [r.message for r in caplog.records if "absent" in r.message]
        assert len(warnings) == 1
        assert _ABSENT in warnings[0]

    def test_each_role_keeps_its_working_models(self):
        pool = LLMPoolConfig(
            translation=[_absent(_TRANSLATION, 1), *_working(_TRANSLATION)],
            judging=[_absent(_JUDGING, 1), *_working(_JUDGING)],
            restoration=[_absent(_RESTORATION, 1), *_working(_RESTORATION)],
        )
        built = _build(pool)
        for role in ("translation", "judging", "restoration"):
            assert [m.model for m in built._usable_by_role[role]] == [
                f"{role}-primary", f"{role}-backup",
            ]


class TestPoolStillFailsClosed:
    def test_role_with_no_usable_model_raises(self):
        pool = LLMPoolConfig(
            translation=[
                _absent(_TRANSLATION, 1),
                _absent(_TRANSLATION, 2, suffix="-2"),
            ],
            judging=_working(_JUDGING),
            restoration=_working(_RESTORATION),
        )
        with pytest.raises(ModelPoolInitError) as excinfo:
            _build(pool)
        message = str(excinfo.value)
        assert "translation" in message
        assert _ABSENT in message

    def test_unset_base_url_var_also_makes_model_unusable(self):
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(
                    provider="openai",
                    model="needs-base-url",
                    priority=1,
                    role=_TRANSLATION,
                    base_url=f"https://example.invalid/${{{_ABSENT}}}",
                ),
                *_working(_TRANSLATION),
            ],
            judging=_working(_JUDGING),
            restoration=_working(_RESTORATION),
        )
        built = _build(pool)
        assert [m.model for m in built._usable_by_role["translation"]] == [
            "translation-primary", "translation-backup",
        ]
