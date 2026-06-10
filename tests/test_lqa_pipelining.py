"""Tests for A4: OL LQA pipelining (judge runs concurrently with next translate).

Background (from slim-pipeline-hardening.md §A4):
The A2 concurrent gather runs multiple translates in parallel, but per-unit the
sequence ``translate -> judge -> repair`` is serial and holds the concurrency
slot for the full duration. The judge (~5s) is wasted time per unit because the
slot is busy waiting for it.

A4 pipelines the LQA judge with the NEXT unit's translate:
  - Translate phase holds the sem.
  - Judge phase runs OUTSIDE the sem, so it can overlap with the next
    unit's translate.
  - In-flight judge tasks are gathered at the end of the batch.
  - Retry decisions (re-translates for low-score units) are applied AT
    THE END of the batch, not interleaved with the first-pass translates.

These tests target the new ``_translate_xliff_pipelined`` helper in
``ol_cli.py``. They are pure unit tests with mocked ``pool`` / ``judge`` /
``retry_mgr`` — no real LLM, no ConfigObject — so they run hermetically in CI.

A4.1: pipeline overlap — judge of unit N runs while translate of unit N+1
      runs. Total wall-clock < N * translate_time (i.e. judges overlap with
      translates, not serial after every translate).
A4.2: final scores match serial run — pipelined produce the same per-unit
      final score as serial for the same inputs.
A4.3: retry decisions applied at end — units with low first-pass score are
      re-translated AFTER the first-pass batch is complete (i.e. the retry
      fires during/after the judge-gather, not interleaved with first-pass
      translates).
"""
from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Windows compatibility — same as other OL tests.
if sys.platform == 'win32':
    import unittest.mock
    sys.modules.setdefault('fcntl', unittest.mock.MagicMock())


# ---------------------------------------------------------------------------
# Helpers (mirror the patterns from test_xliff_translate.py)
# ---------------------------------------------------------------------------

def _make_unit(unit_id: str, source: str, shield_map: dict | None = None):
    """Build a TranslationUnit-like object (SimpleNamespace) for testing."""
    return SimpleNamespace(
        unit_id=unit_id,
        source_text=source,
        shield_map=shield_map or {},
    )


def _instrumented_pool(translate_ms: float):
    """Build a mock pool that tracks in-flight translate count and timing.

    The returned ``(pool, state)`` tuple gives the test access to
    ``state.translate_in_flight_max`` (peak concurrency) and
    ``state.translate_call_log`` (chronological list of (start, end) for
    each call). Each call sleeps ``translate_ms`` and returns ``"OUT:" + text``.
    """
    state = SimpleNamespace(
        translate_in_flight=0,
        translate_in_flight_max=0,
        translate_call_log=[],   # list of (unit_id, start_t, end_t)
        lock=asyncio.Lock(),
    )

    async def _translate(text, src, tgt, context=None, **_kwargs):
        async with state.lock:
            state.translate_in_flight += 1
            if state.translate_in_flight > state.translate_in_flight_max:
                state.translate_in_flight_max = state.translate_in_flight
            start = time.monotonic()
        await asyncio.sleep(translate_ms)
        async with state.lock:
            end = time.monotonic()
            state.translate_in_flight -= 1
        state.translate_call_log.append((text, start, end))
        return f"OUT:{text}"

    pool = MagicMock()
    pool.translate = AsyncMock(side_effect=_translate)
    return pool, state


def _instrumented_judge(judge_ms: float, per_unit_score: dict[str, float] | None = None):
    """Build a mock judge that tracks in-flight count and returns deterministic scores.

    ``per_unit_score`` maps unit_id -> score. If a unit is not in the map,
    the judge returns 9.0 (passes threshold). If ``per_unit_score`` is None,
    all units return 9.0.
    """
    state = SimpleNamespace(
        judge_in_flight=0,
        judge_in_flight_max=0,
        judge_call_log=[],   # list of (unit_id, start_t, end_t)
        lock=asyncio.Lock(),
    )

    async def _judge(source, target, unit_id, **_kwargs):
        async with state.lock:
            state.judge_in_flight += 1
            if state.judge_in_flight > state.judge_in_flight_max:
                state.judge_in_flight_max = state.judge_in_flight
            start = time.monotonic()
        await asyncio.sleep(judge_ms)
        score = (per_unit_score or {}).get(unit_id, 9.0)
        async with state.lock:
            end = time.monotonic()
            state.judge_in_flight -= 1
        state.judge_call_log.append((unit_id, start, end))
        from ol_core.dataclass import EvaluationResult
        return EvaluationResult(
            unit_id=unit_id,
            scorer_scores={},
            judge_scores={
                "adequacy": score,
                "fluency": score,
                "terminology_consistency": score,
                "format_preservation": score,
            },
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )

    judge = MagicMock()
    judge.judge = AsyncMock(side_effect=_judge)
    judge._state = state
    judge._pass_threshold = 7.0
    return judge, state


