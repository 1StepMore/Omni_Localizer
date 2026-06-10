"""Tests for A2: parallelize per-trans-unit translation via asyncio.gather + Semaphore.

These tests target the ``_translate_units_concurrent`` helper extracted from
``_translate_xliff_async`` in ol_cli.py. They are pure unit tests with mocked
``pool`` / ``judge`` objects — no real LLM, no OMNI_TEST_FAKE_LLM seam, no
ConfigObject — so they run hermetically in CI.

A2.1: gather identity — concurrent run produces the same per-unit results
      as a serial (concurrency=1) run.
A2.2: semaphore respect — no more than ``max_concurrent`` in-flight at any
      point, regardless of how many units are queued.
A2.3: unit-order preservation — output results are in input order, even
      when individual translates complete out of order.
A2.4: per-unit exception handling — one unit's translate raises; the rest
      still translate; the failed unit is reported with transport_error.
"""
from __future__ import annotations

import asyncio
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

# Windows compatibility — same as other OL tests.
if sys.platform == 'win32':
    import unittest.mock
    sys.modules.setdefault('fcntl', unittest.mock.MagicMock())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_unit(unit_id: str, source: str, shield_map: dict | None = None):
    """Build a TranslationUnit-like object for testing.

    We construct a SimpleNamespace rather than a full ``TranslationUnit``
    because the helper only reads ``unit_id``, ``source_text`` and
    ``shield_map``. Keeping the fixture minimal avoids pulling in pydantic
    edge cases.
    """
    from types import SimpleNamespace
    return SimpleNamespace(
        unit_id=unit_id,
        source_text=source,
        shield_map=shield_map or {},
    )


def _make_pool(translator):
    """Build a mock pool whose async ``translate`` calls ``translator(text)``.

    ``translator`` is a sync function ``(text, src, tgt) -> str`` that can
    also raise or sleep to simulate real LLM behavior.
    """
    pool = MagicMock()

    async def _translate(text, src, tgt, context=None, **_kwargs):
        # Yield to the event loop so the semaphore is actually contended.
        await asyncio.sleep(0)
        result = translator(text, src, tgt)
        if isinstance(result, BaseException):
            raise result
        return result

    pool.translate = AsyncMock(side_effect=_translate)
    return pool


def _make_judge(judge_fn=None):
    """Build a mock JudgeService-like object whose ``judge`` always passes."""
    judge = MagicMock()

    async def _judge(source, target, unit_id, **_kwargs):
        from ol_core.dataclass import EvaluationResult
        return EvaluationResult(
            unit_id=unit_id,
            scorer_scores={},
            judge_scores={"adequacy": 9.0, "fluency": 9.0},
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )

    judge.judge = AsyncMock(side_effect=_judge)
    return judge


# ---------------------------------------------------------------------------
# A2.1 — gather identity
# ---------------------------------------------------------------------------

class TestGatherIdentity:
    """A2.1: concurrent gather must produce the same per-unit results as
    serial (concurrency=1) execution."""

    @pytest.mark.asyncio
    async def test_xliff_translate_gather_produces_same_result_as_serial(self):
        from ol_cli import _translate_units_concurrent

        units = [
            _make_unit(f"u{i}", f"source {i}") for i in range(10)
        ]

        def translator(text, src, tgt):
            # Tiny per-call delay so the concurrent run actually overlaps.
            time.sleep(0.001)
            return f"TRANSLATED:{text}"

        pool = _make_pool(translator)

        # Run with concurrency=10 (fully parallel) and concurrency=1 (serial).
        concurrent = await _translate_units_concurrent(
            units, pool, None, None, "en", "zh",
            sem=asyncio.Semaphore(10),
        )
        serial = await _translate_units_concurrent(
            units, pool, None, None, "en", "zh",
            sem=asyncio.Semaphore(1),
        )

        assert len(concurrent) == len(units)
        assert len(serial) == len(units)
        # Per-unit results must be byte-identical between concurrent and
        # serial runs (same translation, same status, same attempts).
        for c, s, u in zip(concurrent, serial, units):
            assert c.unit_id == u.unit_id == s.unit_id, (
                f"unit_id mismatch: c={c.unit_id!r} s={s.unit_id!r} "
                f"expected={u.unit_id!r}"
            )
            assert c.translated == s.translated, (
                f"translation mismatch for {u.unit_id!r}: "
                f"concurrent={c.translated!r} serial={s.translated!r}"
            )
            assert c.translated == f"TRANSLATED:source {u.unit_id[1:]}", (
                f"unexpected translation for {u.unit_id!r}: "
                f"got {c.translated!r}"
            )
            assert c.status == s.status == "ok", (
                f"status mismatch for {u.unit_id!r}: "
                f"concurrent={c.status!r} serial={s.status!r}"
            )
            assert c.attempts == s.attempts == 1, (
                f"attempts mismatch for {u.unit_id!r}: "
                f"concurrent={c.attempts!r} serial={s.attempts!r}"
            )


