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
