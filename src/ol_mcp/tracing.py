"""OTel tracing for the OL MCP server.

Phase 4.5: distributed tracing for the OL MCP dispatcher.  Spans
are emitted when ``OMNI_TRACING_ENABLED=1``; otherwise the
tracer is a no-op (the default) so tests see zero overhead.

The exporter is a custom JSONL file exporter that writes one
line per span to ``OMNI_TRACES_DIR/ol.jsonl`` (default
``/tmp/omni-traces/``).  No network, no stdout writes — the
JSON-RPC stream stays clean.

Wired from ``tools._call_tool`` via ``start_call_tool_span`` +
``set_span_status``.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)
from opentelemetry.context import Context

# Local module — also used by the metrics module pattern, so the
# exporter is intentionally the same as the OPP/ORF ones (a copy
# would diverge; the metrics module's exporter is a copy too —
# see the plan note about per-module isolation).
from ol_mcp._tracing_exporter import _JsonlFileSpanExporter  # noqa: F401  (lazy import below)

MODULE_NAME = "ol"
SPAN_NAME_CALL_TOOL = "ol.call_tool"
_TRACER_NAME = "ol"

ATTR_TOOL_NAME = "tool.name"
ATTR_TOOL_STATUS = "tool.status"
ATTR_TOOL_DURATION_MS = "tool.duration_ms"
ATTR_TOOL_ERROR_CODE = "tool.error_code"
ATTR_MODULE = "module"
ATTR_MODULE_VERSION = "module.version"


def is_enabled() -> bool:
    val = os.environ.get("OMNI_TRACING_ENABLED", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _traces_dir() -> Path:
    return Path(os.environ.get("OMNI_TRACES_DIR", "/tmp/omni-traces"))


_setup_lock = threading.Lock()
_setup_done = False


def setup_tracing() -> bool:
    global _setup_done
    if not is_enabled():
        return False
    with _setup_lock:
        if _setup_done:
            return True
        # Lazy import so the SDK is only required when tracing is on.
        from ol_mcp._tracing_exporter import _JsonlFileSpanExporter as _Exporter
        provider = TracerProvider()
        out = _traces_dir() / f"{MODULE_NAME}.jsonl"
        provider.add_span_processor(SimpleSpanProcessor(_Exporter(out)))
        trace.set_tracer_provider(provider)
        _setup_done = True
        return True


def get_tracer() -> Tracer:
    setup_tracing()
    return trace.get_tracer(_TRACER_NAME)


def _version() -> str:
    try:
        from ol import __version__
        return str(__version__)
    except Exception:  # expected — fallback version on import failure
        return "unknown"


def _extract_traceparent_context(traceparent: str) -> Context | None:
    """Parse a W3C ``traceparent`` string and return an OTel Context.

    Returns None if the traceparent is invalid or cannot be parsed.
    The returned Context is suitable for passing as ``context=`` to
    ``tracer.start_as_current_span(...)`` so the new span becomes a
    child of the upstream span identified by the traceparent.
    """
    if not traceparent:
        return None
    try:
        return TraceContextTextMapPropagator().extract({"traceparent": traceparent})
    except Exception:  # expected — return None on invalid traceparent
        return None


def inject_traceparent(span: Span | None) -> str | None:
    """Build a W3C ``traceparent`` string from the given span's context.

    Format: ``00-{32-hex-trace-id}-{16-hex-span-id}-{2-hex-flags}``

    Returns None if the span is None or has an invalid context.
    """
    if span is None:
        return None
    try:
        ctx = span.get_span_context()
    except Exception:  # expected — return None on span context access failure
        return None
    if ctx is None or not ctx.is_valid:
        return None
    flags = "01" if ctx.trace_flags.sampled else "00"
    return f"00-{format(ctx.trace_id, '032x')}-{format(ctx.span_id, '016x')}-{flags}"


@contextmanager
def start_call_tool_span(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    traceparent: str | None = None,
) -> Iterator[Span | None]:
    if not is_enabled():
        yield None
        return
    tracer = get_tracer()
    parent_ctx = _extract_traceparent_context(traceparent) if traceparent else None
    with tracer.start_as_current_span(SPAN_NAME_CALL_TOOL, context=parent_ctx) as span:
        try:
            span.set_attribute(ATTR_MODULE, MODULE_NAME)
            span.set_attribute(ATTR_MODULE_VERSION, _version())
            span.set_attribute(ATTR_TOOL_NAME, tool_name)
            yield span
        except Exception:
            raise


def set_span_status(
    span: Span | None,
    status: str,
    error_code: str | None = None,
    duration_ms: float | None = None,
) -> None:
    if span is None:
        return
    if not span.is_recording():
        return
    span.set_attribute(ATTR_TOOL_STATUS, status)
    if error_code is not None:
        span.set_attribute(ATTR_TOOL_ERROR_CODE, error_code)
    if duration_ms is not None:
        span.set_attribute(ATTR_TOOL_DURATION_MS, float(duration_ms))
    if status == "success":
        span.set_status(Status(StatusCode.OK))
    elif status in ("error", "rate_limited", "auth_failed"):
        span.set_status(
            Status(StatusCode.ERROR, description=error_code or status)
        )


def _tracing_file_path() -> Path:
    return _traces_dir() / f"{MODULE_NAME}.jsonl"


__all__ = [
    "MODULE_NAME",
    "SPAN_NAME_CALL_TOOL",
    "ATTR_TOOL_NAME",
    "ATTR_TOOL_STATUS",
    "ATTR_TOOL_DURATION_MS",
    "ATTR_TOOL_ERROR_CODE",
    "is_enabled",
    "setup_tracing",
    "get_tracer",
    "start_call_tool_span",
    "set_span_status",
    "inject_traceparent",
    "_extract_traceparent_context",
    "_tracing_file_path",
]