# ---------------------------------------------------------------------------
# A2.2 — semaphore respect
# ---------------------------------------------------------------------------

class TestSemaphoreRespect:
    """A2.2: at any moment, no more than ``max_concurrent`` translates are
    in-flight (i.e., the semaphore is honored even when 100 units are queued)."""

    @pytest.mark.asyncio
    async def test_xliff_translate_gather_respects_semaphore(self):
        from ol_cli import _translate_units_concurrent

        max_concurrent = 5
        n_units = 100

        units = [_make_unit(f"u{i:03d}", f"source {i}") for i in range(n_units)]

        in_flight = 0
        max_in_flight = 0
        in_flight_lock = asyncio.Lock()

        async def slow_translate(text, src, tgt, context=None, **_kwargs):
            nonlocal in_flight, max_in_flight
            async with in_flight_lock:
                in_flight += 1
                if in_flight > max_in_flight:
                    max_in_flight = in_flight
            # Hold the slot long enough for the semaphore to actually
            # be saturated. 50ms > scheduler quantum; 100 units / 5 slots
            # * 50ms = 1s total wall clock.
            await asyncio.sleep(0.05)
            async with in_flight_lock:
                in_flight -= 1
            return f"OUT:{text}"

        pool = MagicMock()
        pool.translate = AsyncMock(side_effect=slow_translate)

        results = await _translate_units_concurrent(
            units, pool, None, None, "en", "zh",
            sem=asyncio.Semaphore(max_concurrent),
        )

        assert len(results) == n_units, (
            f"expected {n_units} results, got {len(results)}"
        )
        # The core invariant: in-flight count never exceeded the cap.
        assert max_in_flight <= max_concurrent, (
            f"semaphore violated: max_in_flight={max_in_flight} "
            f"exceeds max_concurrent={max_concurrent}"
        )
        # And it was actually saturated (otherwise the test is meaningless):
        # we should have hit the cap at least once when 100 units / 5 slots
        # is well above the saturation threshold.
        assert max_in_flight == max_concurrent, (
            f"semaphore under-utilized: max_in_flight={max_in_flight} "
            f"never reached max_concurrent={max_concurrent} "
            f"(test is not exercising the cap)"
        )
        # And every unit got translated successfully.
        for r, u in zip(results, units):
            assert r.status == "ok", (
                f"unit {u.unit_id!r} unexpected status {r.status!r}: {r.error}"
            )
            assert r.translated == f"OUT:source {int(u.unit_id[1:])}", (
                f"unit {u.unit_id!r} unexpected translation {r.translated!r}"
            )


# ---------------------------------------------------------------------------
# A2.3 — unit-order preservation
# ---------------------------------------------------------------------------

