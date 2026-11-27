"""Regression lock: the generic OpenAI-compatible endpoint triple.

suite#448 / OL#227 — the shipped pool (``config/default.yaml`` and the
pipeline-pinned ``config/test_universal.yaml``) carries a lowest-priority
generic entry per role::

    model: ${LLM_MODEL}
    api_key: ${LLM_API_KEY}
    base_url: ${LLM_BASE_URL}

so a user can reuse ANY OpenAI-compatible endpoint (company gateway, local
Ollama, third-party compatible host) without buying a provider key. Three
behaviors must hold, or the path is either dead or dishonest:

1. An unresolved model-name ref must skip an entry exactly like an
   unresolved key ref — a literal ``${LLM_MODEL}`` must never reach
   litellm as a model id (router + doctor scan the model field).
2. With all three vars set, the generic entry becomes usable and the
   litellm model id carries the RESOLVED model name.
3. The entry stays skipped while ANY of the three vars is unset (partial
   triple = misconfiguration, not a fallback), and the CLI pre-check names
   the triple among the vars a config needs.

No network, no litellm calls (conftest stubs litellm under FAKE_LLM);
the pre-check case reads a tmp config file. Deterministic.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import typer
import yaml

from ol_config.schema import LLMPoolConfig, LLMModelConfig

TRIPLE = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


def _clear_triple(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in TRIPLE:
        monkeypatch.delenv(var, raising=False)


def _model(**overrides) -> LLMModelConfig:
    fields = {
        "provider": "openai",
        "model": "${LLM_MODEL}",
        "priority": 3,
        "api_key": "${LLM_API_KEY}",
        "base_url": "${LLM_BASE_URL}",
        "role": "translation",
        "timeout": 120.0,
    }
    fields.update(overrides)
    return LLMModelConfig(**fields)


# ---------------------------------------------------------------------------
# 1. The model field is scanned for ${VAR} refs
# ---------------------------------------------------------------------------


class TestUnresolvedEnvVarsScansModelField:
    def test_unset_model_ref_is_flagged(self, monkeypatch):
        from ol_pool.router import _unresolved_env_vars

        _clear_triple(monkeypatch)
        missing = _unresolved_env_vars(_model())
        assert set(TRIPLE) <= set(missing), missing

    def test_empty_model_ref_is_flagged(self, monkeypatch):
        """OL#195 semantics: "" is as unusable as unset."""
        from ol_pool.router import _unresolved_env_vars

        monkeypatch.setenv("LLM_MODEL", "")
        missing = _unresolved_env_vars(_model())
        assert "LLM_MODEL" in missing

    def test_literal_model_name_has_no_refs(self, monkeypatch):
        from ol_pool.router import _unresolved_env_vars

        _clear_triple(monkeypatch)
        monkeypatch.delenv("ZHIPU_API_KEY", raising=False)  # conftest dummy
        entry = _model(model="glm-4-flash", api_key="${ZHIPU_API_KEY}", base_url=None)
        assert _unresolved_env_vars(entry) == ["ZHIPU_API_KEY"]

    def test_doctor_unresolved_refs_includes_model_field(self, monkeypatch):
        from cli.doctor import _unresolved_refs

        _clear_triple(monkeypatch)
        missing = _unresolved_refs(_model())
        assert set(TRIPLE) <= set(missing), missing


# ---------------------------------------------------------------------------
# 2. Partition + litellm model id
# ---------------------------------------------------------------------------


class TestPartitionAndModelId:
    def _pool(self) -> LLMPoolConfig:
        """All four roles × (primary + backup + generic triple).

        LLMPoolConfig enforces >=2 models per role (primary + backup), so a
        one-role fixture cannot even construct.
        """
        buckets: dict[str, list[LLMModelConfig]] = {}
        for role in ("translation", "judging", "restoration", "profiling"):
            buckets[role] = [
                _model(
                    model="glm-4-flash",
                    api_key="${ZHIPU_API_KEY}",
                    base_url="https://open.bigmodel.cn/api/paas/v4",
                    priority=1,
                    role=role,
                ),
                _model(
                    model="glm-4.7-flash",
                    api_key="${ZHIPU_API_KEY}",
                    base_url="https://open.bigmodel.cn/api/paas/v4",
                    priority=2,
                    role=role,
                ),
                _model(priority=3, role=role),
            ]
        return LLMPoolConfig(**buckets)

    def test_generic_entry_skipped_while_any_var_unset(self, monkeypatch):
        """All-three semantics: partial triple never becomes usable."""
        from ol_pool.router import partition_usable_models

        _clear_triple(monkeypatch)
        for var in TRIPLE[:2]:  # base_url + key set, LLM_MODEL missing
            monkeypatch.setenv(var, "stub")
        usable, skipped = partition_usable_models(self._pool())
        ids = [m.model for m in usable["translation"]]
        assert "${LLM_MODEL}" not in ids and "stub" not in ids, ids
        missing_sets = [set(missing) for _, _, missing in skipped]
        assert {"LLM_MODEL"} in missing_sets, skipped

    def test_generic_entry_usable_and_resolved_when_all_set(self, monkeypatch):
        from ol_pool.router import partition_usable_models

        _clear_triple(monkeypatch)
        monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8899/v1")
        monkeypatch.setenv("LLM_API_KEY", "sk-endpoint")
        monkeypatch.setenv("LLM_MODEL", "qwen3")
        monkeypatch.setenv("ZHIPU_API_KEY", "sk-regression")
        usable, skipped = partition_usable_models(self._pool())
        assert not skipped, skipped
        # partition returns the RAW config objects — the ${LLM_MODEL} literal
        # stays in .model here; resolution happens at the litellm call site
        # (proven by test_build_model_list_emits_resolved_model_id).
        models = {m.model for m in usable["translation"]}
        assert "${LLM_MODEL}" in models and "glm-4-flash" in models, models

    def test_build_model_list_emits_resolved_model_id(self, monkeypatch):
        from ol_pool.router import ModelPool

        _clear_triple(monkeypatch)
        monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8899/v1")
        monkeypatch.setenv("LLM_API_KEY", "sk-endpoint")
        monkeypatch.setenv("LLM_MODEL", "qwen3")
        monkeypatch.delenv("ZHIPU_API_KEY", raising=False)  # conftest dummy
        # ZHIPU unset: only the generic entry is usable, in every role.
        model_list = ModelPool()._build_model_list(self._pool())
        translation_ids = {
            d["litellm_params"]["model"] for d in model_list
        }
        assert translation_ids == {"openai/qwen3"}, translation_ids


