"""Tests for `ol init` — the config bootstrap wizard (OL#92).

Contract (scenarios 1-4):
1. `ol init --non-interactive --force --config <tmp>/local.yaml` writes a
   valid config; `load_config(<tmp>/local.yaml)` succeeds (exit 0).
2. Overwrite WITHOUT --force is refused with ExitCode.PIPELINE_ERROR (exit 1).
3. `init` appears in `ol --help` output.
4. Generated YAML contains ONLY ${ENV_VAR} refs for api_key/base_url — no
   literal keys (e.g. "glm-4-flash" absent, "${ZHIPU_API_KEY}" present).
"""
from __future__ import annotations

import yaml
from typer.testing import CliRunner

from cli._shared import ExitCode
from ol_cli import app

runner = CliRunner()

ENV = {"OMNI_TEST_FAKE_LLM": "1"}


def test_init_writes_valid_config(tmp_path):
    """Scenario 1: --non-interactive --force writes a loadable config."""
    cfg = tmp_path / "local.yaml"
    result = runner.invoke(
        app,
        ["init", "--non-interactive", "--force", "--config", str(cfg)],
        env=ENV,
    )
    assert result.exit_code == 0, (
        f"exit={result.exit_code}, out={result.output!r}, exc={result.exception!r}"
    )
    assert cfg.exists(), f"config not written to {cfg}"

    from ol_config.loader import load_config

    config, _ = load_config(str(cfg))
    assert len(config.llm_pool.translation) >= 2
    assert len(config.llm_pool.judging) >= 2
    assert len(config.llm_pool.restoration) >= 2


def test_init_refuses_overwrite_without_force(tmp_path):
    """Scenario 2: existing config without --force -> PIPELINE_ERROR (exit 1)."""
    cfg = tmp_path / "local.yaml"
    original = "project_id: existing\n"
    cfg.write_text(original, encoding="utf-8")

    result = runner.invoke(
        app,
        ["init", "--non-interactive", "--config", str(cfg)],
        env=ENV,
    )
    assert result.exit_code == ExitCode.PIPELINE_ERROR
    # File must be untouched.
    assert cfg.read_text(encoding="utf-8") == original


def test_init_in_help():
    """Scenario 3: `init` is registered and shows in `ol --help`."""
    result = runner.invoke(app, ["--help"], env=ENV)
    assert result.exit_code == 0
    assert "init" in result.output


def test_init_yaml_has_only_env_refs(tmp_path):
    """Scenario 4: generated YAML uses ${ENV_VAR} refs, never literal keys."""
    cfg = tmp_path / "local.yaml"
    result = runner.invoke(
        app,
        ["init", "--non-interactive", "--force", "--config", str(cfg)],
        env=ENV,
    )
    assert result.exit_code == 0, (
        f"exit={result.exit_code}, out={result.output!r}, exc={result.exception!r}"
    )

    text = cfg.read_text(encoding="utf-8")
    # No literal old keys / providers.
    assert "glm-4-flash" not in text
    assert "agnes" not in text.lower()
    assert "deepseek-v4-flash" not in text
    # ${ENV_VAR} refs present.
    assert "${ZHIPU_API_KEY}" in text
    assert "${NVIDIA_NIM_API_KEY}" in text
    assert "${OPENCODE_GO_KEY}" in text
    assert "${OPENCODE_GO_BASE_URL}" in text

    # Every api_key is a ${ENV_VAR} ref (never a literal).
    data = yaml.safe_load(text)
    for role, models in data["llm_pool"].items():
        assert models, f"role {role} has no models"
        for m in models:
            assert m["api_key"].startswith("${") and m["api_key"].endswith("}"), (
                f"{role}/{m['model']} api_key is not an env ref: {m['api_key']!r}"
            )
