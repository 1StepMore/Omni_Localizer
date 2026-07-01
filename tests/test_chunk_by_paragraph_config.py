"""RED test for Issue #33: --chunk-by-paragraph must propagate --config to MCP tool."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from ol_cli import app

runner = CliRunner()


class TestChunkByParagraphConfig:
    def test_chunk_by_paragraph_passes_config_to_mcp(self):
        """--chunk-by-paragraph must forward --config to translate_md_text MCP call."""

        tmp_path = Path("/tmp/ulw_test_chunk_cfg")
        tmp_path.mkdir(exist_ok=True)
        md = tmp_path / "input.md"
        md.write_text("Para 1.\n\nPara 2.\n\n", encoding="utf-8")
        config = tmp_path / "config.yaml"
        # Use a minimal valid config (not a translation request, but enough to load)
        config.write_text(
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
        out = tmp_path / "out"

        with patch("ol_mcp.tools.translate_md_text", new_callable=AsyncMock) as mock:
            mock.return_value = json.dumps({"success": True, "translated": "x"})
            result = runner.invoke(app, [
                "translate-md",
                str(md),
                "-o", str(out),
                "--config", str(config),
                "--chunk-by-paragraph",
                "--no-cache",
            ])

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert mock.call_count > 0, "translate_md_text was not called"
        for call in mock.call_args_list:
            input_obj = call.args[0]
            assert input_obj.config_path == str(config), (
                f"Expected config_path={config}, got {input_obj.config_path}"
            )
