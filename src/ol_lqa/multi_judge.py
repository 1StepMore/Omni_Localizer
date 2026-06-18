"""Multi-judge LQA (Phase D2).

Uses 3 different LLM judges from different providers. Each scores
1-5 on adequacy, fluency, terminology, format. Majority vote per
dimension (2/3 wins). If tied, take the median.

No human in the loop — judges are LLMs from different providers
to reduce single-model bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

DIMENSIONS = ("adequacy", "fluency", "terminology", "format")


@dataclass
class JudgeScore:
    """Single judge's scores across all dimensions (1-5 each)."""

    judge_name: str
    scores: dict[str, int] = field(default_factory=dict)

    def get(self, dimension: str) -> int:
        return self.scores.get(dimension, 0)


@dataclass
class MultiJudgeResult:
    """Aggregated multi-judge result with majority vote per dimension."""

    adequacy: int
    fluency: int
    terminology: int
    format: int
    individual_scores: list[JudgeScore] = field(default_factory=list)
    dimension_agreement: dict[str, float] = field(default_factory=dict)

    @property
    def average(self) -> float:
        return (self.adequacy + self.fluency + self.terminology + self.format) / 4.0

    def passed(self, threshold: float = 4.0) -> bool:
        return self.average >= threshold

    def to_dict(self) -> dict:
        return {
            "adequacy": self.adequacy,
            "fluency": self.fluency,
            "terminology": self.terminology,
            "format": self.format,
            "average": self.average,
            "dimension_agreement": self.dimension_agreement,
        }


def majority_vote(scores: Sequence[int]) -> int:
    """Return the majority vote. If tied, return the median.

    Args:
        scores: list of integer scores (1-5) from 3 judges.

    Returns:
        The majority-vote score. If 3 scores are all different,
        returns the median.
    """
    if not scores:
        return 0
    if len(scores) == 1:
        return scores[0]

    sorted_scores = sorted(scores)
    n = len(sorted_scores)
    median = sorted_scores[n // 2]
    if n % 2 == 0:
        median = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) // 2

    from collections import Counter
    counts = Counter(scores)
    most_common = counts.most_common(1)[0]
    if most_common[1] >= 2:
        return most_common[0]
    return median


def exact_match_agreement(scores: Sequence[int]) -> float:
    """Fraction of judges that give the exact same score (0.0-1.0)."""
    if not scores:
        return 0.0
    from collections import Counter
    counts = Counter(scores)
    most_common_count = counts.most_common(1)[0][1]
    return most_common_count / len(scores)


def aggregate(judge_scores: Sequence[JudgeScore]) -> MultiJudgeResult:
    """Aggregate 3 judges' scores into a single MultiJudgeResult.

    Args:
        judge_scores: sequence of 3 JudgeScore objects (one per judge).

    Returns:
        MultiJudgeResult with majority-vote scores per dimension.
    """
    result_kwargs: dict[str, int] = {}
    agreement: dict[str, float] = {}
    for dim in DIMENSIONS:
        scores = [js.get(dim) for js in judge_scores]
        result_kwargs[dim] = majority_vote(scores)
        agreement[dim] = exact_match_agreement(scores)

    return MultiJudgeResult(
        **result_kwargs,
        individual_scores=list(judge_scores),
        dimension_agreement=agreement,
    )
