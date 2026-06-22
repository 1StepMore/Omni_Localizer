"""Shared JSONL file span exporter for the OL MCP tracing module.

Tiny custom exporter — writes one line per span to a file.  Used
by ``ol_mcp.tracing``.  Kept in a separate module so the lazy
import in ``tracing.setup_tracing`` doesn't trigger SDK import
when tracing is disabled.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class _JsonlFileSpanExporter(SpanExporter):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:  # type: ignore[override]
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self._path.open("a", encoding="utf-8") as fh:
                    for span in spans:
                        try:
                            ctx = span.get_span_context()
                            parent_id = (
                                format(span.parent.span_id, "016x")
                                if span.parent is not None
                                else None
                            )
                            payload = {
                                "name": span.name,
                                "trace_id": format(ctx.trace_id, "032x"),
                                "span_id": format(ctx.span_id, "016x"),
                                "parent_span_id": parent_id,
                                "start_time_ns": span.start_time,
                                "end_time_ns": span.end_time,
                                "duration_ms": max(
                                    0.0,
                                    (span.end_time - span.start_time) / 1_000_000.0,
                                ),
                                "status": {
                                    "status_code": span.status.status_code.name
                                    if span.status is not None
                                    else "UNSET",
                                    "description": span.status.description
                                    if span.status is not None
                                    else "",
                                },
                                "attributes": dict(span.attributes or {}),
                                "resource": {
                                    k: v for k, v in (span.resource.attributes.items()
                                                      if span.resource is not None
                                                      else [])
                                },
                            }
                            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
                        except Exception:
                            continue
        except Exception:
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None
