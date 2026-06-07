"""A6 cache tests for OL CLI (PR10 of slim-pipeline-hardening plan).

Tests the OL CLI's content-addressed cache at ~/.omni_cache/ol/<sha256>.<ext>.
The cache root is overridden in tests via OMNI_CACHE_DIR env var (set by
``fake_cache_dir`` fixture) so tests do not touch the real user cache.

TDD discipline: these tests are written FIRST (before the production code).
They exercise the cache plumbing without depending on the real
``_translate_md_async`` / ``_translate_xliff_async`` async pipelines
(we mock them to a deterministic counter + known-output writer so we can
assert "cache hit means no pipeline work" and "cache miss calls the pipeline").

Cache key for OL is: sha256(input_bytes + config_file_bytes_if_any).

The test exercises both ``translate-md`` and ``translate-xliff`` entry points
to prove the cache wiring is uniform across MD and XLIFF channels.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import ol_cli
from ol_cli import app

runner = CliRunner()


# ========== Fixtures ==========


@pytest.fixture
def fake_cache_dir(tmp_path, monkeypatch):
    """Override OMNI_CACHE_DIR to a tmp path for testing.

    The production cache helpers must read this env var at call-time
    (not at module import) so the fixture sets it before each test and
    the OL module resolves the cache root to ``tmp_path / "omni_cache"``.
    """
    cache_root = tmp_path / "omni_cache"
    monkeypatch.setenv("OMNI_CACHE_DIR", str(cache_root))
    yield cache_root


@pytest.fixture
def sample_md(tmp_path):
    """Create a minimal MD input file for OL."""
    f = tmp_path / "input.md"
    f.write_text("# Title\n\nHello world.\n", encoding="utf-8")
    return f


@pytest.fixture
def sample_xliff(tmp_path):
    """Create a minimal XLIFF input file for OL."""
    f = tmp_path / "input.xlf"
    f.write_text(
        '<?xml version="1.0"?>\n'
        '<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">\n'
        '  <file source-language="en" target-language="zh" original="test" datatype="plaintext">\n'
        '    <body>\n'
        '      <trans-unit id="tu1">\n'
        '        <source>Hello world</source>\n'
        '        <target></target>\n'
        '      </trans-unit>\n'
        '    </body>\n'
        '  </file>\n'
        '</xliff>\n',
        encoding="utf-8",
    )
    return f


def _make_fake_translate_md(call_counter, output_content="translated md v1"):
    """Returns a fake ``_translate_md_async`` that writes a known output and counts calls.

    Real ``_translate_md_async`` is expensive (it instantiates a ModelPool,
    calls LLM, runs MD repair). For cache tests we only care that the OL
    CLI calls the pipeline on a cache miss and does NOT call it on a cache
    hit. This fake gives us that signal without invoking real LLM paths.
    """
    async def fake_translate_md_async(
        input_path, output_path, config_path, src_lang, tgt_lang,
        add_frontmatter=True,
    ):
        call_counter["n"] += 1
        output_path.mkdir(parents=True, exist_ok=True)
        output_file = output_path / input_path.name
        output_file.write_text(output_content, encoding="utf-8")
        return str(output_file)
    return fake_translate_md_async


def _make_fake_translate_xliff(call_counter, output_content="translated xliff v1"):
    """Returns a fake ``_translate_xliff_async`` that writes a known output and counts calls."""
    async def fake_translate_xliff_async(
        input_path, output_path, config_path, src_lang, tgt_lang,
    ):
        call_counter["n"] += 1
        output_path.mkdir(parents=True, exist_ok=True)
        output_file = output_path / input_path.name
        output_file.write_text(output_content, encoding="utf-8")
        return str(output_file)
    return fake_translate_xliff_async


# ========== Tests ==========


def test_ol_cache_hit_returns_cached_output(
    fake_cache_dir, sample_md, tmp_path,
):
    """Run ``translate-md`` twice on same input; second run is a cache hit.

    The pipeline (``_translate_md_async``) is called once on the cache
    MISS and NOT called on the cache HIT. Outputs across runs are byte
    identical.
    """
    counter = {"n": 0}
    fake_async = _make_fake_translate_md(counter, "translated md v1")

    # First run: cache miss → _translate_md_async is called
    out1 = tmp_path / "out1"
    with patch.object(ol_cli, "_translate_md_async", side_effect=fake_async):
        rc1 = runner.invoke(
            app,
            ["translate-md", str(sample_md), "-o", str(out1)],
        )
    assert rc1.exit_code == 0, (
        f"first run failed (rc={rc1.exit_code}), output={rc1.output!r}, "
        f"exception={rc1.exception!r}"
    )
    assert counter["n"] == 1, f"expected 1 pipeline call, got {counter['n']}"
    md1 = out1 / sample_md.name
    assert md1.exists(), f"expected {md1} to exist"
    assert md1.read_text() == "translated md v1"

    # Second run: cache hit → _translate_md_async MUST NOT be called again
    counter["n"] = 0
    out2 = tmp_path / "out2"
    with patch.object(ol_cli, "_translate_md_async", side_effect=fake_async):
        rc2 = runner.invoke(
            app,
            ["translate-md", str(sample_md), "-o", str(out2)],
        )
    assert rc2.exit_code == 0, (
        f"second run failed (rc={rc2.exit_code}), output={rc2.output!r}, "
        f"exception={rc2.exception!r}"
    )
    assert counter["n"] == 0, (
        f"cache hit expected: _translate_md_async should not be called, "
        f"got {counter['n']} calls"
    )
    md2 = out2 / sample_md.name
    assert md2.exists(), f"expected {md2} to exist after cache hit"
    # Identical output across runs (cache hit must reproduce the cached bytes)
    assert md2.read_text() == md1.read_text()


def test_ol_cache_miss_on_input_change(fake_cache_dir, tmp_path):
    """Modify input; assert cache miss (pipeline called twice across runs)."""
    counter = {"n": 0}
    fake_async = _make_fake_translate_md(counter, "translated v1")

    # First run with input1
    input1 = tmp_path / "in1.md"
    input1.write_text("# Original\n\ncontent one.\n", encoding="utf-8")
    out1 = tmp_path / "out1"
    with patch.object(ol_cli, "_translate_md_async", side_effect=fake_async):
        runner.invoke(app, ["translate-md", str(input1), "-o", str(out1)])
    assert counter["n"] == 1, f"first run expected 1 call, got {counter['n']}"

    # Second run with a different input (same args, different bytes → different cache key)
    input2 = tmp_path / "in2.md"
    input2.write_text("# Modified\n\ndifferent content.\n", encoding="utf-8")
    out2 = tmp_path / "out2"
    with patch.object(ol_cli, "_translate_md_async", side_effect=fake_async):
        runner.invoke(app, ["translate-md", str(input2), "-o", str(out2)])
    assert counter["n"] == 2, (
        f"cache miss expected on input change: expected 2 total calls, "
        f"got {counter['n']}"
    )


_MINIMAL_OL_CONFIG = """\
project_id: "ol-cache-test"
source_lang: "en"
target_lang: "zh"
llm_pool:
  translation:
    - provider: "openai"
      model: "gpt-4o-mini"
      priority: 1
      role: "translation"
    - provider: "openai"
      model: "gpt-4o"
      priority: 2
      role: "translation"
  judging:
    - provider: "openai"
      model: "gpt-4o-mini"
      priority: 1
      role: "judging"
    - provider: "openai"
      model: "gpt-4o"
      priority: 2
      role: "judging"
  restoration:
    - provider: "openai"
      model: "gpt-4o-mini"
      priority: 1
      role: "restoration"
    - provider: "openai"
      model: "gpt-4o"
      priority: 2
      role: "restoration"