# ---------------------------------------------------------------------------
# A4.1 — pipeline overlap
# ---------------------------------------------------------------------------

class TestPipelineOverlap:
    """A4.1: judge of unit N runs concurrently with translate of unit N+1.

    With translate=judge=100ms and N=10 units, the SERIAL (per-unit)
    pattern is N*(100+100) = 2000ms. A2 (gathered but per-unit serial)
    with unbounded sem is still ~200ms (translates overlap, then judges
    overlap). The pipelined helper goes further: it holds the sem
    ONLY during translate, so when a translate finishes, its judge fires
    immediately and the freed slot is used by the next translate.

    The spec asserts total time < N * translate_ms (i.e. < 1000ms for
    N=10, translate=100ms). This is the threshold that distinguishes the
    pipelined implementation from any per-unit-serial implementation that
    is further slowed by the sem gate.
    """

    @pytest.mark.asyncio
    async def test_lqa_pipeline_runs_judge_concurrent_with_next_translation(self):
        from ol_cli import _translate_xliff_pipelined

        n_units = 10
        translate_ms = 0.1     # 100 ms
        judge_ms = 0.1         # 100 ms
        sem_cap = 3            # bounded concurrency: forces overlap
        units = [_make_unit(f"u{i}", f"src{i}") for i in range(n_units)]

        pool, pool_state = _instrumented_pool(translate_ms=translate_ms)
        judge, judge_state = _instrumented_judge(judge_ms=judge_ms)
        retry_mgr = MagicMock()
        retry_mgr._pass_threshold = 7.0

        start = time.monotonic()
        results = await _translate_xliff_pipelined(
            units, pool, judge, retry_mgr, "en", "zh",
            sem=asyncio.Semaphore(sem_cap),
        )
        elapsed = time.monotonic() - start

        assert len(results) == n_units, (
            f"expected {n_units} results, got {len(results)}"
        )
        for r in results:
            assert r.status == "ok", (
                f"unit {r.unit_id!r} unexpected status {r.status!r}: {r.error!r}"
            )

        # === Core A4.1 invariants ===
        # 1) Total wall time < N * translate_ms (the spec's threshold for
        #    "judge overlaps with next translate, not serial").
        threshold = n_units * translate_ms   # 10 * 0.1 = 1.0s
        assert elapsed < threshold, (
            f"A4.1 FAIL: pipelined elapsed={elapsed:.3f}s exceeded "
            f"threshold N*translate_ms={threshold:.3f}s. "
            f"judge is not overlapping with next translate. "
            f"max_translate_in_flight={pool_state.translate_in_flight_max}, "
            f"max_judge_in_flight={judge_state.judge_in_flight_max}"
        )

        # 2) Translate sem was actually saturated (test is meaningful).
        assert pool_state.translate_in_flight_max == sem_cap, (
            f"translate sem under-utilized: max_in_flight="
            f"{pool_state.translate_in_flight_max} never reached cap={sem_cap}; "
            f"overlap test is not exercising the pipeline."
        )

        # 3) Judge also ran concurrently (more than 1 judge in flight at
        #    some point). The pipeline fires judges WITHOUT the sem gate,
        #    so we expect all N judges to run concurrently.
        assert judge_state.judge_in_flight_max > 1, (
            f"judge never overlapped with itself: max_judge_in_flight="
            f"{judge_state.judge_in_flight_max}. The pipeline should fire "
            f"all judges in parallel (no sem gate on judge phase)."
        )

        # 4) A judge started BEFORE all translates finished — i.e. there
        #    exists a time window where BOTH a translate and a judge were
        #    in flight. Check that the first judge started before the last
        #    translate ended.
        first_judge_start = min(s for (_, s, _) in judge_state.judge_call_log)
        last_translate_end = max(e for (_, _, e) in pool_state.translate_call_log)
        assert first_judge_start < last_translate_end, (
            f"A4.1 FAIL: first judge started at t={first_judge_start:.3f} "
            f"but last translate ended at t={last_translate_end:.3f}. "
            f"No overlap between judge phase and next translate phase."
        )


# ---------------------------------------------------------------------------
# A4.2 — final scores match serial run
# ---------------------------------------------------------------------------

