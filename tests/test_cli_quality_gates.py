"""Tests for quality gates wired into CLI translate-md and translate-xliff (Issue #56)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from ol_cli import app

runner = CliRunner()

_MINIMAL_POOL = {
    "translation": [
        {
            "provider": "openai",
            "model": "glm-4-flash",
            "priority": 1,
            "role": "translation",
            "api_key": "test-key",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
        },
        {
            "provider": "openai",
            "model": "agnes-2.0-flash",
            "priority": 2,
            "role": "translation",
            "api_key": "test-key",
            "base_url": "https://apihub.agnes-ai.com/v1",
        },
    ],
    "judging": [
        {
            "provider": "openai",
            "model": "agnes-2.0-flash",
            "priority": 1,
            "role": "judging",
            "api_key": "test-key",
            "base_url": "https://apihub.agnes-ai.com/v1",
        },
        {
            "provider": "openai",
            "model": "glm-4-flash",
            "priority": 2,
            "role": "judging",
            "api_key": "test-key",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
        },
    ],
    "restoration": [
        {
            "provider": "openai",
            "model": "glm-4-flash",
            "priority": 1,
            "role": "restoration",
            "api_key": "test-key",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
        },
        {
            "provider": "openai",
            "model": "agnes-2.0-flash",
            "priority": 2,
            "role": "restoration",
            "api_key": "test-key",
            "base_url": "https://apihub.agnes-ai.com/v1",
        },
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fake_llm_env() -> None:
    """Ensure OMNI_TEST_FAKE_LLM is set for all tests."""
    with patch.dict(os.environ, {"OMNI_TEST_FAKE_LLM": "1"}):
        yield


@pytest.fixture
def tmp_config() -> type:  # noqa: ANN201
    """Fixture providing a helper to write temporary YAML configs."""
    _paths: list[str] = []

    def _make(content: dict) -> str:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w") as f:
            yaml.dump(content, f)
        _paths.append(path)
        return path

    yield _make

    for _p in _paths:
        try:
            os.unlink(_p)
        except OSError:
            pass


@pytest.fixture
def tmp_md() -> str:
    """Create a temporary MD file that triggers the currency mixing gate."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Test\n\nCost: $100 and €200\n")
        path = f.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def tmp_xliff() -> str:
    """Create a temporary XLIFF file with a unit that triggers length ratio gate."""
    content = """<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="test" source-language="en" target-language="zh">
    <body>
      <trans-unit id="1">
        <source>a</source>
        <target></target>
      </trans-unit>
    </body>
  </file>
</xliff>"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xlf", delete=False) as f:
        f.write(content)
        path = f.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def tmp_output_dir() -> str:
    """Create a temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(disabled: bool = False, no_gates_key: bool = False) -> dict:
    """Build a test config with quality gates in the desired state.

    Args:
        disabled: When True, all sub-gates are disabled.
        no_gates_key: When True, the ``quality_gates`` key is omitted
            entirely (tests defaults).
    """
    cfg: dict = {
        "project_id": "test-quality-gates",
        "source_lang": "en",
        "target_lang": "zh",
        "llm_pool": _MINIMAL_POOL,
        "max_md_concurrent": 1,  # Force serial path for deterministic MD output
        "enable_lqa": False,
    }
    if no_gates_key:
        return cfg
    if disabled:
        cfg["quality_gates"] = {
            "inline_tags": False,
            "terminology": False,
            "length_ratio": {"enabled": False, "min": 0.5, "max": 3.0},
            "locale": {"enabled": False, "target_locale": "en-US"},
        }
    else:
        cfg["quality_gates"] = {
            "inline_tags": True,
            "terminology": True,
            "length_ratio": {"enabled": True, "min": 0.5, "max": 3.0},
            "locale": {"enabled": True, "target_locale": "en-US"},
        }
    return cfg


# ---------------------------------------------------------------------------
# MD path quality gate tests
# ---------------------------------------------------------------------------


