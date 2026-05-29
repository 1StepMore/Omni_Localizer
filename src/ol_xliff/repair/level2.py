try:
    from span_aligner import SpanProjector
    _has_span_aligner = True
except ImportError:
    _has_span_aligner = False

import os as _os


def level2_span_align(text: str, shield_map: dict, original: str) -> str:
    if not _has_span_aligner:
        return text
    # E2E-05 fix: span-aligner's SpanProjector loads transformers (bert-base)
    # on instantiation, which fails in offline/air-gapped environments.
    # Skip level-2 when HF is offline.
    if _os.environ.get("HF_HUB_OFFLINE") == "1":
        return text
    projector = SpanProjector()
    return projector.project(text, shield_map, original)
