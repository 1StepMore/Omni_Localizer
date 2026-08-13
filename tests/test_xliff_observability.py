"""Tests for OL#51: XLIFF pipeline observability and cross-unit uniqueness.

P0 — Observability
  - Per-unit translation request logging (unit_id, source_text[:50], response[:50])
  - Per-unit judge score logging (score vs threshold)
  - Retry decision logging (which units enter retry and why)
  - Polish correction logging (old_text → new_text + reason)

P1 — Cross-unit uniqueness validation
  - Units with identical target_text but different source_text → warning
  - Units with different targets → silence (no false positive)
  - Units with empty/None target_text → no crash

All tests use mocked pool/judge (no real LLM) and caplog for log assertions.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers (mirror patterns from test_lqa_pipelining.py)
# ---------------------------------------------------------------------------


def _make_unit(unit_id: str, source: str, target: str | None = None,
               shield_map: dict | None = None):
    """Build a TranslationUnit-like object (SimpleNamespace) for testing."""
    return SimpleNamespace(
        unit_id=unit_id,
        source_text=source,
        target_text=target,
        shield_map=shield_map or {},
    )


def _make_eval_result(unit_id: str, score: float) -> object:
    """Build an EvaluationResult-like object (SimpleNamespace) for testing."""
    return SimpleNamespace(
        unit_id=unit_id,
        judge_overall_score=score,
    )


def _instrumented_pool(return_text: str = "OUT:translated"):
    """Build a mock pool that returns deterministic translations."""
    pool = MagicMock()
    pool.translate = AsyncMock(return_value=return_text)
    return pool


def _instrumented_judge(per_unit_score: dict[str, float] | None = None):
    """Build a mock judge that returns deterministic scores."""
    default_score = 9.0

    async def _judge(source, target, unit_id, **_kwargs):
        score = (per_unit_score or {}).get(unit_id, default_score)
        return _make_eval_result(unit_id, score)

    judge = MagicMock()
    judge.judge = AsyncMock(side_effect=_judge)
    judge._pass_threshold = 7.0
    return judge


# ---------------------------------------------------------------------------
# P0 — Per-unit translation + judge logging
# ---------------------------------------------------------------------------


class TestTranslationLogging:
    """P0-1: unit_pipeline logs translation request per unit."""

    @pytest.mark.asyncio
    async def test_unit_pipeline_logs_translation_per_unit(self, caplog):
        """Verify unit_pipeline logs unit_id + source + target for each unit."""
        from ol_cli import _translate_xliff_pipelined

        n_units = 2
        units = [_make_unit(f"u{i}", f"source text {i}"*5) for i in range(n_units)]
        pool = _instrumented_pool(return_text="OUT: translation result")
        judge = _instrumented_judge()
        retry_mgr = MagicMock()
        retry_mgr._pass_threshold = 7.0

        import asyncio
        caplog.set_level(logging.INFO, logger="ol.cli")
        results = await _translate_xliff_pipelined(
            units, pool, judge, retry_mgr, "en", "zh",
            sem=asyncio.Semaphore(10),
        )

        assert len(results) == n_units
        # Check translate logging for each unit
        for i in range(n_units):
            assert any(
                f"XLIFF translate: unit=u{i}" in msg
                for msg in caplog.messages
            ), f"Missing translate log for u{i}"
        # Verify source[:50] appears in logs
        assert any(
            "source text" in msg
            for msg in caplog.messages
        ), "Source text snippet missing from logs"

    @pytest.mark.asyncio
    async def test_unit_pipeline_logs_judge_score_per_unit(self, caplog):
        """Verify judge score + threshold logged per unit."""
        from ol_cli import _translate_xliff_pipelined

        n_units = 2
        units = [_make_unit(f"u{i}", f"source text {i}") for i in range(n_units)]
        pool = _instrumented_pool(return_text="OUT: translated")
        judge = _instrumented_judge(per_unit_score={"u0": 8.5, "u1": 6.2})
        retry_mgr = MagicMock()
        retry_mgr._pass_threshold = 7.0

        import asyncio
        caplog.set_level(logging.INFO, logger="ol.cli")
        results = await _translate_xliff_pipelined(
            units, pool, judge, retry_mgr, "en", "zh",
            sem=asyncio.Semaphore(10),
        )

        assert len(results) == n_units
        # Check judge score logging
        assert any(
            "XLIFF judge: unit=u0 score=8.5 threshold=7.0" in msg
            for msg in caplog.messages
        ), "Missing judge score log for u0"
        assert any(
            "XLIFF judge: unit=u1 score=6.2" in msg
            for msg in caplog.messages
        ), "Missing judge score log for u1"


# ---------------------------------------------------------------------------
# P0 — Retry decision logging
# ---------------------------------------------------------------------------


class TestRetryDecisionLogging:
    """P0-3: retry phase logs which units enter retry and why."""

    @pytest.mark.asyncio
    async def test_retry_phase_logs_low_scoring_units(self, caplog):
        """Verify units below threshold are logged with score + threshold."""
        from ol_cli import _translate_xliff_pipelined

        units = [
            _make_unit("pass", "high quality source"),
            _make_unit("fail", "low quality source"),
        ]
        pool = _instrumented_pool(return_text="OUT: translated")
        judge = _instrumented_judge(per_unit_score={"pass": 9.0, "fail": 5.0})
        retry_mgr = MagicMock()
        retry_mgr._pass_threshold = 7.0

        import asyncio
        caplog.set_level(logging.INFO, logger="ol.cli")
        results = await _translate_xliff_pipelined(
            units, pool, judge, retry_mgr, "en", "zh",
            sem=asyncio.Semaphore(10),
        )

        assert len(results) == 2
        # The low-scoring unit should be logged for retry
        assert any(
            "XLIFF retry: unit=fail score=5.0 < threshold=7.0" in msg
            for msg in caplog.messages
        ), "Missing retry log for low-scoring unit"
        # High-scoring unit should NOT have retry log
        assert not any(
            "XLIFF retry: unit=pass" in msg
            for msg in caplog.messages
        ), "High-scoring unit should not be logged for retry"


# ---------------------------------------------------------------------------
# P0 — Polish correction logging
# ---------------------------------------------------------------------------


class TestPolishCorrectionLogging:
    """P0-4: polish pass logs individual corrections."""

    @pytest.mark.asyncio
    async def test_polish_logs_individual_corrections(self, caplog):
        """Verify each polish correction logs old_text → new_text + reason."""
        from ol_xliff.polish import polish_translated_units

        units = [
            _make_unit("u0", "source A", target="old target text A"),
            _make_unit("u1", "source B", target="old target text B"),
        ]
        pool = MagicMock()
        # Return a correction response
        pool.translate = AsyncMock(return_value=(
            "id: u0\n"
            "fix: new target text A\n"
            "reason: TERM_INCONSISTENCY: unified Apple → 苹果\n"
            "\n"
            "id: u1\n"
            "fix: new target text B\n"
            "reason: GRAMMAR: added missing article\n"
        ))

        caplog.set_level(logging.INFO, logger="ol_xliff.polish")
        warnings = await polish_translated_units(units, "en", "zh", pool)

        assert "u0" in warnings, "u0 should have polish warning"
        assert "u1" in warnings, "u1 should have polish warning"
        # Check per-correction logging
        assert any(
            "Polish correction: unit=u0" in msg
            for msg in caplog.messages
        ), "Missing polish correction log for u0"
        assert any(
            "Polish correction: unit=u1" in msg
            for msg in caplog.messages
        ), "Missing polish correction log for u1"
        found_reason = any(
            "Polish correction" in msg and "TERM_INCONSISTENCY" in msg
            for msg in caplog.messages
        )
        assert found_reason, "Missing TERM_INCONSISTENCY reason in polish log"


# ---------------------------------------------------------------------------
# P1 — Cross-unit uniqueness validation
# ---------------------------------------------------------------------------


class TestCrossUnitUniqueness:
    """P1: cross-unit duplicate target detection."""

    def test_detects_same_target_different_source(self):
        """Verify warning when different sources share identical target."""
        from ol_buses.xliff_bus import check_cross_unit_uniqueness

        units = [
            _make_unit("u0", "Apple Inc.", target="苹果公司"),
            _make_unit("u1", "Apple Computer", target="苹果公司"),
            _make_unit("u2", "different text", target="不同文本"),
        ]
        warnings = check_cross_unit_uniqueness(units)
        assert len(warnings) == 1, "Should have exactly one duplicate warning"
        assert "CROSS_UNIT_DUPLICATE" in warnings[0], (
            "Warning should contain CROSS_UNIT_DUPLICATE tag"
        )
        assert "苹果公司" in warnings[0], (
            "Warning should mention the duplicated target"
        )
        assert "u0" in warnings[0] and "u1" in warnings[0], (
            "Warning should list both unit IDs"
        )

    def test_no_false_positive_different_targets(self):
        """Verify no warning when all targets are unique."""
        from ol_buses.xliff_bus import check_cross_unit_uniqueness

        units = [
            _make_unit("u0", "source A", target="target A"),
            _make_unit("u1", "source B", target="target B"),
        ]
        warnings = check_cross_unit_uniqueness(units)
        assert len(warnings) == 0, (
            "Should have no warnings for unique targets"
        )

    def test_no_false_positive_identical_source_target_pairs(self):
        """Verify no warning when identical sources produce identical targets."""
        from ol_buses.xliff_bus import check_cross_unit_uniqueness

        units = [
            _make_unit("u0", "Hello", target="你好"),
            _make_unit("u1", "Hello", target="你好"),
        ]
        warnings = check_cross_unit_uniqueness(units)
        assert len(warnings) == 0, (
            "Should have no warnings when sources match"
        )

    def test_empty_target_ignored(self):
        """Verify empty/None targets don't cause false positives or crashes."""
        from ol_buses.xliff_bus import check_cross_unit_uniqueness

        units = [
            _make_unit("u0", "source A", target=""),
            _make_unit("u1", "source B", target=None),
            _make_unit("u2", "source C", target="  "),
        ]
        warnings = check_cross_unit_uniqueness(units)
        assert len(warnings) == 0, (
            "No warnings for empty/whitespace targets"
        )

    def test_logger_receives_warning(self, caplog):
        """Verify the warning is sent to the logger."""
        from ol_buses.xliff_bus import check_cross_unit_uniqueness

        units = [
            _make_unit("u0", "source A", target="duplicate target"),
            _make_unit("u1", "source B", target="duplicate target"),
        ]
        caplog.set_level(logging.WARNING, logger="ol_buses.xliff_bus")
        warnings = check_cross_unit_uniqueness(units)
        assert len(warnings) == 1
        assert any(
            "Cross-unit duplicate" in msg
            for msg in caplog.messages
        ), "Logger should receive the duplicate warning"