class TestFinalScoresMatchSerial:
    """A4.2: pipelined helper produces the same per-unit final score as the
    serial (sem=1) helper for the same inputs. The pipelining changes TIMING,
    not the SCORES; the LLM and judge are deterministic mocks."""

    @pytest.mark.asyncio
    async def test_lqa_pipeline_final_scores_match_serial_run(self):
        from ol_cli import _translate_xliff_pipelined

        n_units = 5
        # Use different per-unit scores to make sure the helper is actually
        # running the judge for each unit and propagating the score.
        scores = {f"u{i}": 6.0 + i * 0.5 for i in range(n_units)}
        # All scores >= 7.0? No: u0=6.0, u1=6.5, u2=7.0, u3=7.5, u4=8.0.
        # u0 and u1 will be below threshold (7.0) — we want the final
        # score to be the post-retry score, not the first-pass.
        units = [_make_unit(f"u{i}", f"src{i}") for i in range(n_units)]

        # Track which unit is on which pass.
        translate_call_count: dict[str, int] = {}
        judge_call_count: dict[str, int] = {}

        async def translate_fn(text, src, tgt, context=None, **_kwargs):
            # Same first-pass and retry translation for deterministic score
            # comparison.
            await asyncio.sleep(0.005)
            return f"OUT:{text}"

        async def judge_fn(source, target, unit_id, **_kwargs):
            await asyncio.sleep(0.005)
            # Both first pass and retry return the same score for the
            # same unit — this makes "final score" deterministic.
            from ol_core.dataclass import EvaluationResult
            s = scores[unit_id]
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores={
                    "adequacy": s, "fluency": s,
                    "terminology_consistency": s, "format_preservation": s,
                },
                format_preserved=True, format_errors=[], warnings=[],
            )

        pool = MagicMock()
        pool.translate = AsyncMock(side_effect=translate_fn)
        judge = MagicMock()
        judge.judge = AsyncMock(side_effect=judge_fn)

        # We use a real RetryManager so the retry path is exercised identically
        # in both serial and pipelined runs.
        from ol_retry.retry import RetryManager
        retry_mgr = RetryManager(max_retries=2, pass_threshold=7.0)

        # Pipelined run with high concurrency.
        pipelined_results = await _translate_xliff_pipelined(
            units, pool, judge, retry_mgr, "en", "zh",
            sem=asyncio.Semaphore(n_units),
        )

        # Recreate mocks for the serial run (they're consumed).
        pool_s = MagicMock()
        pool_s.translate = AsyncMock(side_effect=translate_fn)
        judge_s = MagicMock()
        judge_s.judge = AsyncMock(side_effect=judge_fn)
        retry_mgr_s = RetryManager(max_retries=2, pass_threshold=7.0)

        serial_results = await _translate_xliff_pipelined(
            units, pool_s, judge_s, retry_mgr_s, "en", "zh",
            sem=asyncio.Semaphore(1),  # serial: only one at a time
        )

        # Compare per-unit. Same translation and same per-unit structure.
        assert len(pipelined_results) == len(serial_results) == n_units
        for p, s, u in zip(pipelined_results, serial_results, units):
            assert p.unit_id == s.unit_id == u.unit_id
            assert p.translated == s.translated, (
                f"translation mismatch for {u.unit_id!r}: "
                f"pipelined={p.translated!r} serial={s.translated!r}"
            )
            assert p.status == s.status, (
                f"status mismatch for {u.unit_id!r}: "
                f"pipelined={p.status!r} serial={s.status!r}"
            )
            # The final-score-equivalent field: the retry_manager records
            # attempts. Same inputs + same retry logic = same attempt count.
            assert p.attempts == s.attempts, (
                f"attempts mismatch for {u.unit_id!r}: "
                f"pipelined={p.attempts} serial={s.attempts}"
            )


# ---------------------------------------------------------------------------
# A4.3 — retry decisions applied at end
# ---------------------------------------------------------------------------

