"""E2E-74 regression tests.

The bug: ``ModelPool.translate()`` raised ``UnboundLocalError`` when
``context=None`` (or ``context=dict``) and ``AttributeError`` when
``context`` was a non-empty ``str`` (the inner ``if context:`` branch
tried to call ``context.get(...)`` on a string).

These tests pin the fix: ``translate()`` must always assign ``prompt``
and return a string for any of the supported ``context`` types.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

import pytest

from ol_pool.router import ModelPool


_CONFIG_PATH = str(
    Path(__file__).resolve().parents[1] / "config" / "default.yaml"
)


@pytest.fixture
def pool():
    from ol_pool import router as router_module
    router_module._pool_cache.clear()
    return ModelPool(_CONFIG_PATH)


class TestTranslateContextTypes:
    """Pin the four valid ``context`` shapes from the public signature."""

    def test_context_none_returns_string(self, pool):
        """E2E-74: ``context=None`` (the CLI default) must not raise."""
        result = asyncio.run(
            pool.translate("Hello world", "en", "zh", context=None)
        )
        assert isinstance(result, str)
        assert result

    def test_context_str_uses_prompt_verbatim(self, pool):
        """A pre-built prompt string (e.g. from ``build_translate_prompt``)
        must be used as the user message content. The previous code
        overwrote it with a fresh build, silently discarding the injected
        TM/glossary section.
        """
        from ol_terminology.rag_injector import build_translate_prompt

        pre_built = build_translate_prompt(
            text="Hello world",
            src_lang="en",
            tgt_lang="zh",
            tm_matches=None,
            glossary_terms=[
                {"term": "world", "translation": "世界", "confidence": 0.9},
            ],
        )
        result = asyncio.run(
            pool.translate("Hello world", "en", "zh", context=pre_built)
        )
        assert isinstance(result, str)
        assert result

    def test_context_str_does_not_call_get_on_string(self, pool):
        """The previous code did ``context.get("tm_matches", [])`` on a
        string, which raised ``AttributeError``. Pin that this branch
        no longer touches ``.get``.
        """
        result = asyncio.run(
            pool.translate("Hello", "en", "zh", context="some pre-built prompt")
        )
        assert isinstance(result, str)

    def test_context_dict_returns_string(self, pool):
        """E2E-74: ``context=dict`` (matches the type hint) must not raise."""
        result = asyncio.run(
            pool.translate(
                "Hello world",
                "en",
                "zh",
                context={"tm_matches": [], "glossary_terms": []},
            )
        )
        assert isinstance(result, str)

    def test_context_dict_with_tm_and_glossary(self, pool):
        result = asyncio.run(
            pool.translate(
                "Hello world",
                "en",
                "zh",
                context={
                    "tm_matches": [
                        {"source": "Hello", "target": "你好", "score": 0.9},
                    ],
                    "glossary_terms": [
                        {"source": "world", "target": "世界", "confidence": 0.9},
                    ],
                },
            )
        )
        assert isinstance(result, str)

    def test_context_empty_string_falls_through_to_default(self, pool):
        """Empty-string context should behave like ``None`` (default prompt)."""
        result = asyncio.run(pool.translate("Hello", "en", "zh", context=""))
        assert isinstance(result, str)


class TestTranslateContextUnbound:
    """The original failure modes pinned as regression guards."""

    def test_no_unbound_local_error_on_none(self, pool):
        try:
            asyncio.run(pool.translate("Hello", "en", "zh", context=None))
        except UnboundLocalError as exc:  # pragma: no cover - regression guard
            pytest.fail(
                f"E2E-74 regressed: UnboundLocalError on context=None: {exc}"
            )

    def test_no_unbound_local_error_on_dict(self, pool):
        try:
            asyncio.run(
                pool.translate(
                    "Hello",
                    "en",
                    "zh",
                    context={"tm_matches": [], "glossary_terms": []},
                )
            )
        except UnboundLocalError as exc:  # pragma: no cover - regression guard
            pytest.fail(
                f"E2E-74 regressed: UnboundLocalError on context=dict: {exc}"
            )

    def test_no_attribute_error_on_str(self, pool):
        try:
            asyncio.run(
                pool.translate("Hello", "en", "zh", context="any string")
            )
        except AttributeError as exc:  # pragma: no cover - regression guard
            pytest.fail(
                f"E2E-74 regressed: AttributeError on context=str (str has no .get): {exc}"
            )
