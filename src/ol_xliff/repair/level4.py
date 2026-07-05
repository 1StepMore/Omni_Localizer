import re


_PLACEHOLDER_PATTERN = re.compile(r'\{\{_OL_[A-Z]+_[^}]+\}\}')
_INLINE_TAG_PATTERN = re.compile(
    r'<(x|bx|ex|ph|mrk)\b[^>]*?(?:/>|></\1>)', re.DOTALL
)
_UNIT_END_PATTERN = re.compile(r'</(?:trans-)?unit>')
_BX_EX_PATTERN = re.compile(r'^([be]x)_(\d+)$')


def level4_safe_fallback(text: str, missing_placeholders: dict[str, str]) -> tuple[str, list[str]]:
    if not missing_placeholders:
        return text, []

    # Separate bx/ex pairs from non-paired placeholders.  bx_N and
    # ex_N with equal N form a pair; both halves share the same group.
    bx_ex_pairs: dict[int, dict[str, str]] = {}
    non_paired: dict[str, str] = {}

    for pid, value in missing_placeholders.items():
        m = _BX_EX_PATTERN.match(pid)
        if m:
            tag_type = m.group(1)
            num = int(m.group(2))
            if num not in bx_ex_pairs:
                bx_ex_pairs[num] = {}
            bx_ex_pairs[num][tag_type] = value
        else:
            non_paired[pid] = value

    values_to_insert: list[str] = []
    inserted_ids: list[str] = []

    # For each bx/ex pair: if a half's tag is already in text (restored
    # by L3), skip it to avoid duplication.  Insert only truly missing halves.
    for num in sorted(bx_ex_pairs):
        halves = bx_ex_pairs[num]
        bx_val = halves.get('bx')
        ex_val = halves.get('ex')

        if bx_val is not None and bx_val not in text:
            values_to_insert.append(bx_val)
            inserted_ids.append(f'bx_{num}')
        if ex_val is not None and ex_val not in text:
            values_to_insert.append(ex_val)
            inserted_ids.append(f'ex_{num}')

    # Non-paired placeholders inserted as before.
    for pid, value in non_paired.items():
        values_to_insert.append(value)
        inserted_ids.append(pid)

    if not values_to_insert:
        return text, []

    placeholder_str = ' '.join(values_to_insert)

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
        for p_id in inserted_ids
    ]

    return text, warnings
