"""Regression: the cache key must include the LLM mode (Issue #135).

A run under the ``OMNI_TEST_FAKE_LLM=1`` test seam produces *fake* output that
is not a real translation, yet ``ol translate-md`` wrote it into the shared
content-addressed cache. Because the key mixed input + config + behavioural
flags but not the LLM mode, a later **real** run of the same input hit that
entry, printed ``Translated (cached)``, never called the model, and shipped
the untranslated source. The #132 guard (``untranslated_units > 0``) cannot
catch this: a fake artifact need not carry that field.

These tests pin the fix: the LLM mode (``fake`` vs ``real``) is part of the
cache key, so fake and real runs can never hit each other's entries.
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

_SEED_BODY = "FAKE MODE SEED ECHO\n"


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


def _cache_key_for(sample_md, *, fake: bool) -> str:
    from cli.cache import _cache_key

    assert os.environ.get("OMNI_TEST_FAKE_LLM") == ("1" if fake else None), (
        "env must be set before computing the key"
    )
    return _cache_key(
        sample_md, None, add_frontmatter=True, no_restoration=True,
        no_glossary=False, glossary=None, glossary_max_terms=5,
        src_lang="en", tgt_lang="zh", styleguide=None,
        no_styleguide=False, polish=False,
    )


def _seed_entry(sample_md, *, fake: bool, body: str = _SEED_BODY) -> Path:
    """Write a cache entry under the key of the requested LLM mode."""
    from cli.cache import _cache_root

    key = _cache_key_for(sample_md, fake=fake)
    cache_file = _cache_root() / f"{key}.md"
    cache_file.write_text(
        _frontmatter_output(0, body), encoding="utf-8",
    )
    return cache_file


def _enter_fake_mode(monkeypatch):
    monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
    monkeypatch.delenv("OMNI_RUN_REAL_LLM", raising=False)


def _enter_real_mode(monkeypatch):
    monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
    # In real mode the CLI fail-closes on the API-key pre-check; this only
    # skips that pre-check (the pipeline is patched below anyway).
    monkeypatch.setenv("OMNI_RUN_REAL_LLM", "1")


def test_cache_key_differs_between_fake_and_real_mode(sample_md, monkeypatch):
    _enter_real_mode(monkeypatch)
    real = _cache_key_for(sample_md, fake=False)
    real_again = _cache_key_for(sample_md, fake=False)

    _enter_fake_mode(monkeypatch)
    fake = _cache_key_for(sample_md, fake=True)
    fake_again = _cache_key_for(sample_md, fake=True)

    assert real != fake, "fake and real mode must not share a cache key"
    assert real == real_again, "key must be stable within real mode"
    assert fake == fake_again, "key must be stable within fake mode"


def test_fake_seeded_entry_is_not_hit_by_real_run(
    fake_cache_dir, sample_md, tmp_path, monkeypatch
):
    # Seed under the FAKE-mode key...
    _enter_fake_mode(monkeypatch)
    _seed_entry(sample_md, fake=True)
    assert len(_cache_entries(fake_cache_dir)) == 1

    # ...then run for real (fake seam unset).
    _enter_real_mode(monkeypatch)
    counter = {"n": 0}
    fake = _make_fake(counter, untranslated_units=0, total_units=2,
                      body="FRESH TRANSLATION\n")

    rc = _run(sample_md, tmp_path / "out", fake)

    assert rc.exit_code == 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert counter["n"] == 1, "fake cache entry must not satisfy a real run"
    assert "cached" not in rc.output.lower(), rc.output
    produced = (tmp_path / "out" / sample_md.name).read_text(encoding="utf-8")
    assert "FRESH TRANSLATION" in produced
    assert _SEED_BODY not in produced


def test_real_seeded_entry_is_not_hit_by_fake_run(
    fake_cache_dir, sample_md, tmp_path, monkeypatch
):
    # Seed under the REAL-mode key...
    _enter_real_mode(monkeypatch)
    _seed_entry(sample_md, fake=False)
    assert len(_cache_entries(fake_cache_dir)) == 1

    # ...then run under the fake seam.
    _enter_fake_mode(monkeypatch)
    counter = {"n": 0}
    fake = _make_fake(counter, untranslated_units=0, total_units=2,
                      body="FRESH TRANSLATION\n")

    rc = _run(sample_md, tmp_path / "out", fake)

    assert rc.exit_code == 0, f"rc={rc.exit_code} output={rc.output!r}"
    assert counter["n"] == 1, "real cache entry must not satisfy a fake run"
    assert "cached" not in rc.output.lower(), rc.output
    produced = (tmp_path / "out" / sample_md.name).read_text(encoding="utf-8")
    assert "FRESH TRANSLATION" in produced
    assert _SEED_BODY not in produced
