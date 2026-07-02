"""Test for Issue #35: --chunk-by-paragraph translates paragraphs concurrently.

The fix in commit 95b893a bypasses the MCP tool layer and uses the
underlying pipeline (shield → pool.translate → unshield → repair) directly.
This test verifies:
1. Concurrency: 20 paragraphs complete in <6s with 0.5s/call (vs 10s sequential)
2. Order preservation: output order matches input order
"""
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from ol_cli import app

runner = CliRunner()


def _write_config(path: Path) -> None:
    path.write_text(
        "project_id: test\nsource_lang: en\ntarget_lang: zh\nllm_pool:\n"
        "  translation:\n"
        "    - provider: openai\n      model: glm-4-flash\n      priority: 1\n"
        "      role: translation\n      api_key: ${ZHIPU_API_KEY}\n"
        "      base_url: http://localhost\n    - provider: openai\n"
        "      model: glm-4-flash\n      priority: 2\n      role: translation\n"
        "      api_key: ${ZHIPU_API_KEY}\n      base_url: http://localhost\n"
        "  judging:\n"
        "    - provider: openai\n      model: glm-4-flash\n      priority: 1\n"
        "      role: judging\n      api_key: ${ZHIPU_API_KEY}\n"
        "      base_url: http://localhost\n    - provider: openai\n"
        "      model: glm-4-flash\n      priority: 2\n      role: judging\n"
        "      api_key: ${ZHIPU_API_KEY}\n      base_url: http://localhost\n"
        "  restoration:\n"
        "    - provider: openai\n      model: glm-4-flash\n      priority: 1\n"
        "      role: restoration\n      api_key: ${ZHIPU_API_KEY}\n"
        "      base_url: http://localhost\n    - provider: openai\n"
        "      model: glm-4-flash\n      priority: 2\n      role: restoration\n"
        "      api_key: ${ZHIPU_API_KEY}\n      base_url: http://localhost\n",
        encoding="utf-8",
    )


class TestChunkByParagraphConcurrency:
    def test_20_paragraphs_translate_concurrently(self):
        """20 paragraphs at 0.5s each: concurrent <6s vs sequential ~10s."""
        md = Path("/tmp/ulw_test_concurrency.md")
        md.write_text("\n\n".join([f"Paragraph {i}." for i in range(20)]), encoding="utf-8")
        config = Path("/tmp/ulw_test_concurrency_config.yaml")
        _write_config(config)
        out = Path("/tmp/ulw_test_concurrency_out")
        out.mkdir(exist_ok=True)

        async def slow_translate(text, src, tgt, context=None):
            await asyncio.sleep(0.5)
            return f"TRANSLATED_{text[:20]}"

        with patch("ol_pool.router.ModelPool.get_instance") as mock_get:
            mock_pool = MagicMock()
            mock_pool.translate = AsyncMock(side_effect=slow_translate)
            mock_get.return_value = mock_pool
            start = time.monotonic()
            result = runner.invoke(app, [
                "translate-md",
                str(md),
                "-o", str(out),
                "--config", str(config),
                "--chunk-by-paragraph",
                "--no-cache",
            ])
            elapsed = time.monotonic() - start

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        # With concurrency=5, 20 paras / 5 = 4 batches * 0.5s = 2s + overhead
        assert elapsed < 6.0, (
            f"20 paragraphs at 0.5s each took {elapsed:.2f}s — "
            f"concurrent translation not working (sequential would be ~10s)"
        )

    def test_paragraphs_preserve_input_order(self):
        """Even with concurrent translation, output order matches input order."""
        md = Path("/tmp/ulw_test_concurrency_order.md")
        paragraphs = [f"Unique_paragraph_{i:03d}_content." for i in range(10)]
        md.write_text("\n\n".join(paragraphs), encoding="utf-8")
        config = Path("/tmp/ulw_test_concurrency_order_config.yaml")
        _write_config(config)
        out = Path("/tmp/ulw_test_concurrency_order_out")
        out.mkdir(exist_ok=True)

        # Echo the input so we can verify ordering
        async def echo_translate(text, src, tgt, context=None):
            await asyncio.sleep(0.1)
            return text

        with patch("ol_pool.router.ModelPool.get_instance") as mock_get:
            mock_pool = MagicMock()
            mock_pool.translate = AsyncMock(side_effect=echo_translate)
            mock_get.return_value = mock_pool
            result = runner.invoke(app, [
                "translate-md",
                str(md),
                "-o", str(out),
                "--config", str(config),
                "--chunk-by-paragraph",
                "--no-cache",
            ])

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        out_file = out / md.name
        output = out_file.read_text(encoding="utf-8")
        positions = [output.index(p) for p in paragraphs]
        assert positions == sorted(positions), (
            f"Output order not preserved: positions={positions}"
        )


