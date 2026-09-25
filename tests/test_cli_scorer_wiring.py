"""OL#72: ``--scorer``/``--no-scorer`` CLI wiring reaches the judge.

The 12679b1 cleanup removed the CLI scorer options and the plumbing that
handed a ``ScorerService``/``COMETService`` instance to ``JudgeService``.
These tests pin the restored public surface: selecting ``--scorer bleu``
must cause the judge's optional scorer to be invoked per judged unit.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from ol_cli import app
from ol_lqa import scorer as scorer_module

runner = CliRunner()

_MINIMAL_POOL = {
    "translation": [
        {"provider": "openai", "model": "glm-4-flash", "priority": 1,
         "role": "translation", "api_key": "test-key",
         "base_url": "https://open.bigmodel.cn/api/paas/v4"},
        {"provider": "openai", "model": "agnes-2.0-flash", "priority": 2,
         "role": "translation", "api_key": "test-key",
         "base_url": "https://apihub.agnes-ai.com/v1"},
    ],
    "judging": [
        {"provider": "openai", "model": "agnes-2.0-flash", "priority": 1,
         "role": "judging", "api_key": "test-key",
         "base_url": "https://apihub.agnes-ai.com/v1"},
        {"provider": "openai", "model": "glm-4-flash", "priority": 2,
         "role": "judging", "api_key": "test-key",
         "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    ],
    "restoration": [
        {"provider": "openai", "model": "glm-4-flash", "priority": 1,
         "role": "restoration", "api_key": "test-key",
         "base_url": "https://open.bigmodel.cn/api/paas/v4"},
        {"provider": "openai", "model": "agnes-2.0-flash", "priority": 2,
         "role": "restoration", "api_key": "test-key",
         "base_url": "https://apihub.agnes-ai.com/v1"},
    ],
}


@pytest.fixture(autouse=True)
def _fake_llm_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
    monkeypatch.setenv("OMNI_CACHE_DIR", str(tmp_path / "cache"))


def _lqa_config(tmp_path: Path) -> Path:
    cfg = {
        "project_id": "test-scorer-wiring",
        "source_lang": "en",
        "target_lang": "zh",
        "llm_pool": _MINIMAL_POOL,
        "max_md_concurrent": 1,
        "enable_lqa": True,
        "lqa_threshold": 4.0,
        "lqa_max_retries": 1,
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return path


def _invoke(input_md: Path, out_dir: Path, config: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "translate-md", str(input_md),
            "--config", str(config),
            "-s", "en", "-t", "zh",
            "-o", str(out_dir),
            "--no-frontmatter", "--no-restoration", "--no-cache",
            *extra,
        ],
    )


class TestScorerCliWiring:
    def test_scorer_bleu_reaches_judge(self, tmp_path: Path):
        input_md = tmp_path / "input.md"
        input_md.write_text("# Hello\n\nSame text here.\n", encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        original = scorer_module.ScorerService.score_and_evaluate
        spy = AsyncMock(side_effect=original)
        with patch.object(scorer_module.ScorerService, "score_and_evaluate", spy):
            result = _invoke(
                input_md, out_dir, _lqa_config(tmp_path),
                "--scorer", "bleu",
            )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert spy.await_count > 0, "--scorer bleu never reached JudgeService"

    def test_no_scorer_skips_scorer(self, tmp_path: Path):
        input_md = tmp_path / "input.md"
        input_md.write_text("# Hello\n\nSame text here.\n", encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        original = scorer_module.ScorerService.score_and_evaluate
        spy = AsyncMock(side_effect=original)
        with patch.object(scorer_module.ScorerService, "score_and_evaluate", spy):
            result = _invoke(
                input_md, out_dir, _lqa_config(tmp_path),
                "--scorer", "bleu", "--no-scorer",
            )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert spy.await_count == 0, "--no-scorer must override --scorer"

    def test_scorer_comet_unavailable_falls_back_to_no_scorer(
        self, tmp_path: Path, caplog,
    ):
        """OL#73: selecting ``--scorer comet`` without the optional
        ``unbabel-comet`` dependency must fail soft at the selection
        boundary — no scorer is bound and a single clear warning is
        emitted, instead of raising at judge time per unit.
        """
        input_md = tmp_path / "input.md"
        input_md.write_text("# Hello\n\nSame text here.\n", encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        from ol_lqa.comet import COMETService

        scorer_spy = AsyncMock()
        with patch.object(COMETService, "score_and_evaluate", scorer_spy), \
             patch("ol_lqa.comet.download_model", None), \
             patch("ol_lqa.comet.load_from_checkpoint", None):
            with caplog.at_level(logging.WARNING, logger="ol.cli"):
                result = _invoke(
                    input_md, out_dir, _lqa_config(tmp_path),
                    "--scorer", "comet",
                )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert scorer_spy.await_count == 0, (
            "--scorer comet without unbabel-comet must not invoke the COMET scorer"
        )
        assert any(
            "comet" in record.getMessage().lower() for record in caplog.records
        ), f"expected a clear comet-unavailable warning, got: {caplog.records}"