class TestMDQualityGates:
    """Quality gates in the ``translate-md`` CLI path."""

    def test_md_gate_warnings_appended(
        self, tmp_md: str, tmp_output_dir: str, tmp_config,  # noqa: ANN001
    ) -> None:
        """MD path: gate warnings are appended as HTML comments when gates fire.

        The input contains both ``$`` and ``€``, which triggers the
        currency mixing check (Gate 4). The warnings should appear in
        the output file.
        """
        cfg_path = tmp_config(_make_config(disabled=False))
        result = runner.invoke(
            app,
            [
                "translate-md",
                tmp_md,
                "--config", cfg_path,
                "-o", tmp_output_dir,
                "--no-frontmatter",
                "--no-restoration",
                "--no-cache",
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"

        output_file = Path(tmp_output_dir) / Path(tmp_md).name
        assert output_file.exists(), "Output file not created"
        content = output_file.read_text(encoding="utf-8")
        # The input has $ and € → currency mixing warning
        assert "<!-- Quality gate warnings -->" in content, (
            f"Expected quality gate warnings, got:\n{content}"
        )
        assert "OL_WARN: CURRENCY_MIXING" in content, (
            f"Expected CURRENCY_MIXING warning, got:\n{content}"
        )

    def test_md_disabled_gates_no_warnings(
        self, tmp_md: str, tmp_output_dir: str, tmp_config,  # noqa: ANN001
    ) -> None:
        """MD path: when all quality gates are disabled, no warnings appended."""
        cfg_path = tmp_config(_make_config(disabled=True))
        result = runner.invoke(
            app,
            [
                "translate-md",
                tmp_md,
                "--config", cfg_path,
                "-o", tmp_output_dir,
                "--no-frontmatter",
                "--no-restoration",
                "--no-cache",
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"

        output_file = Path(tmp_output_dir) / Path(tmp_md).name
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "<!-- Quality gate warnings -->" not in content, (
            f"Unexpected quality gate warnings with disabled gates:\n{content}"
        )

    def test_md_missing_config_gate_key_uses_defaults(
        self, tmp_md: str, tmp_output_dir: str, tmp_config,  # noqa: ANN001
    ) -> None:
        """MD path: a config without ``quality_gates`` key uses defaults (all enabled).

        Defaults have all gates enabled, so currency mixing should still
        be detected.
        """
        cfg_path = tmp_config(_make_config(no_gates_key=True))
        result = runner.invoke(
            app,
            [
                "translate-md",
                tmp_md,
                "--config", cfg_path,
                "-o", tmp_output_dir,
                "--no-frontmatter",
                "--no-restoration",
                "--no-cache",
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"

        output_file = Path(tmp_output_dir) / Path(tmp_md).name
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        # Defaults have locale enabled → currency mixing should fire
        assert "<!-- Quality gate warnings -->" in content, (
            f"Expected quality gates with defaults, got:\n{content}"
        )


# ---------------------------------------------------------------------------
# XLIFF path quality gate tests
# ---------------------------------------------------------------------------


class TestXLIFFQualityGates:
    """Quality gates in the ``translate-xliff`` CLI path."""

    def test_xliff_gate_warnings_appended(
        self, tmp_xliff: str, tmp_output_dir: str, tmp_config,  # noqa: ANN001
    ) -> None:
        """XLIFF path: gate warnings are merged into ``warnings_per_unit``.

        The input has source text "a" (1 char) and the fake LLM produces
        "[zh] a" (6 chars), giving a length ratio of 6.0 > 3.0 → warning.
        """
        cfg_path = tmp_config(_make_config(disabled=False))
        result = runner.invoke(
            app,
            [
                "translate-xliff",
                tmp_xliff,
                "--config", cfg_path,
                "-o", tmp_output_dir,
                "--no-restoration",
                "--no-cache",
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"

        # Verify the output XLIFF was created
        output_file = Path(tmp_output_dir) / Path(tmp_xliff).name
        assert output_file.exists(), "Output file not created"

        # Check that warnings were written into the XLIFF notes
        content = output_file.read_text(encoding="utf-8")
        assert "OL_WARN: LENGTH_RATIO" in content, (
            f"Expected LENGTH_RATIO warning in XLIFF output, got:\n{content}"
        )

    def test_xliff_disabled_gates_no_warnings(
        self, tmp_xliff: str, tmp_output_dir: str, tmp_config,  # noqa: ANN001
    ) -> None:
        """XLIFF path: disabled gates produce no warnings."""
        cfg_path = tmp_config(_make_config(disabled=True))
        result = runner.invoke(
            app,
            [
                "translate-xliff",
                tmp_xliff,
                "--config", cfg_path,
                "-o", tmp_output_dir,
                "--no-restoration",
                "--no-cache",
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"

        output_file = Path(tmp_output_dir) / Path(tmp_xliff).name
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "OL_WARN: LENGTH_RATIO" not in content, (
            f"Unexpected LENGTH_RATIO warning with disabled gates:\n{content}"
        )

    def test_xliff_missing_config_gate_key_uses_defaults(
        self, tmp_xliff: str, tmp_output_dir: str, tmp_config,  # noqa: ANN001
    ) -> None:
        """XLIFF path: config without ``quality_gates`` key uses defaults.

        Defaults have all gates enabled, so length ratio should still
        be detected.
        """
        cfg_path = tmp_config(_make_config(no_gates_key=True))
        result = runner.invoke(
            app,
            [
                "translate-xliff",
                tmp_xliff,
                "--config", cfg_path,
                "-o", tmp_output_dir,
                "--no-restoration",
                "--no-cache",
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"

        output_file = Path(tmp_output_dir) / Path(tmp_xliff).name
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "OL_WARN: LENGTH_RATIO" in content, (
            f"Expected LENGTH_RATIO with defaults, got:\n{content}"
        )
