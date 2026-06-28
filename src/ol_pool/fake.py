"""FAKE_LLM seam — synchronous, in-process fake ModelPool.

Provides just enough surface for the OL CLI's translate and judge
call sites to run without real LLM I/O. ``translate`` returns the
source text (echo) prefixed with the target language code so a
caller can assert the result was actually processed. ``judge``
returns a fixed high-score response so the LQA pass_threshold
is satisfied.
"""

from __future__ import annotations

from typing import Any


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
