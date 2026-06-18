"""Tests for Phase D2: multi-judge LQA aggregation."""

import pytest

from ol_lqa.multi_judge import (
    DIMENSIONS,
    JudgeScore,
    MultiJudgeResult,
    aggregate,
    exact_match_agreement,
    majority_vote,
)


def make_scores(*tuples: tuple[str, int, int, int, int]) -> list[JudgeScore]:
    """Helper: tuples are (judge_name, adequacy, fluency, terminology, format)."""
    return [
        JudgeScore(
            judge_name=name,
            scores={
                "adequacy": a, "fluency": f, "terminology": t, "format": fmt,
            },
        )
        for name, a, f, t, fmt in tuples
    ]


class TestMajorityVote:
    def test_clear_majority(self):
        assert majority_vote([5, 5, 3]) == 5

    def test_majority_with_2_1(self):
        assert majority_vote([4, 4, 2]) == 4

    def test_all_same(self):
        assert majority_vote([3, 3, 3]) == 3

    def test_all_different_returns_median(self):
        assert majority_vote([1, 3, 5]) == 3

    def test_empty(self):
        assert majority_vote([]) == 0

    def test_single(self):
        assert majority_vote([4]) == 4


class TestExactMatchAgreement:
    def test_full_agreement(self):
        assert exact_match_agreement([4, 4, 4]) == 1.0

    def test_two_of_three(self):
        assert exact_match_agreement([4, 4, 3]) == pytest.approx(2 / 3)

    def test_no_agreement(self):
        assert exact_match_agreement([1, 2, 3]) == pytest.approx(1 / 3)


class TestAggregate:
    def test_known_good_segment_all_5s(self):
        scores = make_scores(("judge_a", 5, 5, 5, 5), ("judge_b", 5, 5, 5, 5), ("judge_c", 5, 5, 5, 5))
        result = aggregate(scores)
        assert result.adequacy == 5
        assert result.fluency == 5
        assert result.terminology == 5
        assert result.format == 5
        assert result.average == 5.0
        assert all(result.dimension_agreement[d] == 1.0 for d in DIMENSIONS)

    def test_known_bad_segment_detected(self):
        scores = make_scores(
            ("judge_a", 1, 2, 1, 2),
            ("judge_b", 2, 1, 2, 1),
            ("judge_c", 5, 5, 5, 5),
        )
        result = aggregate(scores)
        assert result.adequacy == 2
        assert result.fluency == 2
        assert result.terminology == 2
        assert result.format == 2
        assert result.average == 2.0
        assert all(result.dimension_agreement[d] == pytest.approx(1 / 3) for d in DIMENSIONS)

    def test_mixed_scores(self):
        scores = make_scores(
            ("judge_a", 4, 5, 3, 4),
            ("judge_b", 4, 4, 3, 4),
            ("judge_c", 5, 5, 4, 4),
        )
        result = aggregate(scores)
        assert result.adequacy == 4
        assert result.fluency == 5
        assert result.terminology == 3
        assert result.format == 4


class TestMultiJudgeResult:
    def test_passed_threshold(self):
        r = MultiJudgeResult(adequacy=4, fluency=4, terminology=4, format=4)
        assert r.passed(4.0)
        assert r.average == 4.0

    def test_failed_threshold(self):
        r = MultiJudgeResult(adequacy=3, fluency=3, terminology=3, format=3)
        assert not r.passed(4.0)
        assert r.average == 3.0

    def test_to_dict(self):
        r = MultiJudgeResult(adequacy=4, fluency=5, terminology=3, format=4)
        d = r.to_dict()
        assert d["average"] == 4.0
        assert d["adequacy"] == 4
