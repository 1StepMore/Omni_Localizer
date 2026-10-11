"""Regression: a failed trans-unit must not read an unbound/stale translation.

`src/cli/translate_xliff.py` builds its final results in a loop over units with
three branches:

  * ``first_pass_translate_excs[i] is not None`` -> TRANSLATION_FAILED
  * ``first_pass_judge_excs[i] is not None``     -> LQA_SKIPPED
  * else                                          -> happy path

Only the happy path ever assigned ``final_translation``, but the repair stage
below the branch chain reads ``final_translation`` unconditionally
(``restore_tags(final_translation, ...)`` / ``repaired = final_translation``).
The two failure branches assigned a *different* local, ``translated``, which is
never read anywhere in that loop.

Two failure modes follow:

1. First unit fails -> ``final_translation`` was never assigned at all, so the
   repair stage raises
   ``UnboundLocalError: cannot access local variable 'final_translation'``
   and the whole pipeline dies instead of degrading to a per-unit fallback.
   This is the crash seen in the 2026-10-06..11 nightly runs:
   ``Pipeline error: cannot access local variable 'final_translation'``.

2. A later unit fails while an earlier one succeeded -> ``final_translation``
   still holds the *previous* unit's translation, so the failed unit silently
   receives the wrong text. That is silent data corruption: no exception, a
   wrong translation in the output XLIFF.

These tests pin both: the failed unit must fall back to its own source text and
must never inherit a sibling unit's translation.
"""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Windows compatibility — same as the other OL tests.
if sys.platform == "win32":
    import unittest.mock

    sys.modules.setdefault("fcntl", unittest.mock.MagicMock())


def _make_unit(unit_id: str, source: str, shield_map: dict | None = None):
    """TranslationUnit-like object, mirroring tests/test_lqa_pipelining.py."""
    return SimpleNamespace(
        unit_id=unit_id,
        source_text=source,
        shield_map=shield_map or {},
    )


def _pool(translations: dict[str, str], failing: set[str]):
    """Pool whose translate() returns per-unit text, or raises for `failing`."""

    async def _translate(text, src, tgt, context=None, **_kwargs):
        if text in failing:
            raise RuntimeError(f"provider 429 for {text!r}")
        return translations[text]

    pool = MagicMock()
    pool.translate = AsyncMock(side_effect=_translate)
    return pool


def _judge_returning_high():
    async def _judge(source, target, unit_id, **_kwargs):
        return SimpleNamespace(judge_overall_score=9.0)

    judge = MagicMock()
    judge.judge = AsyncMock(side_effect=_judge)
    return judge


def _retry_mgr(threshold: float = 7.0):
    retry_mgr = MagicMock()
    retry_mgr._pass_threshold = threshold
    return retry_mgr


class TestFailedUnitTranslationBinding:
    """The repair stage must read a value every branch assigns."""

    @pytest.mark.asyncio
    async def test_all_units_failing_degrades_instead_of_raising(self):
        """Mode 1: first unit fails -> no UnboundLocalError, no pipeline death."""
        from ol_cli import _translate_xliff_pipelined

        units = [_make_unit(f"u{i}", f"src{i}") for i in range(3)]
        pool = _pool({}, failing={f"src{i}" for i in range(3)})

        results = await _translate_xliff_pipelined(
            units, pool, _judge_returning_high(), _retry_mgr(), "en", "zh",
            sem=asyncio.Semaphore(2),
        )

        assert len(results) == 3
        for r in results:
            assert r.status == "transport_error", (
                f"{r.unit_id!r}: expected transport_error, got {r.status!r}"
            )
            assert "TRANSLATION_FAILED" in (r.warning or ""), (
                f"{r.unit_id!r}: missing TRANSLATION_FAILED warning, "
                f"got {r.warning!r}"
            )

    @pytest.mark.asyncio
    async def test_failed_unit_does_not_inherit_sibling_translation(self):
        """Mode 2: silent corruption — u1 must not receive u0's translation."""
        from ol_cli import _translate_xliff_pipelined

        units = [
            _make_unit("u0", "src0"),
            _make_unit("u1", "src1"),
        ]
        pool = _pool(
            {"src0": "OUT:src0"},
            failing={"src1"},
        )

        results = await _translate_xliff_pipelined(
            units, pool, _judge_returning_high(), _retry_mgr(), "en", "zh",
            sem=asyncio.Semaphore(2),
        )

        by_id = {r.unit_id: r for r in results}
        assert by_id["u1"].status == "transport_error"

        # The whole point: u1's fallback is ITS OWN source, never u0's output.
        assert by_id["u1"].translated != "OUT:src0", (
            "u1 inherited u0's translation — silent cross-unit corruption"
        )
        assert by_id["u1"].translated == "src1", (
            f"u1 should fall back to its own source text, got "
            f"{by_id['u1'].translated!r}"
        )
        assert by_id["u0"].translated == "OUT:src0", (
            "u0's own translation must be untouched"
        )

    @pytest.mark.asyncio
    async def test_judge_failure_also_binds_its_own_translation(self):
        """LQA_SKIPPED branch must bind too — it had the same dead-variable bug."""
        from ol_cli import _translate_xliff_pipelined

        units = [_make_unit(f"u{i}", f"src{i}") for i in range(2)]
        pool = _pool({f"src{i}": f"OUT:src{i}" for i in range(2)}, failing=set())

        async def _judge(source, target, unit_id, **_kwargs):
            if unit_id == "u1":
                raise RuntimeError("judge provider 429")
            return SimpleNamespace(judge_overall_score=9.0)

        judge = MagicMock()
        judge.judge = AsyncMock(side_effect=_judge)

        results = await _translate_xliff_pipelined(
            units, pool, judge, _retry_mgr(), "en", "zh",
            sem=asyncio.Semaphore(2),
        )

        by_id = {r.unit_id: r for r in results}
        assert by_id["u1"].status == "ok"
        assert "LQA_SKIPPED" in (by_id["u1"].warning or ""), (
            f"expected LQA_SKIPPED, got {by_id['u1'].warning!r}"
        )
        assert by_id["u1"].translated == "OUT:src1", (
            f"u1 must keep its own translation, got "
            f"{by_id['u1'].translated!r}"
        )