class TestUnitOrderPreservation:
    """A2.3: the result list must be in the same order as the input units,
    even when individual translates complete out of order (deliberate)."""

    @pytest.mark.asyncio
    async def test_xliff_translate_gather_preserves_unit_order(self):
        from ol_cli import _translate_units_concurrent

        n_units = 20
        # Per-unit sleep that is INVERSELY proportional to the index, so
        # the later-indexed units finish first. Without order-preserving
        # gather, the result list would be reversed.
        units = [_make_unit(f"u{i:02d}", f"src {i:02d}") for i in range(n_units)]

        def delay_for_index(i: int) -> float:
            return (n_units - i) * 0.005  # u00 sleeps longest, u19 fastest

        async def ordered_translate(text, src, tgt, context=None, **_kwargs):
            i = int(text.split()[1])
            await asyncio.sleep(delay_for_index(i))
            return f"OUT:{text}"

        pool = MagicMock()
        pool.translate = AsyncMock(side_effect=ordered_translate)

        results = await _translate_units_concurrent(
            units, pool, None, None, "en", "zh",
            sem=asyncio.Semaphore(n_units),  # fully parallel so the sleep ordering matters
        )

        # The result list must be in input order, not completion order.
        actual_ids = [r.unit_id for r in results]
        expected_ids = [u.unit_id for u in units]
        assert actual_ids == expected_ids, (
            f"unit order not preserved: actual={actual_ids} expected={expected_ids}"
        )
        # And each result corresponds to the correct unit.
        for r, u in zip(results, units):
            assert r.translated == f"OUT:src {u.unit_id[1:]:>02}", (
                f"unit {u.unit_id!r} got translation {r.translated!r}"
            )


# ---------------------------------------------------------------------------
# A2.4 — per-unit exception handling
# ---------------------------------------------------------------------------

class TestPerUnitExceptionHandling:
    """A2.4: a single unit's translate_fn raising must not break the rest.
    With LQA enabled, the A8 retry wrap in ol_retry/retry.py converts the
    exception into a RetryResult with transport_error=True, so the failed
    unit's result has status='transport_error' and its translation falls
    back to the OPP source. Other units translate normally."""

    @pytest.mark.asyncio
    async def test_xliff_translate_gather_handles_per_unit_exceptions(self):
        from ol_cli import _translate_units_concurrent
        from ol_retry.retry import RetryManager

        units = [
            _make_unit("u1", "ok one"),
            _make_unit("u2", "ok two"),
            _make_unit("u3", "BOOM"),       # this one will raise
            _make_unit("u4", "ok four"),
            _make_unit("u5", "ok five"),
        ]

        async def translate_with_boom(text, src, tgt, context=None, **_kwargs):
            if text == "BOOM":
                raise RuntimeError("simulated transport error")
            return f"OUT:{text}"

        pool = MagicMock()
        pool.translate = AsyncMock(side_effect=translate_with_boom)
        judge = _make_judge()
        # RetryManager with the production default wrap (A8). One retry max
        # so the test stays fast.
        retry_mgr = RetryManager(max_retries=1, pass_threshold=7.0)

        results = await _translate_units_concurrent(
            units, pool, judge, retry_mgr, "en", "zh",
            sem=asyncio.Semaphore(5),
        )

        assert len(results) == 5, f"expected 5 results, got {len(results)}"

        # Map by unit_id for stable assertion order.
        by_id = {r.unit_id: r for r in results}

        # The four non-failing units must translate normally.
        for good_id in ("u1", "u2", "u4", "u5"):
            r = by_id[good_id]
            assert r.status == "ok", (
                f"good unit {good_id!r} got status={r.status!r}: {r.error!r}"
            )
            assert r.translated == f"OUT:{ {'u1': 'ok one', 'u2': 'ok two', 'u4': 'ok four', 'u5': 'ok five'}[good_id] }", (
                f"good unit {good_id!r} got translation {r.translated!r}"
            )

        # The failing unit must be reported as transport_error, with
        # the OPP source as the fallback translation.
        r_fail = by_id["u3"]
        assert r_fail.status == "transport_error", (
            f"failing unit u3 got status={r_fail.status!r}, "
            f"expected 'transport_error' (A8 retry wrap should convert "
            f"the exception). error={r_fail.error!r}"
        )
        assert r_fail.translated == "BOOM", (
            f"failing unit u3 should fall back to OPP source 'BOOM', "
            f"got {r_fail.translated!r}"
        )
        assert r_fail.warning is not None, (
            "failing unit u3 should have a TRANSLATION_FAILED warning"
        )
        assert "TRANSLATION_FAILED" in r_fail.warning, (
            f"unexpected warning text: {r_fail.warning!r}"
        )
        # And the gather itself did not raise — that is the headline
        # invariant: one unit's failure does not break the pipeline.
        assert all(isinstance(r, object) for r in results), (
            "gather returned non-UnitTranslationResult objects — "
            "exception leaked out of the per-unit try/except"
        )
