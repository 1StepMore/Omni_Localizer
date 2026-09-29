"""Direct tests for ``cli._shared.precheck_api_keys`` (BYOK OR-semantics).

The rest of the suite runs with ``OMNI_TEST_FAKE_LLM=1`` plus conftest's
dummy provider keys, so ``precheck_api_keys`` early-returns almost
everywhere and had no direct coverage. These tests unset the seam and
every ambient ``*_API_KEY`` so each branch is exercised deterministically.

A focused module is used (rather than extending ``test_cli_doctor.py``)
because this targets ``_shared``'s fast-fail gate, not the doctor
checklist, and it must run with ``OMNI_TEST_FAKE_LLM`` unset — the
opposite of the rest of the CLI test files.
"""
from __future__ import annotations

import os

import pytest
import typer

from cli._shared import ExitCode, precheck_api_keys

# Minimal pool whose only ${VAR} refs are the two provider keys.
POOL_YAML = """\
project_id: test
llm_pool:
  translation:
    - provider: openai
      model: DeepSeek-V4.1-Flash
      priority: 1
      role: translation
      api_key: "${AMD_API_KEY}"
      base_url: "https://developer.amd.com.cn/radeon/api/v1"
    - provider: openai
      model: glm-4.7-flash
      priority: 2
      role: translation
      api_key: "${ZHIPU_API_KEY}"
      base_url: "https://open.bigmodel.cn/api/paas/v4"
"""

# Valid pool with no ${VAR} interpolation at all.
NO_ENV_REF_YAML = """\
project_id: test
llm_pool:
  translation:
    - provider: openai
      model: local
      priority: 1
      role: translation
      api_key: "literal-not-a-secret"
      base_url: "http://localhost:8080/v1"
"""


def _isolate_env(monkeypatch):
    """Drop the FAKE_LLM/RUN_REAL_LLM seams and every ambient *_API_KEY."""
    for name in ("OMNI_TEST_FAKE_LLM", "OMNI_RUN_REAL_LLM"):
        monkeypatch.delenv(name, raising=False)
    for name in list(os.environ):
        if name.endswith("_API_KEY"):
            monkeypatch.delenv(name, raising=False)


def _write_config(tmp_path, text):
    cfg = tmp_path / "pool.yaml"
    cfg.write_text(text, encoding="utf-8")
    return cfg


def test_zero_keys_raises(tmp_path, monkeypatch, capsys):
    """No provider key at all → fail closed with the 'nothing configured' message."""
    _isolate_env(monkeypatch)
    cfg = _write_config(tmp_path, POOL_YAML)

    with pytest.raises(typer.Exit) as exc:
        precheck_api_keys(str(cfg))

    assert exc.value.exit_code == ExitCode.PIPELINE_ERROR
    err = capsys.readouterr().err
    assert "no provider API key is configured" in err
    assert "AMD_API_KEY" in err
    assert "ZHIPU_API_KEY" in err
    assert "SETUP.md" in err
    assert "OMNI_TEST_FAKE_LLM=1" in err


def test_single_pool_key_proceeds(tmp_path, monkeypatch):
    """Exactly one pool key is enough to proceed (BYOK)."""
    _isolate_env(monkeypatch)
    monkeypatch.setenv("AMD_API_KEY", "sk-real")

    assert precheck_api_keys(str(_write_config(tmp_path, POOL_YAML))) is None


def test_non_pool_key_reports_mismatch(tmp_path, monkeypatch, capsys):
    """Configured-but-mismatched keys name both sides, not 'nothing configured'."""
    _isolate_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    cfg = _write_config(tmp_path, POOL_YAML)

    with pytest.raises(typer.Exit) as exc:
        precheck_api_keys(str(cfg))

    assert exc.value.exit_code == ExitCode.PIPELINE_ERROR
    err = capsys.readouterr().err
    assert "do not match this model pool" in err
    assert "OPENAI_API_KEY" in err
    assert "AMD_API_KEY" in err
    assert "no provider API key is configured" not in err


def test_empty_string_key_counts_absent(tmp_path, monkeypatch):
    """A var present but set to "" is treated as unset."""
    _isolate_env(monkeypatch)
    monkeypatch.setenv("AMD_API_KEY", "")
    cfg = _write_config(tmp_path, POOL_YAML)

    with pytest.raises(typer.Exit):
        precheck_api_keys(str(cfg))


def test_missing_config_returns(tmp_path, monkeypatch):
    """Unlocatable config → return and let the real load path report."""
    _isolate_env(monkeypatch)
    assert precheck_api_keys(str(tmp_path / "nope.yaml")) is None


def test_config_without_env_refs_returns(tmp_path, monkeypatch):
    """A config with no ${VAR} → nothing to precheck."""
    _isolate_env(monkeypatch)
    assert precheck_api_keys(str(_write_config(tmp_path, NO_ENV_REF_YAML))) is None


def test_run_real_llm_bypasses(tmp_path, monkeypatch, capsys):
    """OMNI_RUN_REAL_LLM=1 still bypasses the precheck."""
    _isolate_env(monkeypatch)
    monkeypatch.setenv("OMNI_RUN_REAL_LLM", "1")
    cfg = _write_config(tmp_path, POOL_YAML)

    assert precheck_api_keys(str(cfg)) is None
    assert capsys.readouterr().err == ""
