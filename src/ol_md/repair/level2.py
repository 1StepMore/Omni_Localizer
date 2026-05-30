import re

from ..shield import PLACEHOLDER_PATTERN

try:
    from span_aligner import SpanProjector
    _has_span_aligner = True
except (ImportError, OSError):
    _has_span_aligner = False


def level2_span_align(text: str, shield_map: dict, original: str) -> str:
    if not _has_span_aligner:
        return text
    try:
        projector = SpanProjector()

        src_spans = []
        for match in PLACEHOLDER_PATTERN.finditer(text):
            src_spans.append({
                'start': match.start(),
                'end': match.end(),
                'text': match.group(0)
            })

        if not src_spans:
            return text

        projected = projector.project_spans(original, text, src_spans)

        result = text
        for span in projected:
            marker = span['text']
            start = span['start']
            result = result[:start] + marker + result[start + len(marker):]

        return result
    except (OSError, AttributeError):
        return text