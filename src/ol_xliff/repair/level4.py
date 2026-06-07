import re


_PLACEHOLDER_PATTERN = re.compile(r'\{\{_OL_[A-Z]+_[^}]+\}\}')
_INLINE_TAG_PATTERN = re.compile(
    r'<(x|bx|ex|ph|mrk)\b[^>]*?(?:/>|></\1>)', re.DOTALL
)
_UNIT_END_PATTERN = re.compile(r'</(?:trans-)?unit>')


def level4_safe_fallback(text: str, missing_placeholders: dict) -> tuple[str, list[str]]:
    if not missing_placeholders:
        return text, []

    placeholder_str = ' '.join(missing_placeholders.values())

    # POST_MORTEM ORF-5: insert at best-effort position instead of always
    # at end-of-unit. Try, in order:
    #  1. After the last inline tag already present (preserves grouping).
    #  2. After the last surviving {{_OL_*_*}} placeholder (preserves
    #     the original position intent if restoration already moved some).
    #  3. Before </unit> / </trans-unit> (preserves unit structure).
    #  4. Append to text (last resort; e.g. empty input).
    insert_pos: int | None = None
    strategy = "append-to-text"

    if text:
        for match in reversed(list(_INLINE_TAG_PATTERN.finditer(text))):
            insert_pos = match.end()
            strategy = "after-inline-tag"
            break
        if insert_pos is None:
            for match in reversed(list(_PLACEHOLDER_PATTERN.finditer(text))):
                insert_pos = match.end()
                strategy = "after-placeholder"
                break
        if insert_pos is None:
            unit_end = _UNIT_END_PATTERN.search(text)
            if unit_end:
                insert_pos = unit_end.start()
                strategy = "before-unit-end"

    if insert_pos is None:
        text = (text.rstrip() + ' ' if text else '') + placeholder_str
    else:
        text = text[:insert_pos] + ' ' + placeholder_str + ' ' + text[insert_pos:]

    warnings = [
        f"Tag auto-appended ({strategy}), manual check needed: {p_id}"
        for p_id in missing_placeholders
    ]

    return text, warnings