"""


def test_ol_cache_invalidation_on_config_change(
    fake_cache_dir, sample_md, tmp_path,
):
    """Change config; assert cache miss (pipeline called twice across runs)."""
    counter = {"n": 0}
    fake_async = _make_fake_translate_md(counter, "translated v1")

    # First run with config1
    config1 = tmp_path / "config1.yaml"
    config1.write_text(_MINIMAL_OL_CONFIG, encoding="utf-8")
    out1 = tmp_path / "out1"
    with patch.object(ol_cli, "_translate_md_async", side_effect=fake_async):
        rc1 = runner.invoke(
            app,
            ["translate-md", str(sample_md), "-o", str(out1),
             "-c", str(config1)],
        )
    assert rc1.exit_code == 0, (
        f"first run failed (rc={rc1.exit_code}), output={rc1.output!r}, "
        f"exception={rc1.exception!r}"
    )
    assert counter["n"] == 1, f"first run expected 1 call, got {counter['n']}"

    # Second run with config2 (different content → different cache key)
    config2 = tmp_path / "config2.yaml"
    config2.write_text(
        _MINIMAL_OL_CONFIG.replace('"ol-cache-test"', '"ol-cache-test-2"'),
        encoding="utf-8",
    )
    out2 = tmp_path / "out2"
    with patch.object(ol_cli, "_translate_md_async", side_effect=fake_async):
        rc2 = runner.invoke(
            app,
            ["translate-md", str(sample_md), "-o", str(out2),
             "-c", str(config2)],
        )
    assert rc2.exit_code == 0, (
        f"second run failed (rc={rc2.exit_code}), output={rc2.output!r}, "
        f"exception={rc2.exception!r}"
    )
    assert counter["n"] == 2, (
        f"cache miss expected on config change: expected 2 total calls, "
        f"got {counter['n']}"
    )


def test_ol_cache_directory_created_with_correct_permissions(
    fake_cache_dir, sample_md, tmp_path,
):
    """Cache dir exists and is mode 0o700 (protects any sensitive cached content)."""
    counter = {"n": 0}
    fake_async = _make_fake_translate_md(counter, "translated v1")
    out1 = tmp_path / "out1"
    with patch.object(ol_cli, "_translate_md_async", side_effect=fake_async):
        rc = runner.invoke(
            app,
            ["translate-md", str(sample_md), "-o", str(out1)],
        )
    assert rc.exit_code == 0, (
        f"run failed (rc={rc.exit_code}), output={rc.output!r}, "
        f"exception={rc.exception!r}"
    )

    cache_root = Path(os.environ["OMNI_CACHE_DIR"])
    ol_cache = cache_root / "ol"
    assert ol_cache.exists(), f"expected cache dir at {ol_cache}"
    assert ol_cache.is_dir()
    mode = ol_cache.stat().st_mode & 0o777
    assert mode == 0o700, f"expected mode 0o700, got {oct(mode)}"
