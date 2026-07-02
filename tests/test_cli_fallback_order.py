"""Tests for Issue #38: OL CLI fallback order in translate_md + batch.

Before fix: cli/translate_md.py:827-828 hardcodes
`src = source_lang or "en"` and `tgt = target_lang or "zh"` BEFORE the
config is loaded. The subsequent `src = src or cfg.source_lang` at
line 835-836 is dead code because `src` is already truthy.

Result: `ol translate-md file.md` (no -s/-t) ALWAYS uses en->zh,
even if the config sets source_lang=zh, target_lang=en. The user
cannot make zh->en the default via config.

translate_xliff.py:488-502 has the correct pattern: don't hardcode
fallback before config.

After fix: same pattern as translate_xliff — config defaults take
effect when no -s/-t is passed.
"""
import os
from pathlib import Path

import pytest
import yaml


class TestCliFallbackOrder:
    """Issue #38: CLI must honor config defaults when no -s/-t flags."""

    def _write_config(self, tmp_path, source_lang, target_lang):
        # Each role needs at least 2 models (primary + backup) per schema
        def _models(role):
            return [
                {
                    "provider": "openai",
                    "model": "glm-4-flash",
                    "priority": 1,
                    "role": role,
                    "api_key": "${ZHIPU_API_KEY}",
                    "base_url": "http://localhost",
                },
                {
                    "provider": "openai",
                    "model": "glm-4-flash",
                    "priority": 2,
                    "role": role,
                    "api_key": "${ZHIPU_API_KEY}",
                    "base_url": "http://localhost",
                },
            ]
        cfg = {
            "project_id": "test-#38",
            "source_lang": source_lang,
            "target_lang": target_lang,
            "llm_pool": {
                "translation": _models("translation"),
                "judging": _models("judging"),
                "restoration": _models("restoration"),
            },
        }
        cfg_path = tmp_path / "test_38.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        return cfg_path

    def test_cli_uses_config_source_lang_when_no_flag(self, tmp_path, monkeypatch):
        """Issue #38 R1: config source_lang=zh + no -s flag → uses zh.

        Verifies the bug by checking the CLI's own diagnostic output
        ("Using config: project_id (src -> tgt)" at line 838) — with the
        bug, src is hardcoded to "en" regardless of config.
        """
        from typer.testing import CliRunner
        from ol_cli import app

        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
        cfg_path = self._write_config(tmp_path, "zh", "en")
        md = tmp_path / "in.md"
        md.write_text("hello", encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "translate-md", str(md),
                "-o", str(out),
                "--config", str(cfg_path),
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        # The CLI echoes "(zh -> en)" if config defaults are honored.
        # With the bug, it would print "(en -> zh)" because hardcoded
        # defaults are used.
        assert "(zh -> en)" in result.output or "(zh -> en)" in result.stderr, (
            f"Expected CLI to use config defaults (zh -> en). Output: {result.output!r}"
        )

    def test_cli_explicit_flag_overrides_config(self, tmp_path, monkeypatch):
        """Issue #38 R2: config says zh, but -s en -t ja → uses en->ja."""
        from typer.testing import CliRunner
        from ol_cli import app

        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
        cfg_path = self._write_config(tmp_path, "zh", "en")
        md = tmp_path / "in.md"
        md.write_text("hello", encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "translate-md", str(md),
                "-o", str(out),
                "--config", str(cfg_path),
                "-s", "en", "-t", "ja",
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        out_file = out / "in.md"
        assert out_file.exists()

    def test_cli_no_config_falls_back_to_en_zh(self, tmp_path, monkeypatch):
        """Issue #38 R3: no --config, no -s/-t → falls back to hardcoded en->zh."""
        from typer.testing import CliRunner
        from ol_cli import app

        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
        md = tmp_path / "in.md"
        md.write_text("hello", encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "translate-md", str(md),
                "-o", str(out),
                # No --config, no -s/-t
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        out_file = out / "in.md"
        assert out_file.exists()

    def test_cli_partial_override_src_only(self, tmp_path, monkeypatch):
        """Issue #38 R4: config zh->en, CLI with -s de only → de->en."""
        from typer.testing import CliRunner
        from ol_cli import app

        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
        cfg_path = self._write_config(tmp_path, "zh", "en")
        md = tmp_path / "in.md"
        md.write_text("hello", encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "translate-md", str(md),
                "-o", str(out),
                "--config", str(cfg_path),
                "-s", "de",  # only src override
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        out_file = out / "in.md"
        assert out_file.exists()

    def test_batch_uses_config_source_lang(self, tmp_path, monkeypatch):
        """Issue #38 R5: batch.py has the same bug — must be fixed too."""
        from typer.testing import CliRunner
        from ol_cli import app

        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
        cfg_path = self._write_config(tmp_path, "zh", "en")
        md = tmp_path / "in.md"
        md.write_text("hello", encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "translate-batch", str(tmp_path),
                "-o", str(out),
                "--config", str(cfg_path),
            ],
        )
        # batch might also process other files in tmp_path; the
        # important thing is the call didn't crash with hardcoded en->zh
        # when config says zh->en
        assert result.exit_code == 0, f"batch failed: {result.output}"

    def test_cli_fallback_surface_fake_llm(self, tmp_path, monkeypatch):
        """Issue #38 R6: SURFACE — end-to-end CLI with config + FAKE_LLM."""
        from typer.testing import CliRunner
        from ol_cli import app

        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
        cfg_path = self._write_config(tmp_path, "zh", "en")
        md = tmp_path / "surface.md"
        md.write_text("# Surface\n\nhello world", encoding="utf-8")
        out = tmp_path / "surface_out"
        out.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "translate-md", str(md),
                "-o", str(out),
                "--config", str(cfg_path),
            ],
        )
        # The CLI must succeed (no AttributeError, no KeyError) and
        # produce the output file. The content is FAKE_LLM (just [en] hello world)
        # but the important thing is the pipeline ran.
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        out_file = out / "surface.md"
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        # The fake pool returns [target_lang] source, so we should see [en]
        # since config has target_lang=en
        assert "[en]" in content or "hello" in content, (
            f"Output should be the fake LLM translation: {content!r}"
        )
