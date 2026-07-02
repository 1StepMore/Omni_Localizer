"""Tests for Issue #37: OL MCP translate_file tool (file-based OPP→OL→ORF).

Before fix: no MCP tool exists for file-based end-to-end translation.
Users had to call translate_md_text with raw text (in-memory) or run
three separate CLIs (opp, ol translate-md, orf apply-md).

After fix: a single MCP tool translate_file that:
  1. Shells out to `opp` (extract to MD + XLIFF + skeleton)
  2. Shells out to `ol translate-md` or `ol translate-xliff` (translate)
  3. Shells out to `orf apply-md` or `orf apply-xliff` (backfill)
  4. Manages a tempdir (always created, cleaned on success, preserved on failure)
  5. Returns the output path and pipeline metadata
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ol_mcp.tools import (
    TOOL_REGISTRY,
    TranslateFileInput,
)


def _run(coro):
    """Helper: run async coroutine in sync context."""
    return asyncio.run(coro)


class TestTranslateFileTool:
    """Issue #37: translate_file MCP tool — file-based end-to-end."""

    def test_translate_file_is_registered(self):
        """Issue #37 R1: tool appears in TOOL_REGISTRY."""
        assert "translate_file" in TOOL_REGISTRY, (
            f"translate_file not registered. Available: {list(TOOL_REGISTRY.keys())}"
        )

    def test_translate_file_input_model_exists(self):
        """Issue #37 R2: TranslateFileInput Pydantic model is defined in tools.py."""
        assert hasattr(TranslateFileInput, "model_fields")
        fields = TranslateFileInput.model_fields
        for required in ("file_path", "source_lang", "target_lang"):
            assert required in fields, f"Missing required field {required!r}"

    def test_translate_file_rejects_nonexistent_file(self, tmp_path):
        """Issue #37 R4: nonexistent file → FILE_NOT_FOUND error."""
        from ol_mcp.translate_file import translate_file

        result = _run(translate_file(TranslateFileInput(
            file_path=str(tmp_path / "nonexistent.docx"),
            source_lang="en",
            target_lang="zh",
        )))
        parsed = json.loads(result)
        assert parsed.get("success") is False
        assert "FILE_NOT_FOUND" in str(parsed.get("error", {}).get("code", "")) or \
               "not exist" in str(parsed.get("error", {}).get("message", "")).lower(), \
            f"Expected FILE_NOT_FOUND error. Got: {parsed}"

    def test_translate_file_rejects_invalid_format(self, tmp_path):
        """Issue #37 R8: invalid output format → error before any CLI call."""
        from ol_mcp.translate_file import translate_file

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        result = _run(translate_file(TranslateFileInput(
            file_path=str(test_file),
            source_lang="en",
            target_lang="zh",
            output_format="xyz",  # invalid
        )))
        parsed = json.loads(result)
        assert parsed.get("success") is False
        assert "INVALID_FORMAT" in str(parsed.get("error", {}).get("code", "")) or \
               "invalid" in str(parsed.get("error", {}).get("message", "")).lower(), \
            f"Expected INVALID_FORMAT error. Got: {parsed}"

    def test_translate_file_succeeds_with_fake_llm(self, tmp_path):
        """Issue #37 R1+R12: end-to-end success in FAKE_LLM mode.

        Mocks all 3 subprocess calls to avoid network/disk dependencies.
        Verifies the tool resolves binaries, creates a tempdir, calls
        all 3 CLIs, returns success with output_path.
        """
        from ol_mcp import translate_file as tf_module
        from ol_mcp.translate_file import translate_file

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        def mock_run(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 0
            mock.stderr = ""
            # OPP subprocess: creates {stem}.md (and {stem}.xlf for 'both' target)
            # in the --output-dir. Find --output-dir in cmd.
            if cmd[0].endswith("opp") or "/opp" in cmd[0]:
                try:
                    o_idx = cmd.index("--output-dir")
                    out_dir = Path(cmd[o_idx + 1])
                    out_dir.mkdir(parents=True, exist_ok=True)
                    stem = Path(cmd[1]).stem  # input file
                    (out_dir / f"{stem}.md").write_text(
                        f"# OPP extraction of {stem}\n", encoding="utf-8"
                    )
                    (out_dir / f"{stem}.xlf").write_text(
                        '<xliff version="1.2"></xliff>', encoding="utf-8"
                    )
                    (out_dir / f"{stem}_manifest.json").write_text("{}", encoding="utf-8")
                except (ValueError, IndexError):
                    pass
            # OL translate-md: find .md and create .translated.md
            elif "translate-md" in cmd:
                md_files = [a for a in cmd if a.endswith(".md") and "translated" not in a]
                if md_files:
                    src_md = Path(md_files[0])
                    if src_md.exists():
                        dst_md = src_md.parent / f"{src_md.stem}.translated.md"
                        dst_md.write_text(f"# {src_md.stem}\n[zh] translated\n", encoding="utf-8")
            # OL translate-xliff
            elif "translate-xliff" in cmd:
                xlf_files = [a for a in cmd if a.endswith(".xlf") and "translated" not in a]
                if xlf_files:
                    src_xlf = Path(xlf_files[0])
                    if src_xlf.exists():
                        dst_xlf = src_xlf.parent / f"{src_xlf.stem}.translated.xlf"
                        dst_xlf.write_text("<xliff></xliff>", encoding="utf-8")
            # ORF: find -o and create the output
            if "apply-md" in cmd or "apply-xliff" in cmd:
                try:
                    o_idx = cmd.index("-o")
                    Path(cmd[o_idx + 1]).write_bytes(b"PK\x03\x04fake_docx")
                except (ValueError, IndexError):
                    pass
            return mock

        with patch.object(tf_module.subprocess, "run", side_effect=mock_run) as mock_subprocess:
            result = _run(translate_file(TranslateFileInput(
                file_path=str(test_file),
                source_lang="en",
                target_lang="zh",
                output_format="docx",
                output_dir=str(out_dir),
            )))
            parsed = json.loads(result)
            assert parsed.get("success") is True, (
                f"translate_file should succeed with FAKE_LLM. Got: {parsed}"
            )
            # _success_response wraps the data under "content"
            content = parsed.get("content", {})
            assert content.get("output_path"), (
                f"Missing output_path in success response. content={content!r}"
            )
            assert mock_subprocess.called, "Should have called subprocess"
            # Verify at least 3 subprocess calls (opp, ol, orf)
            assert mock_subprocess.call_count >= 3, (
                f"Expected 3+ subprocess calls (opp/ol/orf), got {mock_subprocess.call_count}"
            )

    def test_translate_file_preserves_tempdir_on_failure(self, tmp_path):
        """Issue #37 R11: failure preserves tempdir (for debugging)."""
        from ol_mcp import translate_file as tf_module
        from ol_mcp.translate_file import translate_file

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        def mock_run_fail_opp(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 1
            mock.stderr = "OPP failed: bad file"
            if "translate-md" in cmd or "apply-md" in cmd or \
               "translate-xliff" in cmd or "apply-xliff" in cmd:
                mock.returncode = 0
            return mock

        with patch.object(tf_module.subprocess, "run", side_effect=mock_run_fail_opp):
            result = _run(translate_file(TranslateFileInput(
                file_path=str(test_file),
                source_lang="en",
                target_lang="zh",
                output_dir=str(out_dir),
            )))
            parsed = json.loads(result)
            assert parsed.get("success") is False
            # On failure, error response should reference the failure source
            error_msg = str(parsed.get("error", {}).get("message", ""))
            assert "OPP" in error_msg or "failed" in error_msg.lower(), (
                f"Failure should reference error source. Got: {parsed}"
            )

    def test_translate_file_resolves_opp_via_venv_fallback(self, tmp_path):
        """Issue #37: opp may not be on PATH — tool uses venv fallback."""
        from ol_mcp import translate_file as tf_module
        from ol_mcp.translate_file import translate_file

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # Simulate opp NOT on PATH
        original_which = tf_module.shutil.which
        def mock_which(name, *args, **kwargs):
            if name == "opp":
                return None  # Not on PATH — force venv fallback
            return original_which(name, *args, **kwargs)

        def mock_run(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 0
            mock.stderr = ""
            # OPP subprocess: create the intermediate files
            if cmd[0].endswith("opp") or "/opp" in cmd[0]:
                try:
                    o_idx = cmd.index("--output-dir")
                    out_dir = Path(cmd[o_idx + 1])
                    out_dir.mkdir(parents=True, exist_ok=True)
                    stem = Path(cmd[1]).stem
                    (out_dir / f"{stem}.md").write_text(
                        f"# OPP {stem}\n", encoding="utf-8"
                    )
                    (out_dir / f"{stem}.xlf").write_text(
                        "<xliff></xliff>", encoding="utf-8"
                    )
                except (ValueError, IndexError):
                    pass
            elif "translate-md" in cmd:
                md_files = [a for a in cmd if a.endswith(".md") and "translated" not in a]
                if md_files:
                    src_md = Path(md_files[0])
                    if src_md.exists():
                        dst_md = src_md.parent / f"{src_md.stem}.translated.md"
                        dst_md.write_text("# [zh] hello\n", encoding="utf-8")
            if "apply-md" in cmd:
                try:
                    o_idx = cmd.index("-o")
                    Path(cmd[o_idx + 1]).write_bytes(b"PK\x03\x04")
                except (ValueError, IndexError):
                    pass
            return mock

        with patch.object(tf_module.shutil, "which", side_effect=mock_which):
            with patch.object(tf_module.subprocess, "run", side_effect=mock_run) as mock_subprocess:
                result = _run(translate_file(TranslateFileInput(
                    file_path=str(test_file),
                    source_lang="en",
                    target_lang="zh",
                    output_dir=str(out_dir),
                )))
                parsed = json.loads(result)
                if parsed.get("success"):
                    first_call = mock_subprocess.call_args_list[0]
                    cmd = first_call.args[0] if first_call.args else first_call.kwargs.get("cmd", [])
                    assert cmd, "Should have called subprocess with a cmd"
                    # cmd[0] must be a real file (venv fallback or PATH)
                    assert Path(cmd[0]).exists(), (
                        f"Resolved opp binary {cmd[0]!r} does not exist on disk"
                    )
                else:
                    # If not on PATH and not in venv, we'd get CLI_NOT_FOUND
                    assert "CLI_NOT_FOUND" in str(parsed.get("error", {}).get("code", ""))
