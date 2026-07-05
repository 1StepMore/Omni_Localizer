"""Level 1 regex cleaning for XLIFF placeholder whitespace."""
import re

# Regex to detect LLM-emitted raw XML tags (<x/>, <bx/>, <ex/>)
_RAW_XML_TAG_RE = re.compile(r'<(x|bx|ex)\b[^>]*?id="([^"]+)"[^>]*/>')


def normalize_raw_xml_tags(text: str, shield_map: dict[str, str]) -> tuple[str, bool]:
    """Convert LLM-emitted raw XML tags back to shield placeholders.

    Some LLMs emit actual ``<x/>``, ``<bx/>``, or ``<ex/>`` tags instead
    of the ``{{_OL_XTAG_*_}}`` placeholders. This function detects those
    raw tags and converts them back to placeholders if their ``(type)_(id)``
    key exists in the ``shield_map``.

    Args:
        text: Text that may contain raw XML tags
        shield_map: Dict mapping ``placeholder_id`` -> ``original_tag``
                    (e.g. ``{"x_1": "<x id=\"1\"/>", "bx_2": "<bx id=\"2\" type=\"bold\"/>"}``)

    Returns:
        Tuple of ``(text_with_placeholders, was_modified_bool)``
    """
    count = 0

    def _replace_match(m: re.Match) -> str:
        nonlocal count
        tag_type = m.group(1)
        tag_id = m.group(2)
        key = f"{tag_type}_{tag_id}"
        if key in shield_map:
            count += 1
            return f"{{{{_OL_XTAG_{key}_}}}}"
        return m.group(0)

    text = _RAW_XML_TAG_RE.sub(_replace_match, text)

    return text, count > 0


def level1_regex_clean(text: str, shield_map: dict[str, str] | None = None) -> tuple[str, bool]:
    """Clean whitespace around XLIFF placeholders and strip prompt injection.

    - Converts LLM-emitted raw XML tags back to placeholders (if shield_map provided)
    - Removes leading whitespace before {{ (spaces before placeholder start)
    - Removes trailing whitespace after }} (spaces after placeholder end)
    - Moves punctuation after placeholder (e.g., ". {{" → "{{.")
    - Strips common prompt injection patterns from LLM output (e.g. "CRITICAL: Output ONLY...")

    Args:
        text: Input text with potential whitespace issues around placeholders
        shield_map: Optional dict mapping placeholder_id -> original_tag.
                    When provided, raw XML tags whose keys exist in this map
                    are normalized to placeholders before regex cleaning.

    Returns:
        Tuple of (cleaned_text, was_modified_bool)

    """
    modified = False

    # Stage 1: Normalize LLM-emitted raw XML tags back to placeholders
    if shield_map is not None:
        text, norm_modified = normalize_raw_xml_tags(text, shield_map)
        if norm_modified:
            modified = True

    count = 0

    text, n = re.subn(r'\s+\{\{', '{{', text, count=0)
    count += n

    text, n = re.subn(r'\}\}\s+', '}}', text, count=0)
    count += n

    text, n = re.subn(r'([.,!?])\s+\{\{', r'{{\1', text, count=0)
    count += n

    # E2E-65: Strip prompt injection patterns that leak into LLM output
    # Pattern matches: "CRITICAL: Output ONLY the en translation." or similar variants
    text, n = re.subn(
        r'^(?:CRITICAL|IMPORTANT|NOTE):\s*Output ONLY the \w+ translation\.\s*',
        '',
        text,
        count=0,
        flags=re.IGNORECASE,
    )
    count += n

    return text, modified or count > 0
