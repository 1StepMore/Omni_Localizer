"""Issue #189: retry SOURCE_COPY units + fail-closed on exhausted retries.

Two behaviors are pinned here:

1. ``_translate_one_unit`` re-asks the model when it returns the source text
   verbatim. The retry must bypass the content-addressed cache (non-zero
   ``temperature``) and carry a harder retranslation instruction. If a later
   attempt yields a real translation, the unit is no longer ``untranslated``.
2. If every attempt echoes the source, the unit stays ``untranslated`` and the
   CLI fails closed: non-zero exit code **and** the partial output file is
   deleted, unless ``--allow-untranslated`` is passed.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

import pytest
from typer.testing import CliRunner

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ol_core.dataclass import TranslationUnit


class _SequencePool:
    """Returns canned outputs in order; records the kwargs of each call."""

    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls: list[dict] = []

    async def translate(self, text, src, tgt, **kwargs):
        self.calls.append({"text": text, **kwargs})
        return self._outputs.pop(0)


def _unit(unit_id: str, source: str) -> TranslationUnit:
    return TranslationUnit(unit_id=unit_id, source_text=source, shield_map={})


@pytest.mark.asyncio
async def test_source_copy_retry_succeeds_on_second_attempt():
    from cli.translate_md import _translate_one_unit

    pool = _SequencePool(["Hello world", "你好世界"])
    result = await _translate_one_unit(
        _unit("u0", "Hello world"), pool, None, None, "en", "zh",
        sem=asyncio.Semaphore(1), repair_pipeline=MagicMock(),
    )

    assert result.untranslated is False
    assert result.translated == "你好世界"
    assert result.attempts == 2
    # The retry must bypass the cache and carry the harder instruction.
    assert len(pool.calls) == 2
    assert pool.calls[1]["temperature"] != 0.0
    assert pool.calls[1]["extra_instruction"]


@pytest.mark.asyncio
async def test_source_copy_retry_exhausted_marks_untranslated():
    from cli.translate_md import _translate_one_unit

    pool = _SequencePool(["Hello world", "Hello world", "Hello world"])
    result = await _translate_one_unit(
        _unit("u0", "Hello world"), pool, None, None, "en", "zh",
        sem=asyncio.Semaphore(1), repair_pipeline=MagicMock(),
    )

    assert result.untranslated is True
    assert result.translated == "Hello world"
    assert result.attempts == 3
    assert result.warning is not None
    assert "SOURCE_COPY after 3 attempt(s)" in result.warning


def _fake_async(untranslated_units: int, total_units: int, unit_ids: list[str]):
    from cli.translate_md import _MdText

    async def fake_translate_md_async(
        input_path, output_path, config_path, src_lang, tgt_lang,
        add_frontmatter=True, glossary=None, restoration_enabled=True,
        glossary_max_terms=5, styleguide=None, polish=False,
        scorer_type="none", pool=None, **kwargs,
    ):
        output_path.mkdir(parents=True, exist_ok=True)
        output_file = output_path / input_path.name
        output_file.write_text("translated body\n", encoding="utf-8")
        result = _MdText(str(output_file))
        result.untranslated_units = untranslated_units
        result.total_units = total_units
        result.untranslated_unit_ids = unit_ids
        return result

    return fake_translate_md_async


def _invoke(tmp_path, extra_args=()):
    from ol_cli import app

    src = tmp_path / "in.md"
    src.write_text("# Title\n\nBody text.\n", encoding="utf-8")

    with patch(
        "cli.translate_md._translate_md_async",
        side_effect=_fake_async(1, 2, ["u0"]),
    ):
        return CliRunner().invoke(
            app,
            ["translate-md", str(src), "-s", "en", "-t", "zh",
             "-o", str(tmp_path / "out"), "--no-cache", *extra_args],
        )


def test_exhausted_source_copy_fails_closed_and_deletes_output(tmp_path):
    rc = _invoke(tmp_path)

    assert rc.exit_code != 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert not (tmp_path / "out" / "in.md").exists(), (
        "fail-closed must delete the partial output file"
    )
    assert "u0" in rc.output, rc.output


def test_allow_untranslated_keeps_output(tmp_path):
    rc = _invoke(tmp_path, extra_args=("--allow-untranslated",))

    assert rc.exit_code == 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert (tmp_path / "out" / "in.md").exists()
