"""Regression tests for the shared CLI config-path resolver (e2e-test-suite#142).

Documented precedence, in order:

    1. explicit ``--config <path>``
    2. ``config/local.yaml`` in the current working directory (OPTIONAL)
    3. the ``OL_CONFIG_PATH`` environment variable
    4. ``config/default.yaml``

The defect this locks: ``ol init`` writes ``config/local.yaml``, but every CLI
command except ``ol doctor`` resolved
``config_path or os.environ.get("OL_CONFIG_PATH", "config/default.yaml")`` —
skipping level 2 entirely. Two consequences:

  * ``ol init`` was decorative — the file it generates was never read back.
  * The hint ``run 'ol init' to generate a valid config/local.yaml`` fired on
    ``Config file not found: config/default.yaml`` even when a perfectly good
    ``config/local.yaml`` sat in the cwd, i.e. a dead end.

Every cwd fixture below holds ONLY ``config/local.yaml`` (no
``config/default.yaml``), so a regression to level 4 fails the command
outright instead of silently loading the wrong file — the same shape as the
CI failure, where the workspace root has no ``config/`` directory at all.

Levels 2 and 4 are relative paths resolved against the process cwd by the OS;
this module does not assert anything about running from a foreign cwd.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from cli._shared import ExitCode
from ol_cli import app
from ol_config.resolver import (
    DEFAULT_CONFIG_RELPATH,
    LOCAL_CONFIG_RELPATH,
    resolve_config_path,
)

runner = CliRunner()

ENV = {"OMNI_TEST_FAKE_LLM": "1"}

# Two models per required role so ProjectConfig's min-models-per-role rule
# holds; literal non-secret keys so no ${VAR} is involved (a literal that
# matched a known key pattern would be rejected by loader's secret scan).
_MINIMAL_POOL: dict[str, list[dict[str, Any]]] = {
    role: [
        {
            "provider": "openai",
            "model": f"probe-{role}-primary",
            "priority": 1,
            "role": role,
            "api_key": "probe-key",
            "base_url": "https://example.invalid/v1",
        },
        {
            "provider": "openai",
            "model": f"probe-{role}-fallback",
            "priority": 2,
            "role": role,
            "api_key": "probe-key",
            "base_url": "https://example.invalid/v1",
        },
    ]
    for role in ("translation", "judging", "restoration")
}


def _probe_config(project_id: str = "ol-config-resolution-probe") -> dict[str, Any]:
    return {
        "project_id": project_id,
        "source_lang": "en",
        "target_lang": "zh",
        "glossary_path": None,
        "llm_pool": _MINIMAL_POOL,
        "enable_lqa": False,
        "max_md_concurrent": 1,
        "quality_gates": {
            "inline_tags": False,
            "terminology": False,
            "length_ratio": {"enabled": False, "min": 0.5, "max": 3.0},
            "locale": {"enabled": False, "target_locale": "en-US"},
        },
    }


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    """An empty cwd with OL_CONFIG_PATH unset and the cache redirected.

    ``OL_CONFIG_PATH`` must go: tests/conftest.py sets it to the repo's
    absolute ``config/default.yaml`` via ``setdefault``, and Typer's
    CliRunner MERGES ``env=`` into ``os.environ`` rather than replacing it.
    """
    (tmp_path / "config").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OL_CONFIG_PATH", raising=False)
    monkeypatch.setenv("OMNI_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path


@pytest.fixture
def _fake_llm_env():
    """Activate the FAKE_LLM seam for the whole module (no real LLM calls)."""
    previous = os.environ.get("OMNI_TEST_FAKE_LLM")
    os.environ["OMNI_TEST_FAKE_LLM"] = "1"
    yield
    if previous is None:
        os.environ.pop("OMNI_TEST_FAKE_LLM", None)
    else:
        os.environ["OMNI_TEST_FAKE_LLM"] = previous


def _write_local_yaml(cwd: Path, project_id: str = "ol-config-resolution-probe") -> Path:
    target = cwd / LOCAL_CONFIG_RELPATH
    target.write_text(
        yaml.safe_dump(_probe_config(project_id), sort_keys=False),
        encoding="utf-8",
    )
    return target


def _write_input_md(cwd: Path) -> Path:
    src = cwd / "doc.md"
    src.write_text("# Title\n\nHello world.\n", encoding="utf-8")
    return src


def _translate_md_argv(cwd: Path, *extra: str) -> list[str]:
    return [
        "translate-md",
        str(_write_input_md(cwd)),
        "-o", str(cwd / "out"),
        "--no-frontmatter",
        "--no-restoration",
        "--no-cache",
        *extra,
    ]


def _spy_load_config(monkeypatch) -> list[Path]:
    """Record every path handed to ``ol_config.loader.load_config``.

    Both call sites import ``load_config`` inside the function body, so
    patching the module attribute is enough to observe the resolution.
    The real loader still runs, so a genuinely broken config still fails.
    """
    import ol_config.loader as loader_mod

    real_load_config = loader_mod.load_config
    seen: list[Path] = []

    def spy(path):
        seen.append(Path(path))
        return real_load_config(path)

    monkeypatch.setattr(loader_mod, "load_config", spy)
    return seen


class TestTranslateMdResolution:
    """translate-md must honour the generated config/local.yaml."""

    def test_local_yaml_wins_over_default_yaml(self, isolated_cwd, monkeypatch, _fake_llm_env):
        """cwd has config/local.yaml, OL_CONFIG_PATH unset → local.yaml is used.

        Pre-fix this raised ``Config file not found: config/default.yaml``
        (plus a misleading "run 'ol init'" hint) because level 2 was skipped.
        """
        local = _write_local_yaml(isolated_cwd)
        assert not (isolated_cwd / DEFAULT_CONFIG_RELPATH).exists(), (
            "fixture must not provide config/default.yaml — otherwise the "
            "level-2 resolution is unobservable"
        )
        seen = _spy_load_config(monkeypatch)

        result = runner.invoke(app, _translate_md_argv(isolated_cwd), env=ENV)

        assert result.exit_code == ExitCode.SUCCESS, (
            f"exit={result.exit_code}, out={result.output!r}, "
            f"exc={result.exception!r}"
        )
        assert seen, "load_config was never called — the command did no work"
        assert [p.resolve() for p in seen] == [local.resolve()], (
            f"expected only {LOCAL_CONFIG_RELPATH}, got {[str(p) for p in seen]}"
        )
        assert (isolated_cwd / "out" / "doc.md").exists(), "no output written"

    def test_ol_init_output_is_picked_up(self, isolated_cwd, _fake_llm_env):
        """The real `ol init` file closes the loop: init → translate-md works."""
        init_result = runner.invoke(
            app,
            ["init", "--non-interactive", "--force", "--config", str(isolated_cwd / LOCAL_CONFIG_RELPATH)],
            env=ENV,
        )
        assert init_result.exit_code == ExitCode.SUCCESS, (
            f"ol init failed: exit={init_result.exit_code}, out={init_result.output!r}"
        )
        assert (isolated_cwd / LOCAL_CONFIG_RELPATH).is_file()

        result = runner.invoke(app, _translate_md_argv(isolated_cwd), env=ENV)

        assert result.exit_code == ExitCode.SUCCESS, (
            f"exit={result.exit_code}, out={result.output!r}, exc={result.exception!r}"
        )
        assert "run 'ol init'" not in result.output, (
            "config generated by ol init was not honoured — the hint is a dead end"
        )

    def test_explicit_config_overrides_local_yaml(self, isolated_cwd, monkeypatch, _fake_llm_env):
        """--config still wins over config/local.yaml (already-working case)."""
        _write_local_yaml(isolated_cwd, project_id="from-local-yaml")
        explicit = isolated_cwd / "explicit.yaml"
        explicit.write_text(
            yaml.safe_dump(_probe_config("from-explicit-flag"), sort_keys=False),
            encoding="utf-8",
        )
        seen = _spy_load_config(monkeypatch)

        result = runner.invoke(
            app, _translate_md_argv(isolated_cwd, "--config", str(explicit)), env=ENV,
        )

        assert result.exit_code == ExitCode.SUCCESS, (
            f"exit={result.exit_code}, out={result.output!r}, exc={result.exception!r}"
        )
        assert all(p.resolve() == explicit.resolve() for p in seen), (
            f"explicit --config must win, got {[str(p) for p in seen]}"
        )

    def test_env_var_honoured_when_local_yaml_absent(self, isolated_cwd, monkeypatch, _fake_llm_env):
        """OL_CONFIG_PATH is still consulted when there is no local.yaml."""
        from_env = isolated_cwd / "from-env.yaml"
        from_env.write_text(
            yaml.safe_dump(_probe_config("from-env-var"), sort_keys=False),
            encoding="utf-8",
        )
        monkeypatch.setenv("OL_CONFIG_PATH", str(from_env))
        seen = _spy_load_config(monkeypatch)

        result = runner.invoke(app, _translate_md_argv(isolated_cwd), env=ENV)

        assert result.exit_code == ExitCode.SUCCESS, (
            f"exit={result.exit_code}, out={result.output!r}, exc={result.exception!r}"
        )
        assert all(p.resolve() == from_env.resolve() for p in seen), (
            f"OL_CONFIG_PATH must be honoured, got {[str(p) for p in seen]}"
        )

    def test_falls_through_to_default_when_local_yaml_absent(
        self, isolated_cwd, monkeypatch, _fake_llm_env,
    ):
        """A missing local.yaml is NOT an error — level 4 still applies."""
        (isolated_cwd / DEFAULT_CONFIG_RELPATH).write_text(
            yaml.safe_dump(_probe_config("from-default-yaml"), sort_keys=False),
            encoding="utf-8",
        )
        seen = _spy_load_config(monkeypatch)

        result = runner.invoke(app, _translate_md_argv(isolated_cwd), env=ENV)

        assert result.exit_code == ExitCode.SUCCESS, (
            f"exit={result.exit_code}, out={result.output!r}, exc={result.exception!r}"
        )
        assert [p.resolve() for p in seen] == [(isolated_cwd / DEFAULT_CONFIG_RELPATH).resolve()], (
            f"expected {DEFAULT_CONFIG_RELPATH}, got {[str(p) for p in seen]}"
        )


class TestOtherCliCommandsUseTheSameResolver:
    """inspect-config / judge-text / doctor must not keep private copies."""

    def test_inspect_config_reports_local_yaml(self, isolated_cwd, _fake_llm_env):
        local = _write_local_yaml(isolated_cwd, project_id="inspect-config-probe")

        result = runner.invoke(app, ["inspect-config"], env=ENV)

        assert result.exit_code == ExitCode.SUCCESS, (
            f"exit={result.exit_code}, out={result.output!r}, exc={result.exception!r}"
        )
        payload = json.loads(result.stdout)
        assert payload["config_path"] == LOCAL_CONFIG_RELPATH, (
            f"inspect-config resolved {payload['config_path']!r}, "
            f"expected {LOCAL_CONFIG_RELPATH!r}"
        )
        assert payload["project_id"] == "inspect-config-probe"
        assert local.is_file()

    def test_judge_text_resolves_local_yaml(self, isolated_cwd, monkeypatch, _fake_llm_env):
        """judge-text must build its ModelPool from the same resolved path."""
        from ol_pool.router import ModelPool

        _write_local_yaml(isolated_cwd, project_id="judge-text-probe")
        seen: list[str] = []

        def fake_get_instance(config_path):
            seen.append(config_path)
            raise RuntimeError("stop-after-resolution")

        monkeypatch.setattr(ModelPool, "get_instance", fake_get_instance)

        result = runner.invoke(
            app, ["judge-text", "hello", "你好", "-s", "en", "-t", "zh"], env=ENV,
        )

        assert result.exit_code == ExitCode.PIPELINE_ERROR, (
            f"exit={result.exit_code}, out={result.output!r}, exc={result.exception!r}"
        )
        assert seen == [LOCAL_CONFIG_RELPATH], (
            f"judge-text resolved {seen}, expected ['{LOCAL_CONFIG_RELPATH}']"
        )

    def test_doctor_and_translate_md_agree(self, isolated_cwd, monkeypatch, _fake_llm_env):
        """One resolver: doctor and translate-md pick the SAME config file."""
        _write_local_yaml(isolated_cwd, project_id="parity-probe")
        seen = _spy_load_config(monkeypatch)

        doctor_result = runner.invoke(app, ["doctor", "--json"], env=ENV)
        assert doctor_result.exit_code == ExitCode.SUCCESS, (
            f"doctor failed: exit={doctor_result.exit_code}, out={doctor_result.output!r}"
        )
        doctor_seen = list(seen)
        seen.clear()

        translate_result = runner.invoke(app, _translate_md_argv(isolated_cwd), env=ENV)
        assert translate_result.exit_code == ExitCode.SUCCESS, (
            f"translate-md failed: exit={translate_result.exit_code}, "
            f"out={translate_result.output!r}"
        )

        resolved = {str(p) for p in doctor_seen} | {str(p) for p in seen}
        assert resolved == {LOCAL_CONFIG_RELPATH}, (
            f"doctor and translate-md diverged: doctor={doctor_seen}, "
            f"translate-md={seen}"
        )


class TestResolverUnit:
    """Direct tests of the 4-level precedence."""

    def test_explicit_argument_wins(self, isolated_cwd, monkeypatch):
        _write_local_yaml(isolated_cwd)
        monkeypatch.setenv("OL_CONFIG_PATH", "/env/config.yaml")

        assert resolve_config_path("--config/explicit.yaml") == Path("--config/explicit.yaml")

    def test_local_yaml_beats_env_var(self, isolated_cwd, monkeypatch):
        _write_local_yaml(isolated_cwd)
        monkeypatch.setenv("OL_CONFIG_PATH", "/env/config.yaml")

        assert resolve_config_path(None) == Path(LOCAL_CONFIG_RELPATH)

    def test_env_var_used_when_local_yaml_missing(self, isolated_cwd, monkeypatch):
        monkeypatch.setenv("OL_CONFIG_PATH", "/env/config.yaml")

        assert resolve_config_path(None) == Path("/env/config.yaml")

    def test_default_relpath_is_the_last_resort(self, isolated_cwd):
        assert resolve_config_path(None) == Path(DEFAULT_CONFIG_RELPATH)

    def test_absent_local_yaml_is_optional_not_an_error(self, isolated_cwd):
        """Level 2 must never raise when the file is absent (dir may not exist)."""
        (isolated_cwd / "config").rmdir()
        assert not (isolated_cwd / LOCAL_CONFIG_RELPATH).exists()
        assert not (isolated_cwd / "config").exists()

        assert resolve_config_path(None) == Path(DEFAULT_CONFIG_RELPATH)
