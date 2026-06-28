"""Per-module Prometheus metrics for the OL MCP server.

Phase 4.5: module-prefixed metrics (ol_*) emitted to a local
Prometheus text file under ``OMNI_METRICS_DIR`` (default
``/tmp/omni-metrics/ol.prom``). The shared ``omni_metrics`` package
(``omni_mcp_tool_calls_total`` etc.) is used for the suite-wide
aggregator; this module adds the OL-specific counters and
histograms that the production-readiness plan requires.

Wired from ``tools._call_tool``. All write paths are best-effort —
metrics emission must NEVER raise into the request path (would
break the JSON-RPC stream).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    write_to_textfile,
)

_logger = logging.getLogger(__name__)

# Per-module registry — kept isolated from the global ``REGISTRY`` that
# ``omni_metrics`` uses, so the two metric families don't collide when
# both run in the same process (tests, docs/examples).
REGISTRY = CollectorRegistry()

# Histogram buckets required by the production-readiness plan.
_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

OL_REQUESTS_TOTAL = Counter(
    "ol_requests_total",
    "Total OL MCP requests, by tool_name and status.",
    ["tool_name", "status"],
    registry=REGISTRY,
)

OL_REQUEST_DURATION_SECONDS = Histogram(
    "ol_request_duration_seconds",
    "OL MCP request duration in seconds, by tool_name.",
    ["tool_name"],
    buckets=_DURATION_BUCKETS,
    registry=REGISTRY,
)

OL_TRANSLATIONS_TOTAL = Counter(
    "ol_translations_total",
    "Total OL translations, by source_lang, target_lang, and mode "
    "('md' for translate_md_text/batch_translate_texts, "
    "'xliff' for translate_xliff).",
    ["source_lang", "target_lang", "mode"],
    registry=REGISTRY,
)

# Status label values — stable strings; do not rename.
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_AUTH_FAILED = "auth_failed"


def _metrics_dir() -> Path:
    return Path(os.environ.get("OMNI_METRICS_DIR", "/tmp/omni-metrics"))


_write_lock = threading.Lock()


def _emit() -> None:
    try:
        outdir = _metrics_dir()
        outdir.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            write_to_textfile(str(outdir / "ol.prom"), REGISTRY)
    except Exception:
        _logger.debug("Failed to write Prometheus metrics", exc_info=True)


def _classify_mode(tool_name: str) -> str:
    if tool_name in ("translate_xliff",):
        return "xliff"
    if tool_name in ("translate_md_text", "batch_translate_texts"):
        return "md"
    return "other"


def record_request(
    tool_name: str,
    status: str,
    duration_seconds: float,
) -> None:
    try:
        OL_REQUESTS_TOTAL.labels(tool_name=tool_name, status=status).inc()
        OL_REQUEST_DURATION_SECONDS.labels(tool_name=tool_name).observe(
            max(0.0, float(duration_seconds))
        )
        _emit()
    except Exception:
        _logger.debug("Failed to write Prometheus metrics", exc_info=True)


def record_translation(
    source_lang: str,
    target_lang: str,
    mode: str,
) -> None:
    """Record a single OL translation. ``mode`` is ``"md"`` or ``"xliff"``."""
    try:
        OL_TRANSLATIONS_TOTAL.labels(
            source_lang=source_lang or "unknown",
            target_lang=target_lang or "unknown",
            mode=mode or "other",
        ).inc()
        _emit()
    except Exception:
        _logger.debug("Failed to write Prometheus metrics", exc_info=True)


def record_request_from_arguments(
    tool_name: str,
    arguments: dict[str, Any] | None,
    status: str,
    duration_seconds: float,
) -> None:
    """Convenience: record a request and, for translation tools, also
    bump ``OL_TRANSLATIONS_TOTAL`` (success-only; failures shouldn't
    inflate the translation counter).
    """
    record_request(tool_name, status, duration_seconds)
    if status != STATUS_SUCCESS:
        return
    args = arguments or {}
    if tool_name in ("translate_md_text", "translate_xliff", "batch_translate_texts"):
        record_translation(
            source_lang=str(args.get("source_lang", "unknown")),
            target_lang=str(args.get("target_lang", "unknown")),
            mode=_classify_mode(tool_name),
        )


def time_block() -> "_OLBlockTimer":
    return _OLBlockTimer()


class _OLBlockTimer:
    __slots__ = ("_t0",)

    def __init__(self) -> None:
        self._t0 = time.monotonic()

    def seconds(self) -> float:
        return max(0.0, time.monotonic() - self._t0)


__all__ = [
    "REGISTRY",
    "OL_REQUESTS_TOTAL",
    "OL_REQUEST_DURATION_SECONDS",
    "OL_TRANSLATIONS_TOTAL",
    "STATUS_SUCCESS",
    "STATUS_ERROR",
    "STATUS_RATE_LIMITED",
    "STATUS_AUTH_FAILED",
    "record_request",
    "record_translation",
    "record_request_from_arguments",
    "time_block",
]