class TestChunkByParagraphProgress:
    """Issue #6: chunk-by-paragraph should emit progress output during translation.

    Without progress, users running 100+ paragraph translations have NO
    indication of whether the process is stuck or working.
    """

    def test_chunk_by_paragraph_emits_progress_to_stderr(self, tmp_path, monkeypatch, capsys):
        """Progress messages should appear on stderr during translation."""
        from cli.translate_md import _translate_md_by_paragraph

        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")

        # 12 paragraphs (>5 to trigger first progress milestone at 5)
        paragraphs = [
            f"Paragraph number {i}. This is test content for translation progress check."
            for i in range(12)
        ]
        md = tmp_path / "test.md"
        md.write_text("\n\n".join(paragraphs), encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()

        # Force isatty() to return True (since test env has no real tty)
        import sys
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

        asyncio.run(_translate_md_by_paragraph(
            input_path=md,
            output_path=out,
            config=None,
            src="en",
            tgt="zh",
            add_frontmatter=False,
        ))

        captured = capsys.readouterr()
        # Progress should appear on stderr
        err = captured.err
        assert "12/" in err or "paragraphs" in err.lower(), (
            f"Expected progress output on stderr; got: {err!r}"
        )

    def test_chunk_by_paragraph_silent_when_not_tty(self, tmp_path, monkeypatch, capsys):
        """Progress should NOT appear when stderr is not a tty (piped output)."""
        from cli.translate_md import _translate_md_by_paragraph

        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")

        paragraphs = [f"Para {i} of test content for silent mode." for i in range(8)]
        md = tmp_path / "test.md"
        md.write_text("\n\n".join(paragraphs), encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()

        import sys
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False)

        asyncio.run(_translate_md_by_paragraph(
            input_path=md,
            output_path=out,
            config=None,
            src="en",
            tgt="zh",
            add_frontmatter=False,
        ))

        captured = capsys.readouterr()
        err = captured.err
        # No progress should appear when not a tty
        assert "paragraphs" not in err.lower() or "8/" not in err, (
            f"Expected NO progress on stderr in non-tty mode; got: {err!r}"
        )

    def test_chunk_by_paragraph_quiet_flag_suppresses_progress(self, tmp_path, monkeypatch, capsys):
        """The quiet=True parameter must suppress progress output even on a tty."""
        from cli.translate_md import _translate_md_by_paragraph

        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")

        paragraphs = [f"Para {i} of test content for quiet mode." for i in range(8)]
        md = tmp_path / "test.md"
        md.write_text("\n\n".join(paragraphs), encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()

        import sys
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

        asyncio.run(_translate_md_by_paragraph(
            input_path=md,
            output_path=out,
            config=None,
            src="en",
            tgt="zh",
            add_frontmatter=False,
            quiet=True,
        ))

        captured = capsys.readouterr()
        err = captured.err
        # quiet=True must suppress progress
        assert "paragraphs" not in err.lower() or "8/" not in err, (
            f"quiet=True should suppress progress; got: {err!r}"
        )
