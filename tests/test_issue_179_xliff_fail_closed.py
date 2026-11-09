"""Regression: translate-xliff must fail closed when no unit was translated (OL#179)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

from typer.testing import CliRunner

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_FIXTURE = Path(__file__).parent / "fixtures" / "sample-xliff2.xlf"


def _fake_async(untranslated_units: int, total_units: int):
    from cli.translate_xliff import _XliffText

    async def fake_translate_xliff_async(
        input_path, output_path, config_path, src_lang, tgt_lang,
        glossary=None, styleguide=None, polish=False, **kwargs,
    ):
        output_path.mkdir(parents=True, exist_ok=True)
        output_file = output_path / input_path.name
        output_file.write_bytes(input_path.read_bytes())
        result = _XliffText(str(output_file))
        result.untranslated_units = untranslated_units
        result.total_units = total_units
        return result

    return fake_translate_xliff_async


def _invoke(tmp_path, untranslated_units: int, total_units: int, extra_args=()):
    from ol_cli import app

    src = tmp_path / "sample.xlf"
    src.write_bytes(_FIXTURE.read_bytes())

    with patch(
        "cli.translate_xliff._translate_xliff_async",
        side_effect=_fake_async(untranslated_units, total_units),
    ):
        return CliRunner().invoke(
            app,
            ["translate-xliff", str(src), "-s", "en", "-t", "zh",
             "-o", str(tmp_path / "out"), "--no-cache", "--no-restoration",
             *extra_args],
        )


def test_all_untranslated_exits_nonzero_without_success_line(tmp_path):
    rc = _invoke(tmp_path, untranslated_units=6, total_units=6)

    assert rc.exit_code == 1, f"rc={rc.exit_code} stdout={rc.stdout!r} stderr={rc.stderr!r}"
    assert "Translated:" not in rc.stdout, rc.stdout
    assert "all 6 unit(s) were returned untranslated" in rc.stderr, rc.stderr
    assert not (tmp_path / "out" / "sample.xlf").exists(), (
        "fail-closed must remove the untranslated output"
    )


def test_all_untranslated_json_reports_failure(tmp_path):
    rc = _invoke(tmp_path, untranslated_units=6, total_units=6, extra_args=("--json",))

    assert rc.exit_code == 1, f"rc={rc.exit_code} stdout={rc.stdout!r} stderr={rc.stderr!r}"
    assert '"success": false' in rc.stdout, rc.stdout
    assert '"untranslated_units": 6' in rc.stdout, rc.stdout


def test_partial_untranslated_exits_zero_and_reports_count(tmp_path):
    rc = _invoke(tmp_path, untranslated_units=2, total_units=6)

    assert rc.exit_code == 0, f"rc={rc.exit_code} stdout={rc.stdout!r} stderr={rc.stderr!r}"
    assert "[untranslated: 2/6]" in rc.stdout, rc.stdout
    assert "WARNING: 2 of 6 unit(s)" in rc.stderr, rc.stderr
    assert (tmp_path / "out" / "sample.xlf").exists()


def test_fully_translated_exits_zero_without_warning(tmp_path):
    rc = _invoke(tmp_path, untranslated_units=0, total_units=6)

    assert rc.exit_code == 0, f"rc={rc.exit_code} stdout={rc.stdout!r} stderr={rc.stderr!r}"
    assert "[untranslated: 0/6]" in rc.stdout, rc.stdout
    assert "WARNING:" not in rc.stderr, rc.stderr


def test_async_counts_untranslated_from_unit_results(tmp_path):
    from cli.translate_md import _UnitTranslationResult
    from cli.translate_xliff import _translate_xliff_async

    src = tmp_path / "sample.xlf"
    src.write_bytes(_FIXTURE.read_bytes())
    (tmp_path / "out").mkdir()
    results = [
        _UnitTranslationResult(
            unit_id=str(i),
            translated="" if i % 2 else f"translated {i}",
            untranslated=bool(i % 2),
        )
        for i in range(1, 7)
    ]

    async def fake_concurrent(*args, **kwargs):
        return results

    cfg = SimpleNamespace(
        enable_lqa=False, source_lang="en", target_lang="zh",
        max_xliff_concurrent=1, max_input_size_mb=50, project_id="test",
    )
    with (
        patch("ol_config.loader.load_config", return_value=(cfg, {})),
        patch("cli.translate_xliff._translate_units_concurrent",
              side_effect=fake_concurrent),
    ):
        out = asyncio.run(
            _translate_xliff_async(src, tmp_path / "out", None, "en", "zh")
        )

    assert out.total_units == 5
    assert out.untranslated_units == 3