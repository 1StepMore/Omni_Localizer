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
            "format_preservation": 9.0,
            "score": 9.0,
            "format_errors": [],
        }

    async def profile(
        self,
        content: str,
        source_lang: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return a deterministic placeholder StyleGuide dict.

        Mirrors the shape of :class:`ol_style.schema.StyleGuide.to_dict()`.
        Used by ``ol_style.doc_profiler`` tests in FAKE_LLM mode.

        Real ``ModelPool`` will route this through a "profiling" role
        group in the litellm Router. The fake seam just returns a
        predictable dict so the call chain can be exercised without
        network access.
        """
        self._call_count += 1
        return {
            "tone": "neutral",
            "register": "general",
            "target_audience": "general readers",
            "key_conventions": [
                "Use clear, concise language",
                "Preserve technical terms verbatim when first introduced",
            ],
            "vocabulary": [],
            "avoid": ["obscure jargon", "ambiguous pronouns"],
            "summary": "Auto-generated profile (FAKE_LLM seam).",
            "_source_lang": source_lang,
            "_content_length": len(content),
        }

    def reset(self) -> None:
        self._call_count = 0
