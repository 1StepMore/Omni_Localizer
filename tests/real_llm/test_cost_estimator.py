"""A11.4 — CostEstimator unit tests.

Runs in normal CI (no LLM calls, no env-var gating). The estimator is a
pure-Python class; tests are deterministic and fast.

Rates are caller-supplied here (never shipped by the module), so the tests
pass explicit test doubles rather than real provider prices. The fail-closed
contract — a missing or unknown model raises before any call is issued — is
pinned explicitly.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.real_llm.cost_estimator import (
    RATES_ENV_VAR,
    CostEstimator,
    load_rates,
    rates_from_env,
)
from tests.real_llm.test_real_llm_e2e import _PRIMARY_MODEL

_OL_ROOT = Path(__file__).resolve().parents[2]


# ===========================================================================
# A11.4 — required tests
# ===========================================================================

def test_estimate_call_returns_correct_usd() -> None:
    """Pin the USD math for caller-supplied rates.

    Rates are test doubles (not provider prices): alpha = $1/$2, beta =
    $3/$4 per 1M tokens. For 1M input + 1M output tokens that is $3 and $7
    respectively; a 1K/2K call scales linearly.
    """
    est = CostEstimator(budget_usd=100.0, rates={"alpha": (1.0, 2.0), "beta": (3.0, 4.0)})

    assert est.estimate_call("alpha", 1_000_000, 1_000_000) == pytest.approx(3.0)
    assert est.estimate_call("beta", 1_000_000, 1_000_000) == pytest.approx(7.0)

    small = est.estimate_call("beta", input_tokens=1000, output_tokens=2000)
    assert small == pytest.approx(0.003 + 0.008)

    assert est.call_count == 0
    assert est.total_cost_usd == 0.0


def test_missing_rate_fails_closed() -> None:
    """No rates configured → estimate_call raises before any call is issued."""
    est = CostEstimator(budget_usd=5.0)
    with pytest.raises(KeyError) as exc:
        est.estimate_call("ark-code-latest", 1000, 1000)
    assert RATES_ENV_VAR in str(exc.value)


def test_unknown_model_fails_closed() -> None:
    """A model absent from the supplied map raises (never silently $0)."""
    est = CostEstimator(budget_usd=5.0, rates={"alpha": (1.0, 2.0)})
    with pytest.raises(KeyError) as exc:
        est.estimate_call("gamma", 1000, 1000)
    assert "gamma" in str(exc.value)
    assert "alpha" in str(exc.value)


def test_selected_primary_model_matches_canonical_default() -> None:
    """The harness's cost-gate model must be config/default.yaml priority 1.

    Locks the selected model to the canonical pool so a model swap cannot
    leave the cost gate pricing a model that is no longer the primary.
    """
    data = yaml.safe_load((_OL_ROOT / "config" / "default.yaml").read_text(encoding="utf-8"))
    canonical_primary = data["llm_pool"]["translation"][0]["model"]
    assert _PRIMARY_MODEL == "ark-code-latest"
    assert _PRIMARY_MODEL == canonical_primary


def test_selected_primary_model_rate_is_priceable() -> None:
    """With an explicit rate supplied, the selected model estimates cleanly."""
    est = CostEstimator(budget_usd=5.0, rates={_PRIMARY_MODEL: (1.0, 2.0)})
    assert est.estimate_call(_PRIMARY_MODEL, 1_000_000, 0) == pytest.approx(1.0)


# ===========================================================================
# Rate-map parsing (OL_REAL_LLM_RATES)
# ===========================================================================

def test_rates_from_env_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        RATES_ENV_VAR,
        '{"ark-code-latest": [1.5, 3.0], "glm-4.7-flash": [0.5, 1.0]}',
    )
    rates = rates_from_env()
    assert rates == {"ark-code-latest": (1.5, 3.0), "glm-4.7-flash": (0.5, 1.0)}


def test_rates_from_env_unset_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(RATES_ENV_VAR, raising=False)
    assert rates_from_env() == {}


def test_rates_from_env_malformed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RATES_ENV_VAR, '{"broken": [1.0]}')
    with pytest.raises(ValueError):
        rates_from_env()


def test_load_rates_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        load_rates("[1, 2, 3]")


# ===========================================================================
# Budget gate
# ===========================================================================

def test_would_exceed_budget_returns_true_when_over() -> None:
    """Pin pre-call budget gate: True iff cumulative+candidate > budget.

    Rates are test doubles: alpha = $2/$4 per 1M tokens. 100K input +
    30K output = $0.20 + $0.12 = $0.32 recorded; the same candidate pushes
    $0.64 past a $0.50 budget. The boundary is strict (``>``): a candidate
    that exactly hits the remaining budget is allowed through.
    """
    est = CostEstimator(budget_usd=0.50, rates={"alpha": (2.0, 4.0)})

    est.record_call("alpha", input_tokens=100_000, output_tokens=30_000)
    assert est.total_cost_usd == pytest.approx(0.32)

    candidate = est.estimate_call("alpha", input_tokens=100_000, output_tokens=30_000)
    assert candidate == pytest.approx(0.32)
    assert est.would_exceed_budget(candidate) is True
    assert est.call_count == 1
    assert est.total_cost_usd == pytest.approx(0.32)

    # Boundary: cumulative $0.32 + candidate $0.18 == $0.50 → allowed (strict >).
    boundary = est.estimate_call("alpha", input_tokens=90_000, output_tokens=0)
    assert boundary == pytest.approx(0.18)
    assert est.would_exceed_budget(boundary) is False

    # A tiny safe candidate is also allowed.
    safe = est.estimate_call("alpha", input_tokens=1_000, output_tokens=1_000)
    assert est.would_exceed_budget(safe) is False


def test_negative_tokens_raise() -> None:
    est = CostEstimator(budget_usd=5.0, rates={"alpha": (1.0, 2.0)})
    with pytest.raises(ValueError):
        est.estimate_call("alpha", -1, 10)


def test_negative_cost_raises() -> None:
    est = CostEstimator(budget_usd=5.0)
    with pytest.raises(ValueError):
        est.would_exceed_budget(-0.01)
