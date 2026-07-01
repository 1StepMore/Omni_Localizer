"""Test for Issue #35 fix: --chunk-by-paragraph should translate paragraphs concurrently.

Before the fix, paragraphs were translated sequentially. For 20 paragraphs
at 0.5s each, sequential takes 10s. With concurrency=5, should take ~2s.
"""
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
        """20 paragraphs × 0.5s LLM each: concurrent should finish in <5s, sequential would take 10s."""
        md = Path("/tmp/ulw_test_concurrency.md")
        md.write_text("\n\n".join([f"Paragraph {i}." for i in range(20)]), encoding="utf-8")
        config = Path("/tmp/ulw_test_concurrency_config.yaml")
        _write_config(config)
        out = Path("/tmp/ulw_test_concurrency_out")
        out.mkdir(exist_ok=True)

        async def slow_translate(params):
            await asyncio.sleep(0.5)
            return json.dumps({
                "success": True,
                "translated": f"TRANSLATED_P{hash(params.content) % 1000}",
                "warnings": [],
                "source_lang": params.source_lang,
                "target_lang": params.target_lang,
            })

        start = time.monotonic()
        with patch("ol_mcp.tools.translate_md_text", new_callable=AsyncMock) as mock:
            mock.side_effect = slow_translate
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
        # With sequential, 20 * 0.5s = 10s.
        # Threshold: 6s (allows 3x overhead margin for sequential-equivalent)
        assert elapsed < 6.0, (
            f"20 paragraphs at 0.5s each took {elapsed:.2f}s — "
            f"concurrent translation not working (sequential would be ~10s)"
        )

    def test_paragraphs_preserve_input_order(self):
        """Even with concurrent translation, the output order must match input order."""
        md = Path("/tmp/ulw_test_concurrency_order.md")
        paragraphs = [f"Unique_paragraph_{i:03d}_content." for i in range(10)]
        md.write_text("\n\n".join(paragraphs), encoding="utf-8")
        config = Path("/tmp/ulw_test_concurrency_order_config.yaml")
        _write_config(config)
        out = Path("/tmp/ulw_test_concurrency_order_out")
        out.mkdir(exist_ok=True)

        # Mock that returns the same text it received (to verify ordering)
        async def echo_translate(params):
            await asyncio.sleep(0.1)
            return json.dumps({
                "success": True,
                "translated": params.content,
                "warnings": [],
                "source_lang": params.source_lang,
                "target_lang": params.target_lang,
            })

        with patch("ol_mcp.tools.translate_md_text", new_callable=AsyncMock) as mock:
            mock.side_effect = echo_translate
            result = runner.invoke(app, [
                "translate-md",
                str(md),
                "-o", str(out),
                "--config", str(config),
                "--chunk-by-paragraph",
                "--no-cache",
            ])

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        # Read the output file and verify order
        out_file = out / md.name
        output = out_file.read_text(encoding="utf-8")
        for i, p in enumerate(paragraphs):
            assert p in output, f"Paragraph {i} missing from output"
        # Verify order: each paragraph should appear in the output in the
        # same order as the input.
        positions = [output.index(p) for p in paragraphs]
        assert positions == sorted(positions), (
            f"Output order not preserved: positions={positions}"
        )
