"""XLIFF tag extraction and restoration for Omni-Localizer."""
import re


def extract_tags(source_xml: str) -> dict[str, str]:
    """Extract <x/>, <bx/>, <ex/> tags from XLIFF source.

    Returns:
        Dict mapping placeholder ID to original tag

    """
    tags = {}

    # Match standalone tags: <x id="1" type="bold"/>
    tag_pattern = re.compile(r'<x[^>]*id="([^"]+)"[^>]*/>')
    for match in tag_pattern.finditer(source_xml):
        tag_id = match.group(1)
        tags[f'x_{tag_id}'] = match.group(0)

    # Match begin tags: <bx id="1" type="bold"/>
    bx_pattern = re.compile(r'<bx[^>]*id="([^"]+)"[^>]*/>')
    for match in bx_pattern.finditer(source_xml):
        tag_id = match.group(1)
        tags[f'bx_{tag_id}'] = match.group(0)

    # Match end tags: <ex id="1" type="bold"/>
    ex_pattern = re.compile(r'<ex[^>]*id="([^"]+)"[^>]*/>')
    for match in ex_pattern.finditer(source_xml):
        tag_id = match.group(1)
        tags[f'ex_{tag_id}'] = match.group(0)

    return tags


# ULTRAREADY-FIX (2026-06-08): the LLM sometimes emits inline tag
# placeholders in a non-canonical format ({{OLXTAGbx1}} instead of
# {{_OL_XTAG_bx_1_}}) AND additionally appends the actual <bx>/<ex>
# tags at the end (entity-escaped as &lt;...&gt;). The bus's existing
# restore_tags only matches the canonical {{_OL_XTAG_*_}} format, so
# both forms leak through into the XLIFF output and end up as literal
# text in the final DOCX. This regex matches the LLM's format AND
# strips the erroneously-appended actual tags.
_OLXTAG_NEW_RE = re.compile(r'\{\{OLXTAG(bx|ex|x)(\d+)\}\}')
_BX_APPENDED_RE = re.compile(r'&lt;bx[^>]*id="[^"]*"[^>]*/&gt;')
_EX_APPENDED_RE = re.compile(r'&lt;ex[^>]*id="[^"]*"[^>]*/&gt;')
_X_APPENDED_RE = re.compile(r'&lt;x[^>]*id="[^"]*"[^>]*/&gt;')


def restore_tags(target_text: str, tag_map: dict[str, str]) -> str:
    """Restore tags from placeholder map to target text.

    ULTRAREADY-FIX (2026-06-08): now also handles the LLM's
    non-canonical placeholder format ``{{OLXTAG<type><id>}}`` and
    strips the LLM's erroneously-appended actual <bx>/<ex>/<x> tags
    so the final DOCX doesn't end up with literal placeholder text
    or duplicated markup.

    Args:
        target_text: Text with placeholders like {{_OL_XTAG_x_1_}}
                      or {{OLXTAGbx1}}, possibly with actual
                      &lt;bx.../&gt; tags appended.
        tag_map: Mapping of placeholder ID (e.g. ``bx_1``) to original tag.

    Returns:
        Text with placeholders replaced and erroneously-appended
        actual tags removed.
    """
    result = target_text

    # Format 1: bus's canonical {{_OL_XTAG_<key>_}} format
    for placeholder, tag in tag_map.items():
        result = result.replace(f"{{{{_OL_XTAG_{placeholder}_}}}}", tag)

    # Format 2: LLM's non-canonical {{OLXTAG<type><id>}} format
    def _replace_new(m: re.Match) -> str:
        tag_type = m.group(1)
        tag_id = m.group(2)
        return tag_map.get(f"{tag_type}_{tag_id}", m.group(0))
    result = _OLXTAG_NEW_RE.sub(_replace_new, result)

    # Strip the LLM's erroneously-appended actual tags (entity-escaped
    # because they came from the LLM as literal markup, e.g. "&lt;bx .../&gt;")
    result = _BX_APPENDED_RE.sub("", result)
    result = _EX_APPENDED_RE.sub("", result)
    result = _X_APPENDED_RE.sub("", result)

    return result


def replace_tags_with_placeholders(source_xml: str) -> tuple[str, dict[str, str]]:
    """Replace XML tags in source with placeholders.

    Args:
        source_xml: Raw XLIFF source with tags

    Returns:
        Tuple of (text_with_placeholders, shield_map)

    """
    shield_map = {}
    text = source_xml

    # Process in order: x, bx, ex tags
    for tag_type in ['x', 'bx', 'ex']:
        pattern = re.compile(rf'<{tag_type}[^>]*id="([^"]+)"[^>]*/>')
        matches = list(pattern.finditer(text))

        # Process in reverse order to maintain positions
        for match in reversed(matches):
            tag_id = match.group(1)
            placeholder = f'{{{{_OL_XTAG_{tag_type}_{tag_id}_}}}}'
            shield_map[f'{tag_type}_{tag_id}'] = match.group(0)
            text = text[:match.start()] + placeholder + text[match.end():]

    return text, shield_map
