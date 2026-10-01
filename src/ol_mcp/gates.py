"""Quality-gate outcome reporting for the OL MCP translate tools (issue #115).

The OL#56 gates are best-effort by design: a gate that *warns* must never
fail the translation, and its ``OL_WARN: <CODE>`` strings keep flowing into
the tool's ``warnings`` field unchanged.

A gate pass that never *executed* is a different thing. It used to be
downgraded to a single log line, so the caller received
``{"translated": ..., "warnings": []}`` — byte-identical to "the gates ran
and everything passed". This module owns the one thing that closes that
gap: a machine-checkable record of whether the gates ran, surfaced twice
per outcome so either style of caller can act on it:

* a namespaced entry in ``warnings`` (``OL_GATES_NOT_RUN`` /
  ``OL_GATES_SKIPPED``), matching how every other non-fatal condition is
  surfaced to MCP callers (cf. ``OL_PATH_DENIED: ...`` in
  ``translate_xliff.py``);
* a ``quality_gates`` object in the response envelope, for callers that
  branch on structured data instead of parsing strings.

``status`` is the single discriminator:

* ``ran`` — the gates executed (with or without ``OL_WARN`` output);
* ``not_run`` — the caller asked for gates and they never ran: the config
  is missing or failed to load, or the gate invocation raised. The
  ``reason`` says which.
* ``skipped`` — the caller explicitly opted out via ``no_quality_gates``.
  Deliberate, and deliberately distinguishable from ``not_run``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)

from ol_config.loader import load_config
from ol_config.schema import QualityGateConfig

# Namespaced ``warnings`` markers, so a caller can filter for them without
# matching on free text. Kept distinct from each other so an explicit
# opt-out never reads like a failure.
NOT_RUN_MARKER = "OL_GATES_NOT_RUN"
SKIPPED_MARKER = "OL_GATES_SKIPPED"

# Reason for a caller-requested skip — the parameter name is quoted so the
# response tells the caller exactly which switch turned the gates off.
SKIP_REASON = "disabled by caller (no_quality_gates=true)"


class GateStatus(str, Enum):
    """Whether the post-translation quality gates executed."""

    RAN = "ran"
    NOT_RUN = "not_run"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class GateOutcome:
    """Machine-checkable record of one post-translation quality-gate pass.

    Immutable: an outcome is a fact about a past run, and both translate
    tools attach it to the response after the fact.
    """

    status: GateStatus
    reason: str = ""

    @property
    def marker(self) -> str | None:
        """The namespaced ``warnings`` entry for a non-``ran`` outcome.

        ``None`` for ``ran`` — a gate pass that executed needs no marker,
        keeping the pre-existing "gates ran, warnings present" response
        shape unchanged.
        """
        match self.status:
            case GateStatus.RAN:
                return None
            case GateStatus.NOT_RUN:
                return f"{NOT_RUN_MARKER}: {self.reason}"
            case GateStatus.SKIPPED:
                return f"{SKIPPED_MARKER}: {self.reason}"

    def as_response_field(self) -> dict[str, Any]:
        """The ``quality_gates`` object for the MCP response envelope.

        ``reason`` is always present (``""`` when there is nothing to
        explain) so callers can read it without a ``.get()`` fallback.
        """
        return {"status": self.status.value, "reason": self.reason}


def _record(outcome: GateOutcome, warnings: list[str]) -> GateOutcome:
    """Append the outcome's marker to ``warnings`` (if any) and return it."""
    marker = outcome.marker
    if marker is not None:
        warnings.append(marker)
    return outcome


def run_gates(
    config_path: str,
    warnings: list[str],
    run: Callable[[QualityGateConfig], None],
) -> GateOutcome:
    """Load the quality-gate config, invoke ``run`` under it, report the outcome.

    ``run`` receives the resolved :class:`QualityGateConfig` and is
    responsible for collecting its own gate output (``run_quality_gates``
    results extend ``warnings`` for ``translate_md_text``;
    ``warnings_per_unit`` for ``translate_xliff``).

    Every failure mode — config missing, config invalid, ``run`` raising —
    is reported as ``GateStatus.NOT_RUN`` with a reason, never swallowed
    into a log line (issue #115). Gate *warnings* are untouched: they stay
    non-fatal by design.
    """
    try:
        cfg, _ = load_config(config_path)
    except Exception as load_err:
        _logger.warning("Quality gate config load failed: %s", load_err)
        return _record(
            GateOutcome(GateStatus.NOT_RUN, f"config_load_failed: {load_err}"), warnings,
        )

    try:
        run(cfg.quality_gates)
    except Exception as gate_err:
        _logger.warning("Quality gate invocation failed: %s", gate_err)
        return _record(
            GateOutcome(GateStatus.NOT_RUN, f"gate_invocation_failed: {gate_err}"), warnings,
        )

    return _record(GateOutcome(GateStatus.RAN), warnings)


def skip_gates(warnings: list[str]) -> GateOutcome:
    """Report a caller-requested skip (``no_quality_gates=true``).

    Separate from :func:`run_gates` so an explicit opt-out can never be
    mistaken for — or silently degraded into — the broken-config case.
    """
    return _record(GateOutcome(GateStatus.SKIPPED, SKIP_REASON), warnings)