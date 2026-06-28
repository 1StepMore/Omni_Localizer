"""FAKE_LLM seam fixture for OL CLI tests.

Provides a synchronous, in-process fake ModelPool that the OL CLI uses
when ``OMNI_TEST_FAKE_LLM=1`` is set. The real LLM call is short-circuited;
the ``_apply_fake_llm_seam`` helper additionally stubs ``span_aligner``
so the MD repair pipeline (level 2) can run without hitting Hugging Face.

The actual implementations of these helpers live in
``src/ol_cli.py`` (``_apply_fake_llm_seam`` is a free function there) and
``ol_pool/fake.py`` (``_FakeModelPool`` class).
This module re-exports the same symbols under the names that
``ol_cli.py:_translate_md_async`` and ``_translate_xliff_async``
import when the seam is active, plus a thin ``_FakeModelPool`` class
that satisfies the same duck-typed surface as the real ``ModelPool``
(``translate``/``judge`` async methods, ``_cache_enabled``,
``_test_mode`` attributes).
"""
from __future__ import annotations

from src.ol_cli import _apply_fake_llm_seam  # noqa: F401  (re-export)
from ol_pool.fake import _FakeModelPool  # noqa: F401  (re-export from production code)
