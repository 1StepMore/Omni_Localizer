"""Compatibility shim; the implementation lives in ol_core.repair.level2."""

from ol_core.repair.level2 import (
    SpanProjector,
    _has_span_aligner,
    level2_span_align,
)

__all__ = ["SpanProjector", "_has_span_aligner", "level2_span_align"]
