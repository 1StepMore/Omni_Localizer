"""A11 — CostEstimator for real-LLM nightly runs.

The estimator provides a **pre-call gate** (``would_exceed_budget``) so a
runaway test suite can't rack up a surprise bill, and a **post-call tracker**
(``record_call``) so cumulative spend is auditable from ``summary()``.

Pricing is **explicit and fail-closed**. This module ships no hardcoded
prices: provider list prices change, and a stale number would silently
mis-bill real calls. Supply the current per-1M-token USD rates either:

- via the constructor —
  ``CostEstimator(rates={"<model>": [input_rate, output_rate], ...})``, or
- via the ``OL_REAL_LLM_RATES`` env var holding that same JSON object
  (``rates_from_env()`` reads it).

Any model missing from the map raises ``KeyError`` at ``estimate_call``
time — before the LLM call is issued — so an unknown or unpriced model fails
closed instead of spending. See ``docs/real_llm_runbook.md`` for the
rate-supply / recalibration procedure.

Design constraints:
- Pure stdlib + dataclass; no LLM calls.
- The rate table is caller-supplied data, never inferred from
  ``config/*.yaml`` (a stale config must not silently mis-bill).
- Unknown/missing model → ``KeyError`` (fail-closed).

Marker convention: this module is import-safe from any test in
``tests/real_llm/``. The conftest's ``cost_estimator`` fixture returns a
fresh instance per test.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


RATES_ENV_VAR = "OL_REAL_LLM_RATES"
"""Env var holding the explicit JSON rate map: ``{"<model>": [in, out]}``."""


def load_rates(raw: str | None) -> dict[str, tuple[float, float]]:
    """Parse an explicit JSON rate map.

    Args:
        raw: JSON object mapping model name to ``[input_rate, output_rate]``
            (USD per 1M tokens). ``None`` or empty string yields ``{}`` —
            fail-closed (every model then raises at ``estimate_call``).

    Raises:
        ValueError: ``raw`` is not a JSON object, or a value is not a
            two-element ``[input, output]`` list.
    """
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(
            f"{RATES_ENV_VAR} must be a JSON object mapping "
            f"model -> [input_rate, output_rate]"
        )
    rates: dict[str, tuple[float, float]] = {}
    for model, pair in data.items():
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(
                f"rate for {model!r} must be [input_rate, output_rate]"
            )
        rates[str(model)] = (float(pair[0]), float(pair[1]))
    return rates


def rates_from_env(env_var: str = RATES_ENV_VAR) -> dict[str, tuple[float, float]]:
    """Load the explicit rate map from ``env_var`` (empty dict when unset)."""
    return load_rates(os.environ.get(env_var))


@dataclass
class _CallRecord:
    """One row in the cumulative tracker. Internal — exposed via summary()."""
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class CostEstimator:
    """Cumulative cost tracker with pre-call budget gate.

    The nightly real-LLM suite uses this as a tripwire: a test calls
    ``estimate_call`` → ``would_exceed_budget`` → (if safe) issue the
    LLM call → ``record_call``. If the suite ever spends more than the
    budget, the test that would push it over short-circuits with a
    clear ``pytest.skip`` rather than charging real money.

    ``rates`` is the explicit model → (input_rate, output_rate) map; build
    it with ``rates_from_env()`` (``OL_REAL_LLM_RATES``) or pass it directly.
    An unset/empty map makes every ``estimate_call`` raise, which is the
    intended fail-closed behavior.

    Usage::

        estimator = CostEstimator(
            budget_usd=5.0, rates=rates_from_env(),
        )
        for unit in corpus:
            est = estimator.estimate_call("ark-code-latest", in_tok, out_tok)
            if estimator.would_exceed_budget(est):
                pytest.skip("budget exceeded")
            response = await pool.translate(unit)
            estimator.record_call("ark-code-latest", in_tok, out_tok)
    """
    budget_usd: float = 10.0
    rates: dict[str, tuple[float, float]] = field(default_factory=dict)
    _calls: list[_CallRecord] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Pre-call
    # ------------------------------------------------------------------ #

    def estimate_call(
        self, model: str, input_tokens: int, output_tokens: int,
    ) -> float:
        """Return estimated USD cost for a single call.

        Cost = (input_tokens / 1e6) * input_rate + (output_tokens / 1e6) * output_rate.

        Raises:
            KeyError: ``model`` is not in ``self.rates``. Fail-closed — the
                caller must supply explicit rates before spending.
            ValueError: token counts are negative.
        """
        if model not in self.rates:
            raise KeyError(
                f"No rate configured for model {model!r}. "
                f"Configured models: {sorted(self.rates)}. "
                f"Supply rates via the {RATES_ENV_VAR} env var (JSON) or "
                f"CostEstimator(rates=...). See docs/real_llm_runbook.md. "
                f"Fail-closed: refusing to guess a price."
            )
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError(
                f"Token counts must be non-negative; got input_tokens={input_tokens}, "
                f"output_tokens={output_tokens}"
            )
        input_rate, output_rate = self.rates[model]
        return (
            (input_tokens / 1_000_000) * input_rate
            + (output_tokens / 1_000_000) * output_rate
        )

    def would_exceed_budget(self, cost: float) -> bool:
        """Return True if adding ``cost`` would push cumulative spend over budget.

        Pre-call check: call ``estimate_call`` first, then this method.
        The boundary is strict (``>``), so a call that exactly hits the
        budget is allowed through.

        Raises:
            ValueError: ``cost`` is negative.
        """
        if cost < 0:
            raise ValueError(f"cost must be non-negative; got {cost}")
        return self.total_cost_usd + cost > self.budget_usd

    # ------------------------------------------------------------------ #
    # Post-call
    # ------------------------------------------------------------------ #

    def record_call(
        self, model: str, input_tokens: int, output_tokens: int,
    ) -> float:
        """Record a completed call and return the cost added to the tracker.

        Side effect: appends to ``self._calls`` so the next
        ``would_exceed_budget`` check sees the updated total. Returns
        the same value ``estimate_call`` would for the same arguments.
        """
        cost = self.estimate_call(model, input_tokens, output_tokens)
        self._calls.append(_CallRecord(model, input_tokens, output_tokens, cost))
        return cost

    # ------------------------------------------------------------------ #
    # Read-only inspection
    # ------------------------------------------------------------------ #

    @property
    def total_cost_usd(self) -> float:
        """Sum of all recorded call costs in USD. Float; small rounding OK."""
        return sum(c.cost_usd for c in self._calls)

    @property
    def call_count(self) -> int:
        """Number of completed calls recorded so far."""
        return len(self._calls)

    def summary(self) -> dict[str, Any]:
        """Return cumulative tracker state for the runbook / dashboard.

        Format::

            {
                "total_cost": <float USD>,
                "call_count": <int>,
                "by_model": {
                    "<model_name>": {"calls": <int>, "cost": <float USD>},
                    ...
                },
            }
        """
        by_model: dict[str, dict[str, float]] = {}
        for c in self._calls:
            if c.model not in by_model:
                by_model[c.model] = {"calls": 0, "cost": 0.0}
            by_model[c.model]["calls"] += 1
            by_model[c.model]["cost"] += c.cost_usd
        return {
            "total_cost": self.total_cost_usd,
            "call_count": self.call_count,
            "by_model": by_model,
        }
