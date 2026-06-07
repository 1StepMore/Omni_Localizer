"""A11 — CostEstimator for real-LLM nightly runs.

Hardcoded per-1M-token USD rates for the three models configured in
``config/local.yaml`` (the MiniMax-M2.7 priority chain). The estimator
provides a **pre-call gate** (``would_exceed_budget``) so a runaway test
suite can't rack up a surprise bill, and a **post-call tracker**
(``record_call``) so cumulative spend is auditable from ``summary()``.

Design constraints:
- No I/O, no LLM calls, no env-var lookups. Pure stdlib + dataclass.
- Unknown models raise ``KeyError`` (fail-closed: better to refuse than
  to silently spend real money on an unconfigured model).
- Rates are intentionally hardcoded rather than read from the YAML
  config: a stale config must not silently mis-bill real LLM calls.
- Recalibrate quarterly — see ``docs/real_llm_runbook.md``.

Marker convention: this module is import-safe from any test in
``tests/real_llm/``. The conftest's ``cost_estimator`` fixture returns a
fresh instance per test.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Per-1M-token USD rates. (input_rate, output_rate).
# Source: provider list pricing as of 2026-05; recalibrate quarterly.
# Recalibration owner: see docs/real_llm_runbook.md.
_RATES_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    # model_name: (input_rate_usd_per_1m, output_rate_usd_per_1m)
    "MiniMax-M3": (3.0, 15.0),
    "MiniMax-M2.7": (2.0, 10.0),
    "ernie-4.5-turbo-32k": (1.0, 4.0),
}


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

    Usage::

        estimator = CostEstimator(budget_usd=5.0)
        for unit in corpus:
            est = estimator.estimate_call("MiniMax-M3", in_tok, out_tok)
            if estimator.would_exceed_budget(est):
                pytest.skip("budget exceeded")
            response = await pool.translate(unit)
            estimator.record_call("MiniMax-M3", in_tok, out_tok)
    """
    budget_usd: float = 10.0
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
            KeyError: ``model`` is not in the rate table. Fail-closed.
            ValueError: token counts are negative.
        """
        if model not in _RATES_PER_1M_TOKENS:
            raise KeyError(
                f"No rate configured for model {model!r}. "
                f"Known models: {sorted(_RATES_PER_1M_TOKENS)}. "
                f"Add a rate entry in cost_estimator._RATES_PER_1M_TOKENS."
            )
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError(
                f"Token counts must be non-negative; got input_tokens={input_tokens}, "
                f"output_tokens={output_tokens}"
            )
        input_rate, output_rate = _RATES_PER_1M_TOKENS[model]
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

    def summary(self) -> dict:
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