# ---------------------------------------------------------------------------
# P0 — End-to-end: verify all logging fires together in a pipeline run
# ---------------------------------------------------------------------------


class TestFullPipelineLogging:
    """Verify all logging points fire during a full pipeline execution."""

    @pytest.mark.asyncio
    async def test_pipeline_logs_translate_judge_and_retry(self, caplog):
        """All three logging points fire during a normal pipeline run."""
        from ol_cli import _translate_xliff_pipelined

        units = [
            _make_unit("good", "high quality"),
            _make_unit("bad", "low quality"),
        ]
        pool = _instrumented_pool(return_text="OUT: translated")
        judge = _instrumented_judge(per_unit_score={"good": 9.0, "bad": 4.0})
        retry_mgr = MagicMock()
        retry_mgr._pass_threshold = 7.0

        import asyncio
        caplog.set_level(logging.INFO, logger="ol.cli")
        results = await _translate_xliff_pipelined(
            units, pool, judge, retry_mgr, "en", "zh",
            sem=asyncio.Semaphore(10),
        )

        assert len(results) == 2
        messages = "\n".join(caplog.messages)

        # All three logging points
        assert "XLIFF translate: unit=good" in messages
        assert "XLIFF translate: unit=bad" in messages
        assert "XLIFF judge: unit=good" in messages
        assert "XLIFF judge: unit=bad" in messages
        assert "XLIFF retry: unit=bad" in messages
        assert "XLIFF retry: unit=bad" in messages


# ---------------------------------------------------------------------------
# P1 — Edge cases for cross-unit uniqueness
# ---------------------------------------------------------------------------


class TestCrossUnitUniquenessEdgeCases:
    """Additional edge cases for the uniqueness check."""

    def test_empty_units_list(self):
        """Empty units list should return empty warnings."""
        from ol_buses.xliff_bus import check_cross_unit_uniqueness
        warnings = check_cross_unit_uniqueness([])
        assert warnings == []

    def test_single_unit(self):
        """Single unit should never trigger duplicate warning."""
        from ol_buses.xliff_bus import check_cross_unit_uniqueness
        units = [_make_unit("u0", "source", target="target")]
        warnings = check_cross_unit_uniqueness(units)
        assert warnings == []
