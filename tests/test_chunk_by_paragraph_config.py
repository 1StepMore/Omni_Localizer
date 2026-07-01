"""Test for Issue #33 fix: --config must reach ModelPool.get_instance.

The chunk-by-paragraph path was fixed in commit 95b893a to bypass
the MCP tool layer and call the underlying pipeline (shield → pool.translate
→ unshield → repair) directly. This test verifies that the --config
flag is propagated to ModelPool.get_instance so the right config is
loaded for the LLM pool.
"""
import json
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


class TestChunkByParagraphConfig:
    def test_chunk_by_paragraph_passes_config_to_pool(self):
        """--chunk-by-paragraph must forward --config to ModelPool.get_instance."""
        md = Path("/tmp/ulw_test_chunk_cfg2.md")
        md.write_text("Para 1.\n\nPara 2.\n\n", encoding="utf-8")
        config = Path("/tmp/ulw_test_chunk_cfg2_config.yaml")
        _write_config(config)
        out = Path("/tmp/ulw_test_chunk_cfg2_out")
        out.mkdir(exist_ok=True)

        with patch("ol_pool.router.ModelPool.get_instance") as mock_get:
            mock_pool = MagicMock()
            mock_pool.translate = AsyncMock(return_value="translated_text")
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
        # The fix's code: ModelPool.get_instance(config) if config else ...
        mock_get.assert_called_with(str(config))
