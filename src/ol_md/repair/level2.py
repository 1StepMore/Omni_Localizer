try:
    from span_aligner import SpanProjector
    _has_span_aligner = True
except ImportError:
    _has_span_aligner = False


import logging
import re

_logger = logging.getLogger(__name__)

# Regex matching {{_OL_XTAG_<name>_}} shield placeholders
_SHIELD_RE = re.compile(r"\{\{_OL_XTAG_([^}]+)_\}\}")


def _shield_to_xml(text: str) -> tuple[str, dict[str, str]]:
    """Convert {{_OL_XTAG_...}} placeholders to XML-style <ol_...> tags.

    Returns (xml_text, reverse_map) where reverse_map maps the XML tag
    string back to the original shield placeholder.
    """
    reverse: dict[str, str] = {}

    def _replacer(m: re.Match) -> str:
        shield = m.group(0)
        inner = m.group(1)
        safe = inner.replace("/", "_slash_").replace("-", "_dash_")
        xml_tag = f"<ol_{safe}>"
        reverse[xml_tag] = shield
        closing_xml = f"</ol_{safe}>"
        closing_shield = "{{_OL_XTAG_/" + inner + "_}}" if not inner.startswith("/") else None
        if closing_shield:
            reverse[closing_xml] = closing_shield
        return xml_tag

    return _SHIELD_RE.sub(_replacer, text), reverse


def _xml_to_shield(text: str, reverse: dict[str, str]) -> str:
    """Convert XML-style <ol_...> tags back to {{_OL_XTAG_...}} placeholders."""
    for xml_tag, shield in reverse.items():
        text = text.replace(xml_tag, shield)
    return text


def _get_shield_tag_names(text: str) -> list[str]:
    """Extract unique shield tag names from text for allowed_tags."""
    names = set()
    for m in _SHIELD_RE.finditer(text):
        inner = m.group(1)
        safe = inner.replace("/", "_slash_").replace("-", "_dash_")
        names.add(f"ol_{safe}")
    return sorted(names)


def level2_span_align(
    text: str, shield_map: dict, original: str
) -> tuple[str, bool]:
    """Apply L2 span alignment to `text`. Returns (text, l2_applied).

    l2_applied=True: span_aligner was available AND the L2 repair
    succeeded; `text` is the L2-repaired output.
    l2_applied=False: span_aligner unavailable OR L2 raised; `text`
    is the upstream text (graceful degradation).
    """
    if not _has_span_aligner:
        return text, False
    import os
    old_offline = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        original_xml, rev_map = _shield_to_xml(original)
        text_xml, _ = _shield_to_xml(text)
        allowed = _get_shield_tag_names(original)

        projector = SpanProjector()
        aligned, _ = projector.project_tagged_text(
            original_xml, text_xml, allowed_tags=allowed, max_gap=2,
        )
        result = _xml_to_shield(aligned, rev_map)
        return result, result != text
    except Exception as e:
        _logger.warning(
            "L2 span_aligner unavailable, falling back to upstream text: %s", e
        )
        return text, False
    finally:
        if old_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = old_offline
