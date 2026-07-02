"""T2.5 unit tests for styleguide in cache key.

Tests the ``_cache_key`` function in ``cli.cache`` to verify that
adding a StyleGuide path or the --no-styleguide flag changes the
cache key, so cached outputs from prior runs don't pollute new runs.
"""
import os
from pathlib import Path

import pytest

from cli.cache import _cache_key


@pytest.fixture
def sample_xliff(tmp_path):
    """Create a minimal XLIFF input file for cache tests."""
    f = tmp_path / "input.xlf"
    f.write_text(
        '<?xml version="1.0"?>\n'
        '<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">\n'
        '  <file source-language="en" target-language="zh" original="t" datatype="plaintext">\n'
        '    <body><trans-unit id="t1"><source>hi</source><target></target></trans-unit></body>\n'
        '  </file>\n</xliff>\n',
        encoding="utf-8",
    )
    return f


class TestStyleGuideCacheKey:
    def test_cache_key_differs_with_styleguide_path(self, sample_xliff, tmp_path):
        sg1 = tmp_path / "sg1.json"
        sg1.write_text('{"tone":"formal","register":"technical"}')
        sg2 = tmp_path / "sg2.json"
        sg2.write_text('{"tone":"casual","register":"general"}')
        k1 = _cache_key(sample_xliff, None, styleguide=str(sg1))
        k2 = _cache_key(sample_xliff, None, styleguide=str(sg2))
        assert k1 != k2, "Different styleguide paths must produce different cache keys"

    def test_cache_key_same_with_both_none(self, sample_xliff):
        k1 = _cache_key(sample_xliff, None, styleguide=None, no_styleguide=False)
        k2 = _cache_key(sample_xliff, None, styleguide=None, no_styleguide=False)
        assert k1 == k2, "Same params (styleguide=None, no_styleguide=False) must produce same key"

    def test_cache_key_differs_with_no_styleguide_flag(self, sample_xliff):
        k1 = _cache_key(sample_xliff, None, no_styleguide=False)
        k2 = _cache_key(sample_xliff, None, no_styleguide=True)
        assert k1 != k2, "no_styleguide=True vs False must produce different cache keys"

    def test_cache_key_differs_with_styleguide_vs_no_styleguide(self, sample_xliff, tmp_path):
        sg = tmp_path / "sg.json"
        sg.write_text('{"tone":"formal"}')
        k_with = _cache_key(sample_xliff, None, styleguide=str(sg), no_styleguide=False)
        k_without = _cache_key(sample_xliff, None, styleguide=None, no_styleguide=True)
        assert k_with != k_without

    def test_cache_key_unchanged_when_styleguide_empty_string(self, sample_xliff):
        k1 = _cache_key(sample_xliff, None, styleguide=None)
        k2 = _cache_key(sample_xliff, None, styleguide="")
        assert k1 == k2, "Empty-string styleguide should be treated like None"

    def test_cache_key_includes_no_styleguide_when_set(self, sample_xliff):
        k_default = _cache_key(sample_xliff, None)
        k_no_styleguide = _cache_key(sample_xliff, None, no_styleguide=True)
        assert k_default != k_no_styleguide
