try:
    from span_aligner import SpanProjector
    _has_span_aligner = True
except ImportError:
    _has_span_aligner = False

import re
import os as _os


def level2_span_align(text: str, shield_map: dict, original: str) -> str:
    if not _has_span_aligner:
        return text
    # E2E-05 fix: span-aligner's SpanProjector loads transformers (bert-base)
    # on instantiation, which fails in offline/air-gapped environments.
    # Skip level-2 when HF is offline.
    if _os.environ.get("HF_HUB_OFFLINE") == "1":
        return text
    try:
        projector = SpanProjector()
        # Try .project_spans() first (new API), fallback to .project() (old API)
        if hasattr(projector, 'project_spans'):
            src_spans = [{'start': m.start(), 'end': m.end(), 'text': m.group(0)}
                         for m in re.finditer(r'OL(B64|I|M|L|G|H|A)_([0-9a-fA-F]+)', text)]
            if not src_spans:
                return text
            projected = projector.project_spans(original, text, src_spans)
            result = text
            for span in projected:
                marker = span['text']
                start = span['start']
                result = result[:start] + marker + result[start + len(marker):]
            return result
        elif hasattr(projector, 'project'):
            return projector.project(text, shield_map, original)
        else:
            return text
    except (OSError, AttributeError):
        return text
