"""Regression: never cache untranslated ``ol translate-md`` output (Issue #132).

When the LLM failed or was rate-limited, OL wrote the degraded
(source-fallback) output into the content-addressed cache. A later run of the
same input then reported ``Translated (cached)`` and exited ``0`` while serving
the untranslated source. These tests pin two guards:

* a run that produced any untranslated unit must not write the cache;
* a cache entry whose frontmatter records ``untranslated_units > 0`` is a miss,
  so an already-poisoned entry is re-translated instead of reused.

A normal, fully-translated run must still write and hit the cache, and
``--no-cache`` must keep forcing a fresh translation.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

import pytest
from typer.testing import CliRunner

from cli.translate_md import _MdText
from ol_cli import app

runner = CliRunner()


@pytest.fixture
def fake_cache_dir(tmp_path, monkeypatch):
    cache_root = tmp_path / "omni_cache"
    monkeypatch.setenv("OMNI_CACHE_DIR", str(cache_root))
    yield cache_root


@pytest.fixture
def sample_md(tmp_path):
    f = tmp_path / "in.md"
    f.write_text("# Title\n\nHello world.\n", encoding="utf-8")
    return f


def _frontmatter_output(untranslated_units: int, body: str) -> str:
    fm = (
        "---\n"
        "source_lang: en\n"
        "target_lang: zh\n"
    )
    if untranslated_units > 0:
        fm += f"untranslated_units: {untranslated_units}\n"
    fm += "---\n"
    return fm + body


def _make_fake(call_counter, untranslated_units, total_units, body):
    async def fake_translate_md_async(
        input_path, output_path, config_path, src_lang, tgt_lang,
        add_frontmatter=True, glossary=None, restoration_enabled=True,
        glossary_max_terms=5, styleguide=None, polish=False,
        scorer_type="none", pool=None, **kwargs,
    ):
        call_counter["n"] += 1
        output_path.mkdir(parents=True, exist_ok=True)
        output_file = output_path / input_path.name
        output_file.write_text(
            _frontmatter_output(untranslated_units, body), encoding="utf-8",
        )
        result = _MdText(str(output_file))
        result.untranslated_units = untranslated_units
        result.total_units = total_units
        return result

    return fake_translate_md_async


def _run(sample_md, out_dir, fake, extra=()):
    with patch("cli.translate_md._translate_md_async", side_effect=fake):
        return runner.invoke(
            app,
            ["translate-md", str(sample_md), "-s", "en", "-t", "zh",
             "-o", str(out_dir), "--no-restoration", *extra],
        )


def _cache_entries(cache_dir: Path) -> list[Path]:
    root = cache_dir / "ol"
    if not root.exists():
        return []
    return [p for p in root.iterdir() if p.is_file()]


def _seed_poisoned_entry(sample_md, cache_dir, untranslated_units=1):
    from cli.cache import _cache_key, _cache_root

    key = _cache_key(
        sample_md, None, add_frontmatter=True, no_restoration=True,
        no_glossary=False, glossary=None, glossary_max_terms=5,
        src_lang="en", tgt_lang="zh", styleguide=None,
        no_styleguide=False, polish=False,
    )
    cache_file = _cache_root() / f"{key}.md"
    cache_file.write_text(
        _frontmatter_output(untranslated_units, "UNTRANSLATED SOURCE ECHO\n"),
        encoding="utf-8",
    )
    return cache_file


def test_all_untranslated_run_writes_no_cache(fake_cache_dir, sample_md, tmp_path):
    counter = {"n": 0}
    fake = _make_fake(counter, untranslated_units=2, total_units=2,
                      body="source fallback\n")

    rc = _run(sample_md, tmp_path / "out", fake)

    assert rc.exit_code != 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert _cache_entries(fake_cache_dir) == [], (
        f"untranslated run must not write the cache, found "
        f"{_cache_entries(fake_cache_dir)}"
    )


def test_poisoned_cache_entry_is_treated_as_miss(fake_cache_dir, sample_md, tmp_path):
    _seed_poisoned_entry(sample_md, fake_cache_dir, untranslated_units=1)
    assert len(_cache_entries(fake_cache_dir)) == 1

    counter = {"n": 0}
    fake = _make_fake(counter, untranslated_units=0, total_units=2,
                      body="FRESH TRANSLATION\n")

    rc = _run(sample_md, tmp_path / "out", fake)

    assert rc.exit_code == 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert counter["n"] == 1, "poisoned cache hit must re-run the pipeline"
    assert "cached" not in rc.output.lower(), rc.output
    produced = (tmp_path / "out" / sample_md.name).read_text(encoding="utf-8")
    assert "FRESH TRANSLATION" in produced


def test_clean_run_writes_and_hits_cache(fake_cache_dir, sample_md, tmp_path):
    counter = {"n": 0}
    fake = _make_fake(counter, untranslated_units=0, total_units=2,
                      body="CLEAN TRANSLATION\n")

    rc1 = _run(sample_md, tmp_path / "out1", fake)
    assert rc1.exit_code == 0, f"rc={rc1.exit_code} output={rc1.output!r}"
    assert counter["n"] == 1
    assert len(_cache_entries(fake_cache_dir)) == 1, "clean run must write cache"

    counter["n"] = 0
    rc2 = _run(sample_md, tmp_path / "out2", fake)
    assert rc2.exit_code == 0, f"rc={rc2.exit_code} output={rc2.output!r}"
    assert counter["n"] == 0, "second clean run should be a cache hit"
    assert "cached" in rc2.output.lower(), rc2.output


def test_no_cache_still_forces_fresh_translation(fake_cache_dir, sample_md, tmp_path):
    counter = {"n": 0}
    fake = _make_fake(counter, untranslated_units=0, total_units=2,
                      body="CLEAN TRANSLATION\n")

    rc1 = _run(sample_md, tmp_path / "out1", fake, extra=("--no-cache",))
    assert rc1.exit_code == 0, f"rc={rc1.exit_code} output={rc1.output!r}"
    assert counter["n"] == 1
    assert _cache_entries(fake_cache_dir) == [], "--no-cache must not write cache"

    rc2 = _run(sample_md, tmp_path / "out2", fake, extra=("--no-cache",))
    assert rc2.exit_code == 0, f"rc={rc2.exit_code} output={rc2.output!r}"
    assert counter["n"] == 2, "--no-cache must always re-run the pipeline"
    assert "cached" not in rc2.output.lower(), rc2.output
