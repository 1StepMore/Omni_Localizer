"""FAKE_LLM seam fixture for OL CLI tests.

Provides a synchronous, in-process fake ModelPool that the OL CLI uses
when ``OMNI_TEST_FAKE_LLM=1`` is set. The real LLM call is short-circuited;
the ``_apply_fake_llm_seam`` helper additionally stubs ``span_aligner``
so the MD repair pipeline (level 2) can run without hitting Hugging Face.

The actual implementations of these helpers live in
``src/ol_cli.py`` (``_apply_fake_llm_seam`` is a free function there).
This module re-exports the same symbols under the names that
``ol_cli.py:_translate_md_async`` and ``_translate_xliff_async``
import when the seam is active, plus a thin ``_FakeModelPool`` class
that satisfies the same duck-typed surface as the real ``ModelPool``
(``translate``/``judge`` async methods, ``_cache_enabled``,
``_test_mode`` attributes).
"""
from __future__ import annotations

from typing import Any

from src.ol_cli import _apply_fake_llm_seam  # noqa: F401  (re-export)


class _FakeModelPool:
    """Synchronous, in-process stand-in for ``ModelPool``.

    Provides just enough surface for the OL CLI's translate and judge
    call sites to run without real LLM I/O. ``translate`` returns the
    source text (echo) prefixed with the target language code so a
    caller can assert the result was actually processed. ``judge``
    returns a fixed high-score response so the LQA pass_threshold
    is satisfied.
    """

    def __init__(self) -> None:
        self._cache_enabled = False
        self._test_mode = True
        self._call_count = 0

    async def translate(
        self,
        source: str,
        source_lang: str = "",
        target_lang: str = "",
        **kwargs: Any,
    ) -> str:
        self._call_count += 1
        return f"[{target_lang}] {source}"

    async def judge(
        self,
        source: str,
        target: str,
        unit_id: str = "",
        source_lang: str = "",
        target_lang: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "accuracy": 9.0,
            "fluency": 9.0,
            "adequacy": 9.0,
            "terminology_consistency": 9.0,
            "format_preserved": True,
            "score": 9.0,
        }

    def reset(self) -> None:
        self._call_count = 0
