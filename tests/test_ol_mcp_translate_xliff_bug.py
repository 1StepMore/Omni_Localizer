"""ULTRAREADY-FIX (2026-06-08): regression test for the OL MCP translate_xliff bug.

Discovered during a real end-to-end pipeline run: the MCP tool's
translate_xliff function returns `{"success": true, "units_processed": N}`
but writes empty `<target>` elements to the output file. The CLI
path works correctly. This test pins the contract that the MCP path
must also write real translations.
"""
import asyncio
import json
import os
import xml.etree.ElementTree as ET

import pytest

from ol_mcp.tools import TranslateXliffInput, translate_xliff


NS = {"x": "urn:oasis:names:tc:xliff:document:1.2"}


def _has_real_llm_keys() -> bool:
    """Check env (lazily, so monkeypatch.setenv in the test takes effect)."""
    return bool(
        os.environ.get("MINIMAX_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("BAIDU_API_KEY")
    )


def _make_minimal_xliff(source: str = "爱上海尔") -> str:
    """Build a minimal 1-unit XLIFF with a known Chinese source."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xliff xmlns="urn:oasis:names:tc:xliff:document:1.2" version="1.2">\n'
        '<file original="test" source-language="zh" target-language="en" datatype="plaintext">\n'
        "<body>\n"
        '<trans-unit id="u0" resname="para_index_0">\n'
        f"<source>{source}</source>\n"
        '<target state="translated"></target>\n'
        "</trans-unit>\n"
        "</body>\n"
        "</file>\n"
        "</xliff>\n"
    )


def _read_targets(path: str) -> list[str]:
    tree = ET.parse(path)
    return [
        (t.text or "").strip()
        for t in tree.findall(".//x:trans-unit/x:target", NS)
    ]


class TestTranslateXliffEndToEnd:
    """End-to-end test that pins the contract translate_xliff writes real targets.

    The bug: the tool returns success=true and units_processed=1 but
    the output file has an empty <target> for that unit. This test
    fails (RED) on the current code, then passes (GREEN) after the fix.
    """

    def test_translate_xliff_writes_non_empty_targets(
        self, tmp_path, monkeypatch
    ):
        """RED: target text must be non-empty after a successful call."""
        # Source .env so the OLConfig + LiteLLM pick up the keys.
        from pathlib import Path
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    monkeypatch.setenv(k.strip(), v.strip())

        if not _has_real_llm_keys():
            pytest.skip("no MINIMAX/OPENAI/BAIDU API key set")

        input_path = tmp_path / "small.xlf"
        input_path.write_text(_make_minimal_xliff("爱上海尔"), encoding="utf-8")
        output_path = tmp_path / "small_translated.xlf"

        result_str = asyncio.run(translate_xliff(
            TranslateXliffInput(
                input_path=str(input_path),
                output_path=str(output_path),
                source_lang="zh",
                target_lang="en",
                config_path=str(Path(__file__).resolve().parent.parent / "config" / "default.yaml"),
            )
        ))
        result = json.loads(result_str)
        assert result.get("success") is True, f"call failed: {result!r}"
        assert result.get("units_processed") == 1, f"wrong count: {result!r}"

        targets = _read_targets(str(output_path))
        assert len(targets) == 1, f"expected 1 target, got {len(targets)}"
        # The contract: target text is non-empty (a real English translation).
        assert targets[0], (
            f"BUG: target text is empty despite success=True. "
            f"Full result: {result!r}, targets: {targets!r}"
        )


class TestTranslateXliffMcpStyleGuide:
    """T2.4 tests: styleguide_path flows through to build_translate_prompt."""

    def _make_minimal_xliff(self, tmp_path) -> str:
        xlf = tmp_path / "in.xlf"
        xlf.write_text(_make_minimal_xliff("Hello"), encoding="utf-8")
        return str(xlf)

    def _make_styleguide(self, tmp_path) -> str:
        sg = tmp_path / "sg.json"
        sg.write_text(
            '{"tone":"formal","register":"technical","target_audience":"devs",'
            '"key_conventions":["Use clear prose"],"vocabulary":[],'
            '"avoid":["jargon"],"summary":"test"}'
        )
        return str(sg)

    def test_mcp_styleguide_load_emits_warning_on_missing_file(self, tmp_path, monkeypatch):
        from pathlib import Path
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    monkeypatch.setenv(k.strip(), v.strip())

        input_path = tmp_path / "in.xlf"
        input_path.write_text(_make_minimal_xliff("Hello"), encoding="utf-8")

        result_str = asyncio.run(translate_xliff(
            TranslateXliffInput(
                input_path=str(input_path),
                source_lang="en",
                target_lang="zh",
                config_path=str(Path(__file__).resolve().parent.parent / "config" / "default.yaml"),
                styleguide_path="/nonexistent/sg.json",
            )
        ))
        result = json.loads(result_str)
        assert result.get("success") is True
        warnings = result.get("content", {}).get("warnings", []) or result.get("warnings", [])
        assert any("StyleGuide" in w or "PATH_NOT_ALLOWED" in w for w in warnings), (
            f"expected StyleGuide/path warning, got: {warnings!r}"
        )

    def test_mcp_styleguide_loaded_into_prompt(self, tmp_path, monkeypatch):
        """When styleguide_path is valid, the LLM prompt receives the styleguide section."""
        from pathlib import Path
        from unittest.mock import patch, AsyncMock
        from ol_mcp.translate_xliff import translate_xliff as mcp_translate_xliff

        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    monkeypatch.setenv(k.strip(), v.strip())

        input_path = tmp_path / "in.xlf"
        input_path.write_text(_make_minimal_xliff("Hello"), encoding="utf-8")
        sg_path = self._make_styleguide(tmp_path)

        captured_contexts: list[str | None] = []

        async def fake_translate(self, text, src, tgt, context=None, **kwargs):
            captured_contexts.append(context)
            return f"[{tgt}] {text}"

        with patch("ol_pool.router.ModelPool.translate", new=fake_translate):
            result_str = asyncio.run(mcp_translate_xliff(
                TranslateXliffInput(
                    input_path=str(input_path),
                    source_lang="en",
                    target_lang="zh",
                    config_path=str(Path(__file__).resolve().parent.parent / "config" / "default.yaml"),
                    styleguide_path=sg_path,
                )
            ))
        result = json.loads(result_str)
        assert result.get("success") is True, f"call failed: {result!r}"
        assert len(captured_contexts) >= 1, f"expected pool.translate to be called, got {captured_contexts!r}"
        ctx = captured_contexts[0]
        assert ctx is not None
        assert "[Style Guide]" in ctx, f"StyleGuide section missing from context: {ctx[:300]}"
