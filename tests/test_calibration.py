"""Tests for Phase D3: calibration against reference LLM."""

import pytest

from ol_lqa.calibration import (
    CalibrationReport,
    average_inter_judge_agreement,
    calibrate,
    spearman_rank_correlation,
)
from ol_lqa.multi_judge import MultiJudgeResult


def make_result(a: int, f: int, t: int, fmt: int, agreement: float = 1.0) -> MultiJudgeResult:
    """Make a MultiJudgeResult with specified scores and agreement."""
    return MultiJudgeResult(
        adequacy=a, fluency=f, terminology=t, format=fmt,
        dimension_agreement={d: agreement for d in ("adequacy", "fluency", "terminology", "format")},
    )


class TestSpearman:
    def test_perfect_positive(self):
        assert spearman_rank_correlation([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == pytest.approx(1.0)

    def test_perfect_negative(self):
        assert spearman_rank_correlation([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == pytest.approx(-1.0)

    def test_no_correlation(self):
        rho = spearman_rank_correlation([1, 2, 3, 4, 5], [2, 4, 1, 3, 5])
        assert -1.0 <= rho <= 1.0

    def test_constant_series_returns_zero(self):
        assert spearman_rank_correlation([1, 1, 1], [2, 3, 4]) == 0.0

    def test_mismatched_length_raises(self):
        with pytest.raises(ValueError):
            spearman_rank_correlation([1, 2, 3], [1, 2])

    def test_too_short_returns_zero(self):
        assert spearman_rank_correlation([1], [2]) == 0.0


class TestAverageAgreement:
    def test_full_agreement(self):
        results = [make_result(4, 4, 4, 4, agreement=1.0) for _ in range(3)]
        assert average_inter_judge_agreement(results) == 1.0

    def test_mixed_agreement(self):
        results = [make_result(4, 4, 4, 4, agreement=0.5) for _ in range(3)]
        assert average_inter_judge_agreement(results) == 0.5

    def test_empty(self):
        assert average_inter_judge_agreement([]) == 0.0


class TestCalibrate:
    def test_passes_thresholds(self):
        judge_results = [
            make_result(5, 5, 4, 5),
            make_result(4, 5, 4, 4),
            make_result(3, 4, 3, 3),
            make_result(5, 5, 5, 5),
            make_result(2, 2, 2, 2),
        ]
        reference_scores = [
            {"adequacy": 5, "fluency": 5, "terminology": 4, "format": 5},
            {"adequacy": 4, "fluency": 5, "terminology": 4, "format": 4},
            {"adequacy": 3, "fluency": 4, "terminology": 3, "format": 3},
            {"adequacy": 5, "fluency": 5, "terminology": 5, "format": 5},
            {"adequacy": 2, "fluency": 2, "terminology": 2, "format": 2},
        ]
        report = calibrate(judge_results, reference_scores)
        assert report.passed
        assert report.average_spearman >= 0.7
        assert report.average_inter_judge_agreement == 1.0

    def test_fails_spearman(self):
        judge_results = [make_result(5, 1, 5, 1)]
        reference_scores = [{"adequacy": 1, "fluency": 5, "terminology": 1, "format": 5}]
        report = calibrate(judge_results, reference_scores)
        assert not report.passed
        assert any("Spearman" in f for f in report.failures)

    def test_fails_agreement(self):
        r1 = make_result(4, 4, 4, 4)
        r1.dimension_agreement = {"adequacy": 0.33, "fluency": 0.33, "terminology": 0.33, "format": 0.33}
        report = calibrate([r1], [{"adequacy": 4, "fluency": 4, "terminology": 4, "format": 4}])
        assert not report.passed
        assert any("agreement" in f for f in report.failures)

    def test_mismatch_raises(self):
        with pytest.raises(ValueError):
            calibrate([make_result(4, 4, 4, 4)], [])

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            calibrate([], [])


class TestCalibrationReport:
    def test_to_dict(self):
        report = CalibrationReport(
            num_docs=5,
            average_spearman=0.85,
            average_inter_judge_agreement=0.75,
        )
        report.evaluate()
        d = report.to_dict()
        assert d["passed"] is True
        assert d["num_docs"] == 5
        assert d["thresholds"]["spearman"] == 0.7
        assert d["thresholds"]["agreement"] == 0.6
