"""A11.4 — CostEstimator unit tests.

Runs in normal CI (no LLM calls, no env-var gating). The estimator is a
pure-Python class; tests are deterministic and fast.
"""
from __future__ import annotations

import pytest

from tests.real_llm.cost_estimator import CostEstimator


# ===========================================================================
# A11.4 — required tests
# ===========================================================================

def test_estimate_call_returns_correct_usd() -> None:
    """Pin per-model USD math: M3 = $3/$15, M2.7 = $2/$10, ernie-4.5 = $1/$4.

    For 1M input + 1M output tokens:
      - MiniMax-M3:        $3 + $15 = $18
      - MiniMax-M2.7:      $2 + $10 = $12
      - ernie-4.5-turbo-32k: $1 + $4 = $5

    Asserts the cost estimator returns the expected USD amount for a
    full-million-token call on each known model. This is the contract
    the nightly runbook depends on (see docs/real_llm_runbook.md).
    """
    est = CostEstimator(budget_usd=100.0)

    # MiniMax-M3: $3/M input + $15/M output
    cost_m3 = est.estimate_call("MiniMax-M3", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_m3 == pytest.approx(18.0), (
        f"MiniMax-M3 1M+1M tokens must cost $18 (3+15), got ${cost_m3}"
    )

    # MiniMax-M2.7: $2/M input + $10/M output
    cost_m27 = est.estimate_call("MiniMax-M2.7", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_m27 == pytest.approx(12.0), (
        f"MiniMax-M2.7 1M+1M tokens must cost $12 (2+10), got ${cost_m27}"
    )

    # ernie-4.5-turbo-32k: $1/M input + $4/M output
    cost_ernie = est.estimate_call("ernie-4.5-turbo-32k", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_ernie == pytest.approx(5.0), (
        f"ernie-4.5-turbo-32k 1M+1M tokens must cost $5 (1+4), got ${cost_ernie}"
    )

    # Sanity: a smaller call scales linearly
    cost_small = est.estimate_call("MiniMax-M3", input_tokens=1000, output_tokens=2000)
    assert cost_small == pytest.approx(0.003 + 0.030), (
        f"MiniMax-M3 1K input + 2K output = $0.003 + $0.030 = $0.033, got ${cost_small}"
    )

    # record_call is a no-op for estimation correctness; estimator state stays clean
    assert est.call_count == 0
    assert est.total_cost_usd == 0.0


def test_would_exceed_budget_returns_true_when_over() -> None:
    """Pin pre-call budget gate: returns True iff cumulative+candidate > budget.

    Scenario: $1.00 budget, $0.50 already spent, candidate $0.60. Sum = $1.10
    exceeds $1.00 → gate returns True (caller should skip the call).

    The boundary is strict (``>``): a candidate that exactly hits the
    budget is allowed through. The exact-budget case is asserted too
    so the contract is pinned on both sides.
    """
    est = CostEstimator(budget_usd=1.0)

    # Record $0.50 of spend (M3, 100K input + ~13.33K output → $0.30 + $0.20 = $0.50)
    # 100_000 input * 3.0 / 1e6 = 0.30
    # 13_334 output * 15.0 / 1e6 ≈ 0.20001 — round to whole tokens to hit 0.20
    # Use simpler: 100_000 input * 3.0 = $0.30; 13_333 output * 15.0 ≈ $0.19999
    # Easier: build a $0.50 spend via 50_000 input + 25_000 output on M3:
    #   50_000 * 3.0 / 1e6 = 0.15
    #   25_000 * 15.0 / 1e6 = 0.375 → total 0.525 — not exactly 0.50
    # Use M2.7: 100_000 input * 2.0 = $0.20; 30_000 output * 10.0 = $0.30 → total $0.50 exactly
    est.record_call("MiniMax-M2.7", input_tokens=100_000, output_tokens=30_000)
    assert est.total_cost_usd == pytest.approx(0.50), (
        f"Setup: 100K input + 30K output on M2.7 must be $0.50, got ${est.total_cost_usd}"
    )

    # Candidate $0.60 → total would be $1.10 > $1.00 → gate returns True
    candidate = est.estimate_call("MiniMax-M2.7", input_tokens=100_000, output_tokens=40_000)
    assert candidate == pytest.approx(0.60), (
        f"Candidate cost must be $0.60, got ${candidate}"
    )
    assert est.would_exceed_budget(candidate) is True, (
        "Budget=$1.00, cumulative=$0.50, candidate=$0.60 → sum $1.10 > $1.00, "
        "gate must return True (skip the call)"
    )

    # Caller skipped: estimator state unchanged
    assert est.call_count == 1
    assert est.total_cost_usd == pytest.approx(0.50)

    # Boundary: candidate that exactly hits the budget is allowed through (strict >)
    boundary = est.estimate_call("MiniMax-M2.7", input_tokens=100_000, output_tokens=30_000)
    assert boundary == pytest.approx(0.50)
    assert est.would_exceed_budget(boundary) is False, (
        "Boundary: cumulative=$0.50, candidate=$0.50 → sum $1.00 == $1.00, "
        "gate must return False (allow the call, strict >)"
    )

    # Sanity: a tiny safe candidate is also allowed
    safe = est.estimate_call("MiniMax-M2.7", input_tokens=1_000, output_tokens=1_000)
    assert est.would_exceed_budget(safe) is False
