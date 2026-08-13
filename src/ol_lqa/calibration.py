"""Calibration against reference LLM (Phase D3).

Computes two calibration metrics on the reference set:
1. Spearman rank correlation ≥ 0.7 between multi-judge scores
   and reference LLM scores (per dimension, across 20 docs)
2. Inter-judge exact-match agreement ≥ 60% (at least 2 of 3
   judges give the exact same score — no ±1 tolerance)

No human ratings — reference LLM is the ground truth proxy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ol_lqa.multi_judge import DIMENSIONS, MultiJudgeResult


def spearman_rank_correlation(x: Sequence[float], y: Sequence[float]) -> float:
    """Compute Spearman rank correlation coefficient.

    Args:
        x: first series of values
        y: second series of values (same length as x)

    Returns:
        Spearman rho in [-1.0, 1.0]. Returns 0.0 if either series
        is constant (no variance to correlate).
    """
    n = len(x)
    if n != len(y):
        raise ValueError(f"x and y must have same length, got {n} and {len(y)}")
    if n < 2:
        return 0.0

    def rank(values: Sequence[float]) -> list[float]:
        sorted_indices = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(sorted_indices):
            j = i
            while j + 1 < len(sorted_indices) and values[sorted_indices[j + 1]] == values[sorted_indices[i]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                ranks[sorted_indices[k]] = avg_rank
            i = j + 1
        return ranks

    rx = rank(list(x))
    ry = rank(list(y))

    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    d = [rx[i] - mean_rx for i in range(n)]
    e = [ry[i] - mean_ry for i in range(n)]
    d_sq = sum(di * di for di in d)
    e_sq = sum(ei * ei for ei in e)
    if d_sq == 0 or e_sq == 0:
        return 0.0
    cov = sum(d[i] * e[i] for i in range(n))
    return cov / (d_sq * e_sq) ** 0.5


def average_inter_judge_agreement(results: Sequence[MultiJudgeResult]) -> float:
    """Average exact-match agreement across all dimensions and docs.

    Args:
        results: list of MultiJudgeResult (one per document)

    Returns:
        Average agreement in [0.0, 1.0].
    """
    if not results:
        return 0.0
    total = 0.0
    count = 0
    for r in results:
        for dim in DIMENSIONS:
            total += r.dimension_agreement.get(dim, 0.0)
            count += 1
    return total / count if count else 0.0


@dataclass
class CalibrationReport:
    """Result of a calibration run."""

    spearman_per_dimension: dict[str, float] = field(default_factory=dict)
    average_spearman: float = 0.0
    average_inter_judge_agreement: float = 0.0
    num_docs: int = 0
    passed: bool = False
    failures: list[str] = field(default_factory=list)

    SPEARMAN_THRESHOLD = 0.7
    AGREEMENT_THRESHOLD = 0.6

    def evaluate(self) -> None:
        self.passed = (
            self.average_spearman >= self.SPEARMAN_THRESHOLD
            and self.average_inter_judge_agreement >= self.AGREEMENT_THRESHOLD
        )
        self.failures = []
        if self.average_spearman < self.SPEARMAN_THRESHOLD:
            self.failures.append(
                f"Spearman {self.average_spearman:.3f} < {self.SPEARMAN_THRESHOLD}"
            )
        if self.average_inter_judge_agreement < self.AGREEMENT_THRESHOLD:
            self.failures.append(
                f"Inter-judge agreement {self.average_inter_judge_agreement:.3f} < {self.AGREEMENT_THRESHOLD}"
            )

    def to_dict(self) -> dict:
        return {
            "num_docs": self.num_docs,
            "spearman_per_dimension": self.spearman_per_dimension,
            "average_spearman": self.average_spearman,
            "average_inter_judge_agreement": self.average_inter_judge_agreement,
            "thresholds": {
                "spearman": self.SPEARMAN_THRESHOLD,
                "agreement": self.AGREEMENT_THRESHOLD,
            },
            "passed": self.passed,
            "failures": self.failures,
        }


def calibrate(
    judge_results: Sequence[MultiJudgeResult],
    reference_scores: Sequence[dict[str, int]],
) -> CalibrationReport:
    """Run calibration against reference LLM scores.

    Args:
        judge_results: multi-judge results, one per document
        reference_scores: reference LLM scores, one dict per document
            with keys: adequacy, fluency, terminology, format (1-5 each)

    Returns:
        CalibrationReport with pass/fail and metrics.
    """
    n = len(judge_results)
    if n != len(reference_scores):
        raise ValueError(f"Mismatch: {n} judge results vs {len(reference_scores)} reference")
    if n == 0:
        raise ValueError("Need at least 1 document to calibrate")

    report = CalibrationReport(num_docs=n)

    for dim in DIMENSIONS:
        judge_dim_scores = []
        ref_dim_scores = []
        for jr, ref in zip(judge_results, reference_scores):
            judge_dim_scores.append(getattr(jr, dim))
            ref_dim_scores.append(ref.get(dim, 0))
        rho = spearman_rank_correlation(judge_dim_scores, ref_dim_scores)
        report.spearman_per_dimension[dim] = rho

    report.average_spearman = sum(report.spearman_per_dimension.values()) / len(DIMENSIONS)
    report.average_inter_judge_agreement = average_inter_judge_agreement(judge_results)
    report.evaluate()
    return report
