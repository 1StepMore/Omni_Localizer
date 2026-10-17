"""Regression: untranslated units must be visible on stdout and exit code.

``ol translate-md`` used to report untranslated (source-fallback) units only on
stderr, while stdout printed the same ``Translated: ...`` success line and the
process exited ``0``. A caller that reads only stdout or only the exit code
treated a fully failed translation as success. These tests pin the new
contract:

* stdout always carries ``[untranslated: a/b]``;
* ``untranslated == total > 0`` exits non-zero;
* partial untranslated still exits ``0``;
* ``--fail-on-untranslated`` keeps its "any untranslated is fatal" semantics.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

from typer.testing import CliRunner

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _fake_async(untranslated_units: int, total_units: int):
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
        return result

    return fake_translate_md_async


def _invoke(tmp_path, untranslated_units, total_units, extra_args=()):
    from ol_cli import app

    src = tmp_path / "in.md"
    src.write_text("# Title\n\nBody text.\n", encoding="utf-8")

    with patch(
        "cli.translate_md._translate_md_async",
        side_effect=_fake_async(untranslated_units, total_units),
    ):
        return CliRunner().invoke(
            app,
            ["translate-md", str(src), "-s", "en", "-t", "zh",
             "-o", str(tmp_path / "out"), "--no-cache", *extra_args],
        )


def test_all_untranslated_exits_nonzero(tmp_path):
    rc = _invoke(tmp_path, untranslated_units=3, total_units=3)

    assert rc.exit_code != 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert "[untranslated: 3/3]" in rc.output, rc.output


def test_partial_untranslated_exits_zero_and_reports_count(tmp_path):
    rc = _invoke(tmp_path, untranslated_units=2, total_units=6)

    assert rc.exit_code == 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert "[untranslated: 2/6]" in rc.output, rc.output


def test_fully_translated_exits_zero_and_reports_zero(tmp_path):
    rc = _invoke(tmp_path, untranslated_units=0, total_units=6)

    assert rc.exit_code == 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert "[untranslated: 0/6]" in rc.output, rc.output


def test_fail_on_untranslated_partial_exits_nonzero(tmp_path):
    rc = _invoke(
        tmp_path, untranslated_units=2, total_units=6,
        extra_args=("--fail-on-untranslated",),
    )

    assert rc.exit_code != 0, f"rc={rc.exit_code} output={rc.output!r}"


def test_stdout_keeps_original_summary_prefix(tmp_path):
    rc = _invoke(tmp_path, untranslated_units=2, total_units=6)

    assert "Translated: in.md ->" in rc.output, rc.output
    assert "(en -> zh) [untranslated: 2/6]" in rc.output, rc.output