# ---------------------------------------------------------------------------
# 3. The pre-check names the triple among a config's required vars
# ---------------------------------------------------------------------------

_POOL_YAML = """
llm_pool:
  translation:
  - provider: openai
    model: ${LLM_MODEL}
    api_key: ${LLM_API_KEY}
    base_url: ${LLM_BASE_URL}
    timeout: 120.0
    priority: 3
    role: translation
"""


class TestPrecheckNamesTriple:
    def _write_config(self, tmp_path: Path) -> Path:
        cfg = tmp_path / "config.yaml"
        _ = yaml.safe_load(_POOL_YAML)  # sanity: the fixture parses
        cfg.write_text(_POOL_YAML, encoding="utf-8")
        return cfg

    def test_zero_config_names_the_triple(self, monkeypatch, tmp_path, capsys):
        """No vars at all: the error lists the triple as what is needed."""
        from cli._shared import precheck_api_keys

        _clear_triple(monkeypatch)
        # Conftest installs both a dummy provider key and FAKE_LLM=1; the
        # pre-check must run on its real path here.
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
        monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
        with pytest.raises(typer.Exit):
            precheck_api_keys(str(self._write_config(tmp_path)))
        captured = capsys.readouterr()
        for var in TRIPLE:
            assert var in captured.err, captured.err


# ---------------------------------------------------------------------------
# 4. The shipped configs and the init preset all carry the triple
# ---------------------------------------------------------------------------


class TestShippedSurfacesCarryTriple:
    @pytest.mark.parametrize("cfg_name", ["default.yaml", "test_universal.yaml"])
    def test_config_roles_carry_generic_entry(self, cfg_name):
        cfg = Path(__file__).resolve().parents[1] / "config" / cfg_name
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        roles = data["llm_pool"]
        # default.yaml has 4 roles; test_universal.yaml pins 3 — every role
        # that IS present must carry the triple.
        assert roles, f"{cfg_name}: empty pool"
        for role, entries in roles.items():
            triples = [
                e for e in entries
                if e.get("model") == "${LLM_MODEL}"
                and e.get("api_key") == "${LLM_API_KEY}"
                and e.get("base_url") == "${LLM_BASE_URL}"
            ]
            assert triples, f"{cfg_name}:{role}: no generic endpoint entry"
            assert triples[0]["provider"] == "openai"
            # Lowest priority: strictly after every provider entry.
            provider_priorities = [
                e["priority"] for e in entries if e not in triples
            ]
            assert triples[0]["priority"] > max(provider_priorities), (
                f"{cfg_name}:{role}: generic entry must be the lowest tier"
            )

    def test_init_preset_mirrors_triple(self):
        from cli.init import UNIFIED_POOL_PRESET

        for role, entries in UNIFIED_POOL_PRESET.items():
            triples = [
                e for e in entries
                if e["model"] == "${LLM_MODEL}"
                and e["api_key"] == "${LLM_API_KEY}"
                and e["base_url"] == "${LLM_BASE_URL}"
            ]
            assert triples, f"init preset {role}: no generic endpoint entry"
            assert triples[0]["priority"] == len(entries), (
                f"init preset {role}: triple must be the last tier"
            )

    def test_shipped_default_pool_is_untouched_when_triple_unset(self, monkeypatch):
        """The default pool's provider entries keep working with no LLM_* set."""
        from ol_pool.router import partition_usable_models

        _clear_triple(monkeypatch)
        monkeypatch.setenv("ZHIPU_API_KEY", "sk-regression")
        cfg = (
            Path(__file__).resolve().parents[1] / "config" / "default.yaml"
        ).read_text(encoding="utf-8")
        import yaml as _yaml

        pool = LLMPoolConfig(**_yaml.safe_load(cfg)["llm_pool"])
        usable, skipped = partition_usable_models(pool)
        # Skipped = exactly the generic entries (LLM_* unset); every provider
        # entry stays usable and no role is starved.
        assert skipped and all(
            set(missing) == {"LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"}
            for _, _, missing in skipped
        ), skipped
        for role in ("translation", "judging", "restoration", "profiling"):
            assert usable[role], f"{role}: starved"
            assert all(m.model != "${LLM_MODEL}" for m in usable[role])
