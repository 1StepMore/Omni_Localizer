"""Regression: MD translation must report source-fallback (untranslated) units.

``ol translate-md`` used to substitute the OPP source text at five fallback
sites and exit 0, so a partially-translated document shipped as if it were a
translation and the document-level Gate 5 call could not see it. These tests
pin the per-unit ``untranslated`` flag and the warning that carries it.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

import pytest
from typer.testing import CliRunner

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ol_core.dataclass import TranslationUnit


def _unit(unit_id: str, source: str) -> TranslationUnit:
    return TranslationUnit(unit_id=unit_id, source_text=source, shield_map={})


def _pool(failing=(), translator=None):
    def _default(text: str) -> str:
        return f"TRANSLATED:{text}"

    translate = translator or _default

    async def _translate(text, src, tgt, context=None, **_kwargs):
        if text in failing:
            raise RuntimeError(f"provider 429 for {text!r}")
        return translate(text)

    pool = MagicMock()
    pool.translate = AsyncMock(side_effect=_translate)
    return pool


@pytest.mark.asyncio
async def test_raising_unit_reports_untranslated_and_keeps_source():
    from cli.translate_md import _translate_one_unit

    unit = _unit("u0", "Hello world")
    result = await _translate_one_unit(
        unit, _pool(failing={"Hello world"}), None, None, "en", "zh",
        sem=asyncio.Semaphore(1), repair_pipeline=MagicMock(),
    )

    assert result.untranslated is True
    assert result.translated == "Hello world"


@pytest.mark.asyncio
async def test_translated_unit_reports_not_untranslated():
    from cli.translate_md import _translate_one_unit

    unit = _unit("u1", "Hello world")
    result = await _translate_one_unit(
        unit, _pool(), None, None, "en", "zh",
        sem=asyncio.Semaphore(1), repair_pipeline=MagicMock(),
    )

    assert result.untranslated is False
    assert result.translated == "TRANSLATED:Hello world"


@pytest.mark.asyncio
async def test_failed_unit_warning_mentions_source_copy():
    from cli.translate_md import _translate_one_unit

    unit = _unit("u0", "Hello world")
    result = await _translate_one_unit(
        unit, _pool(failing={"Hello world"}), None, None, "en", "zh",
        sem=asyncio.Semaphore(1), repair_pipeline=MagicMock(),
    )

    assert result.warning is not None
    assert "SOURCE_COPY" in result.warning


@pytest.mark.asyncio
async def test_all_clean_document_has_zero_untranslated_units():
    from cli.translate_md import _translate_md_units_concurrent

    md = "# Title\n\nHello world\n\nGoodbye world\n"
    rebuilt = await _translate_md_units_concurrent(
        md, _pool(), None, None, "en", "zh",
        asyncio.Semaphore(3), None,
    )

    assert rebuilt.total_units >= 1
    assert rebuilt.untranslated_units == 0


@pytest.mark.asyncio
async def test_one_failing_unit_is_counted_at_document_level():
    from cli.translate_md import _translate_md_units_concurrent

    md = "# Title\n\nHello world\n\nGoodbye world\n"
    rebuilt = await _translate_md_units_concurrent(
        md, _pool(failing={"Title"}), None, None, "en", "zh",
        asyncio.Semaphore(3), None,
    )

    assert rebuilt.total_units >= 2
    assert rebuilt.untranslated_units >= 1


def _runner_and_fake(untranslated_units: int):
    from cli.translate_md import _MdText
    from ol_cli import app

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
        # One more unit than untranslated keeps these cases *partial*
        # (0 < untranslated < total) so ``--allow-untranslated`` keeps exit 0;
        # the fail-closed default and the all-untranslated → non-zero rule are
        # covered by tests/test_e2e_133_untranslated_visible.py.
        result.total_units = untranslated_units + 1
        return result

    return CliRunner(), app, fake_translate_md_async


def test_json_payload_reports_untranslated_units(tmp_path):
    runner, app, fake = _runner_and_fake(2)
    src = tmp_path / "in.md"
    src.write_text("# Title\n\nBody text.\n", encoding="utf-8")

    with patch("cli.translate_md._translate_md_async", side_effect=fake):
        rc = runner.invoke(
            app,
            ["translate-md", str(src), "-s", "en", "-t", "zh",
             "-o", str(tmp_path / "out"), "--json", "--no-cache",
             "--allow-untranslated"],
        )

    assert rc.exit_code == 0, f"rc={rc.exit_code} output={rc.output!r}"
    payload = None
    for line in reversed(rc.output.strip().splitlines()):
        if line.strip().startswith("{"):
            payload = json.loads(line)
            break
    assert payload is not None, f"no JSON payload in output: {rc.output!r}"
    assert payload["untranslated_units"] == 2


def test_fail_on_untranslated_flag_exits_pipeline_error(tmp_path):
    runner, app, fake = _runner_and_fake(1)
    src = tmp_path / "in.md"
    src.write_text("# Title\n\nBody text.\n", encoding="utf-8")

    with patch("cli.translate_md._translate_md_async", side_effect=fake):
        rc = runner.invoke(
            app,
            ["translate-md", str(src), "-s", "en", "-t", "zh",
             "-o", str(tmp_path / "out"), "--fail-on-untranslated", "--no-cache"],
        )

    assert rc.exit_code == 1, f"rc={rc.exit_code} output={rc.output!r}"


def test_allow_untranslated_flag_stays_success(tmp_path):
    runner, app, fake = _runner_and_fake(1)
    src = tmp_path / "in.md"
    src.write_text("# Title\n\nBody text.\n", encoding="utf-8")

    with patch("cli.translate_md._translate_md_async", side_effect=fake):
        rc = runner.invoke(
            app,
            ["translate-md", str(src), "-s", "en", "-t", "zh",
             "-o", str(tmp_path / "out"), "--no-cache",
             "--allow-untranslated"],
        )

    assert rc.exit_code == 0, f"rc={rc.exit_code} output={rc.output!r}"


def test_default_fails_closed_and_removes_output(tmp_path):
    runner, app, fake = _runner_and_fake(1)
    src = tmp_path / "in.md"
    src.write_text("# Title\n\nBody text.\n", encoding="utf-8")

    with patch("cli.translate_md._translate_md_async", side_effect=fake):
        rc = runner.invoke(
            app,
            ["translate-md", str(src), "-s", "en", "-t", "zh",
             "-o", str(tmp_path / "out"), "--no-cache"],
        )

    assert rc.exit_code != 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert not (tmp_path / "out" / "in.md").exists(), (
        "fail-closed must remove the partial output"
    )


@pytest.mark.asyncio
async def test_serial_path_flags_untranslated_units(tmp_path, monkeypatch):
    """max_md_concurrent=1 uses the same per-unit path as the concurrent mode.

    OL#199: the old serial path translated the whole document as one
    ``md_main`` unit, so a JSON-derived MD (mostly a fenced JSON block) was
    echoed back as "source copy" even when the fence had nothing to
    translate. Both modes now count only real translatable units.
    """
    from types import SimpleNamespace

    import importlib

    tmd = importlib.import_module("cli.translate_md")
    from ol_pool import fake as fake_mod

    async def _boom(self, *args, **kwargs):
        raise RuntimeError("provider 429 rate-limited")

    monkeypatch.setattr(fake_mod._FakeModelPool, "translate", _boom)
    monkeypatch.setattr(tmd, "resolve_config_path", lambda cfg: tmp_path / "c.yaml")
    monkeypatch.setattr(
        "ol_config.loader.load_config",
        lambda cfg: (
            SimpleNamespace(
                source_lang="en", target_lang="zh", max_md_concurrent=1,
                enable_lqa=False, max_input_size_mb=50,
            ),
            {},
        ),
    )

    src = tmp_path / "in.md"
    src.write_text("# Title\n\nUse `pip install foo` now.\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()

    result = await tmd._translate_md_async(src, out, None, "en", "zh")

    # Heading + prose = 2 translatable units; both failed → both counted.
    assert result.total_units == 2
    assert result.untranslated_units == 2


_JSON_MD = (
    "```json\n"
    '{\n  "产品": [\n    {\n      "名称": "阿尔法"\n    }\n  ]\n}\n'
    "```\n\n"
    "json_field:产品.0.名称 = 阿尔法\n"
)


@pytest.mark.asyncio
async def test_code_block_only_document_has_no_untranslated_units():
    """A pure fenced code block is non-translatable → 0 units, not a failure.

    OL#199: the serial path used to send the whole JSON-derived MD to the
    LLM and flag the unchanged echo as an untranslated ``md_main`` unit.
    """
    from cli.translate_md import _translate_md_units_concurrent

    md = "```json\n{\n  \"产品\": 100\n}\n```\n"
    pool = _pool()
    rebuilt = await _translate_md_units_concurrent(
        md, pool, None, None, "zh", "en", asyncio.Semaphore(1), None,
    )

    assert rebuilt.total_units == 0
    assert rebuilt.untranslated_units == 0
    assert rebuilt.strip() == md.strip()
    pool.translate.assert_not_awaited()


@pytest.mark.asyncio
async def test_json_field_path_is_preserved_and_only_value_translated():
    """Only the json_field value goes to the LLM; the ORF anchor is verbatim."""
    from cli.translate_md import _translate_md_units_concurrent

    seen: list[str] = []

    def translator(text: str) -> str:
        seen.append(text)
        return "Alpha"

    rebuilt = await _translate_md_units_concurrent(
        _JSON_MD, _pool(translator=translator), None, None,
        "zh", "en", asyncio.Semaphore(1), None,
    )

    assert seen == ["阿尔法"], "the json_field prefix must not reach the LLM"
    assert "json_field:产品.0.名称 = Alpha" in rebuilt
    assert rebuilt.untranslated_units == 0
    assert rebuilt.total_units == 1


@pytest.mark.asyncio
async def test_json_field_untranslatable_value_is_not_counted():
    """A path with CJK but an identifier value is not an untranslated unit.

    The value ``ABC-123`` has no source-script character, so a model that
    correctly leaves it alone must not trip SOURCE_COPY on the Chinese path.
    """
    from cli.translate_md import _translate_md_units_concurrent

    md = (
        "```json\n{\n  \"产品\": [{\"型号\": \"ABC-123\"}]\n}\n```\n\n"
        "json_field:产品.0.型号 = ABC-123\n"
    )
    rebuilt = await _translate_md_units_concurrent(
        md, _pool(translator=lambda text: text), None, None,
        "zh", "en", asyncio.Semaphore(1), None,
    )

    assert "json_field:产品.0.型号 = ABC-123" in rebuilt
    assert rebuilt.untranslated_units == 0


@pytest.mark.asyncio
async def test_echoing_llm_still_fails_closed_on_json_values():
    """Reverse evidence: an echo stub still produces untranslated units."""
    from cli.translate_md import _translate_md_units_concurrent

    rebuilt = await _translate_md_units_concurrent(
        _JSON_MD, _pool(translator=lambda text: text), None, None,
        "zh", "en", asyncio.Semaphore(1), None,
    )

    assert rebuilt.untranslated_units == 1
    assert rebuilt.total_units == 1
    assert "json_field:产品.0.名称 = 阿尔法" in rebuilt


_SERIAL_POOL = {
    role: [
        {
            "provider": "openai",
            "model": f"{role}-a",
            "priority": 1,
            "role": role,
            "api_key": "test-key",
            "base_url": "https://example.invalid/v1",
        },
        {
            "provider": "openai",
            "model": f"{role}-b",
            "priority": 2,
            "role": role,
            "api_key": "test-key",
            "base_url": "https://example.invalid/v1",
        },
    ]
    for role in ("translation", "judging", "restoration")
}


def test_echoing_llm_cli_still_exits_nonzero(tmp_path, monkeypatch):
    """Reverse evidence: end-to-end echo stub ⇒ fail-closed exit + no output."""
    import yaml
    from typer.testing import CliRunner

    from ol_cli import app
    from ol_pool import fake as fake_mod

    async def _echo(self, source, *args, **kwargs):
        return source

    monkeypatch.setattr(fake_mod._FakeModelPool, "translate", _echo)
    monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "project_id": "ol199-reverse",
        "source_lang": "zh",
        "target_lang": "en",
        "llm_pool": _SERIAL_POOL,
        "max_md_concurrent": 1,
        "enable_lqa": False,
    }), encoding="utf-8")

    src = tmp_path / "source.md"
    src.write_text(_JSON_MD, encoding="utf-8")
    out = tmp_path / "out"

    result = CliRunner().invoke(
        app,
        ["translate-md", str(src), "-s", "zh", "-t", "en",
         "-o", str(out), "-c", str(cfg_path), "--no-cache"],
    )

    assert result.exit_code != 0, result.output
    assert "untranslated" in result.output.lower()
    assert not (out / "source.md").exists()