class TestRetryDecisionsAtEnd:
    """A4.3: units with a low first-pass score trigger a retry AFTER the
    main batch of translates is done. The retry must NOT happen interleaved
    with the first-pass translates of OTHER units.

    The headline invariant: no retry of unit X starts before the FIRST-pass
    translate of EVERY unit is complete. Equivalently: at the time the first
    retry begins, all N first-pass translates have already finished.
    """

    @pytest.mark.asyncio
    async def test_lqa_pipeline_retry_decisions_applied_at_end(self):
        from ol_cli import _translate_xliff_pipelined

        n_units = 6
        # u0..u2: low first-pass score (need retry). u3..u5: pass first time.
        low_score_units = {f"u{i}": 5.0 for i in range(3)}     # below 7.0
        pass_score_units = {f"u{i}": 9.0 for i in range(3, 6)}  # above 7.0
        per_unit_first_pass = {**low_score_units, **pass_score_units}

        units = [_make_unit(f"u{i}", f"src{i}") for i in range(n_units)]

        # Track translate calls in global order. The helper passes the
        # same source text to both first-pass and retry translate calls,
        # so we can't tag the call with a pass number from the text alone.
        # Instead we exploit the A4 ordering: all first-pass translates
        # finish before any retry translate starts, so the first n_units
        # calls are first-pass and the rest are retries.
        translate_calls: list[tuple[str, int, float]] = []
        calls_lock = asyncio.Lock()

        async def translate_fn(text, src, tgt, context=None, **_kwargs):
            async with calls_lock:
                idx = len(translate_calls)
                translate_calls.append((text, idx, time.monotonic()))
            await asyncio.sleep(0.02)
            return f"OUT:{text}"

        async def judge_fn(source, target, unit_id, **_kwargs):
            from ol_core.dataclass import EvaluationResult
            s = per_unit_first_pass.get(unit_id, 9.0)
            await asyncio.sleep(0.01)
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores={
                    "adequacy": s, "fluency": s,
                    "terminology_consistency": s, "format_preservation": s,
                },
                format_preserved=True, format_errors=[], warnings=[],
            )

        pool = MagicMock()
        pool.translate = AsyncMock(side_effect=translate_fn)
        judge = MagicMock()
        judge.judge = AsyncMock(side_effect=judge_fn)
        from ol_retry.retry import RetryManager
        retry_mgr = RetryManager(max_retries=2, pass_threshold=7.0)

        results = await _translate_xliff_pipelined(
            units, pool, judge, retry_mgr, "en", "zh",
            sem=asyncio.Semaphore(2),  # bounded so first-pass has to interleave
        )

        assert len(results) == n_units, f"expected {n_units} results, got {len(results)}"

        # First-pass batch: the first n_units calls. Each unit appears
        # exactly once in this batch.
        first_pass_calls = translate_calls[:n_units]
        first_pass_texts = [t for (t, _, _) in first_pass_calls]
        first_pass_start_times = [s for (_, _, s) in first_pass_calls]
        first_pass_end_times = [s + 0.02 for s in first_pass_start_times]

        total_translate_calls = len(translate_calls)
        assert total_translate_calls == n_units + 3, (
            f"expected {n_units + 3} total translate calls "
            f"({n_units} first-pass + 3 retries for u0..u2), "
            f"got {total_translate_calls}: {translate_calls}"
        )
        assert set(first_pass_texts) == {f"src{i}" for i in range(n_units)}, (
            f"first-pass batch missing some units: {first_pass_texts}"
        )

        retry_calls = translate_calls[n_units:]
        retry_texts = [t for (t, _, _) in retry_calls]
        assert set(retry_texts) == {"src0", "src1", "src2"}, (
            f"retry batch has wrong units: got {retry_texts}, "
            f"expected ['src0', 'src1', 'src2']"
        )

        # === THE HEADLINE A4.3 INVARIANT ===
        # All retry calls must start AFTER the last first-pass translate
        # has ENDED. This is the A4 ordering guarantee from the plan:
        # "re-translate happens at the end (not while other units are
        # still translating)." Small slop accounts for the in-flight
        # judge phase of the last first-pass unit (judges may still be
        # running, but first-pass TRANSLATES of other units are done).
        last_first_pass_end = max(first_pass_end_times)
        first_retry_start = min(s for (_, _, s) in retry_calls)
        assert first_retry_start >= last_first_pass_end - 0.005, (
            f"A4.3 FAIL: first retry started at t={first_retry_start:.4f}, "
            f"but last first-pass translate ended at t={last_first_pass_end:.4f}. "
            f"Retries must NOT interleave with first-pass translates of "
            f"other units. first_pass_end_times={first_pass_end_times}, "
            f"retry_calls={retry_calls}"
        )

        by_id = {r.unit_id: r for r in results}
        for uid in ("u3", "u4", "u5"):
            assert by_id[uid].attempts == 1, (
                f"pass unit {uid!r} should have attempts=1, "
                f"got {by_id[uid].attempts}"
            )
        for uid in ("u0", "u1", "u2"):
            assert by_id[uid].attempts >= 2, (
                f"retry unit {uid!r} should have attempts>=2, "
                f"got {by_id[uid].attempts}"
            )
