"""Deferred A9.2 + A10.1-A10.3 specific tests.

These tests were originally deferred because the
``tests.test_e2e_pipeline_fixtures`` (FAKE_LLM seam) was broken.
With that seam now restored, the deferred tests can land.

A10.1 + A10.2: l2_applied: bool is returned by both ol_md and ol_xliff
   level2_span_align functions.
A9.2: _translate_md_async with OMNI_TEST_FAKE_LLM=1 (seam active)
   completes without raising; tests the OL-7 outer try/except wrap.
A10.3: WARNING log level is emitted when L2 span_aligner fails.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Activate the FAKE_LLM seam BEFORE any ol_cli imports.
os.environ["OMNI_TEST_FAKE_LLM"] = "1"

# Ensure suite root is on sys.path so the seam's relative import works.
_suite_root = Path(__file__).resolve().parents[2]
if str(_suite_root) not in sys.path:
    sys.path.insert(0, str(_suite_root))

import pytest

from ol_md.repair.level2 import level2_span_align as md_level2
from ol_xliff.repair.level2 import level2_span_align as xliff_level2


# ============================================================
# A10.1: l2_applied: bool returned from ol_md level2
# ============================================================
class TestMdL2ReturnsL2AppliedFlag:
    def test_md_l2_returns_l2_applied_flag(self):
        text, l2_applied = md_level2("Hello world", {}, "Hello world")
        assert isinstance(l2_applied, bool), (
            f"l2_applied must be bool, got {type(l2_applied).__name__}"
        )

    def test_md_l2_returns_l2_applied_false_when_no_projector(self):
        # Patch the module so _has_span_aligner is False.
        with patch("ol_md.repair.level2._has_span_aligner", False):
            text, l2_applied = md_level2("Hello world", {}, "Hello world")
            assert l2_applied is False
            assert text == "Hello world"

    def test_md_l2_text_returned_unchanged_in_no_projector_path(self):
        # Even with placeholder-rich text, the no-projector branch
        # returns the input text verbatim.
        text = "Some {{_OL_XTAG_1_}} placeholder text."
        with patch("ol_md.repair.level2._has_span_aligner", False):
            out, l2_applied = md_level2(text, {}, text)
            assert l2_applied is False
            assert out == text


# ============================================================
# A10.2: l2_applied: bool returned from ol_xliff level2
# ============================================================
class TestXliffL2ReturnsL2AppliedFlag:
    def test_xliff_l2_returns_l2_applied_flag(self):
        text, l2_applied = xliff_level2("Hello world", {}, "Hello world")
        assert isinstance(l2_applied, bool)

    def test_xliff_l2_returns_l2_applied_false_when_no_projector(self):
        with patch("ol_xliff.repair.level2._has_span_aligner", False):
            text, l2_applied = xliff_level2("Hello world", {}, "Hello world")
            assert l2_applied is False
            assert text == "Hello world"

    def test_xliff_l2_handles_math_and_code_placeholders(self):
        text = "See {{_OL_CODE_1_}} and {{_OL_MATH_2_}} for details."
        with patch("ol_xliff.repair.level2._has_span_aligner", False):
            out, l2_applied = xliff_level2(text, {}, text)
            assert l2_applied is False
            assert out == text


# ============================================================
# A10.3: WARNING log level emitted when L2 fails
# ============================================================
class TestL2LogsWarning:
    def test_md_l2_logs_warning_on_projector_failure(self, caplog):
        # Force _has_span_aligner=True so the code tries the projector.
        # Then make the projector raise so the except branch logs WARNING.
        with patch("ol_md.repair.level2._has_span_aligner", True), \
             patch("ol_md.repair.level2.SpanProjector") as MockProj:
            MockProj.side_effect = RuntimeError("simulated HF load failure")
            with caplog.at_level(logging.WARNING, logger="ol_md.repair.level2"):
                text, l2_applied = md_level2("Hello", {}, "Hello")
            assert l2_applied is False
            assert any(
                rec.levelno == logging.WARNING
                and "span_aligner unavailable" in rec.message
                for rec in caplog.records
            ), f"no WARNING log emitted; got: {[r.message for r in caplog.records]}"

    def test_xliff_l2_logs_warning_on_projector_failure(self, caplog):
        with patch("ol_xliff.repair.level2._has_span_aligner", True), \
             patch("ol_xliff.repair.level2.SpanProjector") as MockProj:
            MockProj.side_effect = RuntimeError("simulated HF load failure")
            with caplog.at_level(logging.WARNING, logger="ol_xliff.repair.level2"):
                text, l2_applied = xliff_level2("Hello", {}, "Hello")
            assert l2_applied is False
            assert any(
                rec.levelno == logging.WARNING
                and "span_aligner unavailable" in rec.message
                for rec in caplog.records
            )


# ============================================================
# A9.2: _translate_md_async with FAKE_LLM seam completes without raising
# ============================================================
class TestTranslateMdAsyncWithFakeLlm:
    @pytest.mark.asyncio
    async def test_translate_md_async_with_fake_llm_completes(self, tmp_path):
        """A9 verification: with the FAKE_LLM seam active,
        _translate_md_async returns a string and writes output without
        raising — the OL-7 outer try/except wrap is in place."""
        from ol_cli import _translate_md_async

        input_path = tmp_path / "in.md"
        input_path.write_text("# Title\n\nSome content.\n", encoding="utf-8")
        # _translate_md_async treats output_path as a DIRECTORY and
        # writes the translated file inside it.
        output_dir = tmp_path / "out_dir"
        output_dir.mkdir()

        result = await _translate_md_async(
            input_path, output_dir, None, "zh", "en"
        )
        assert isinstance(result, str), (
            f"_translate_md_async must return a string under FAKE_LLM seam; "
            f"got {type(result).__name__}"
        )
        output_file = output_dir / input_path.name
        assert output_file.exists(), f"output file not created at {output_file}"
        assert output_file.read_text(encoding="utf-8"), "output file is empty"
