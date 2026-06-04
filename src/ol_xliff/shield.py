import re


def _shield_bx_ex_pairs(text: str) -> tuple[str, dict[str, str]]:
    """Shield bx/ex as conceptual begin/end pairs.

    XLIFF 1.x bx and ex are self-closing markers that together wrap a
    span. Shielding them individually (as the self_closing pass does)
    loses the pairing — if the LLM drops one half, the placeholder set
    looks complete but the span is broken. By collapsing matched pairs
    into a single placeholder, L4's missing-placeholder detector can
    catch the case where exactly one half is restored.
    """
    shield_map: dict[str, str] = {}

    bx_re = re.compile(r'<bx[^>]*\bid="([^"]+)"[^>]*/>')
    ex_re = re.compile(r'<ex[^>]*\bid="([^"]+)"[^>]*/>')

    bx_by_id: dict[str, re.Match] = {}
    for m in bx_re.finditer(text):
        bx_by_id.setdefault(m.group(1), m)

    ex_by_id: dict[str, re.Match] = {}
    for m in ex_re.finditer(text):
        ex_by_id.setdefault(m.group(1), m)

    pairs: list[tuple[int, int, int, str]] = []
    for tag_id, bx in bx_by_id.items():
        ex = ex_by_id.get(tag_id)
        if ex is not None and ex.start() > bx.end():
            pairs.append((bx.start(), ex.end(), bx.end() - bx.start(), tag_id))

    pairs.sort(key=lambda p: p[0], reverse=True)

    for bx_start, ex_end, _span, tag_id in pairs:
        key = f'bx_ex_{tag_id}'
        placeholder = f'{{{{_OL_XTAG_{key}_}}}}'
        shield_map[key] = text[bx_start:ex_end]
        text = text[:bx_start] + placeholder + text[ex_end:]

    return text, shield_map


def _shield_paired_tag(text: str, tag_type: str) -> tuple[str, dict[str, str]]:
    """Shield paired tags (mrk, em, ph, alayout) handling nesting correctly."""
    shield_map = {}
    original = text

    open_pat = rf'<{tag_type}([^>]*)id="([^"]+)"([^>]*)>'

    openings = []
    for m in re.finditer(open_pat, original):
        openings.append({'start': m.start(), 'end': m.end(), 'id': m.group(2)})

    if not openings:
        return text, shield_map

    open_id_map = {o['start']: o['id'] for o in openings}

    stack = []
    matched = []
    i = 0
    while i < len(original):
        open_pos = original.find(f'<{tag_type}', i)
        close_pos = original.find(f'</{tag_type}>', i)

        if close_pos == -1:
            break

        if open_pos != -1 and open_pos < close_pos:
            if open_pos in open_id_map:
                stack.append(open_pos)
            i = open_pos + 1
        else:
            if stack:
                open_pos = stack.pop()
                tag_id = open_id_map[open_pos]
                matched.append((open_pos, close_pos + len(f'</{tag_type}>'), tag_id))
            i = close_pos + 1

    matched.sort(key=lambda x: x[0], reverse=True)

    pos = len(original)
    result = []
    for start, end, tag_id in reversed(matched):
        key = f'{tag_type}_{tag_id}'
        shield_map[key] = original[start:end]
        result.append(original[end:pos])
        result.append(f'{{{{_OL_XTAG_{key}_}}}}')
        pos = start
    result.append(original[:pos])

    return ''.join(reversed(result)), shield_map


def shield_xliff(text: str) -> tuple[str, dict[str, str]]:
    shield_map = {}
    result = text

    # Self-closing tags: x, bx, ex — shielded individually by id.
    self_closing = [
        ('x', r'<x[^>]*id="([^"]+)"[^>]*/>'),
        ('bx', r'<bx[^>]*id="([^"]+)"[^>]*/>'),
        ('ex', r'<ex[^>]*id="([^"]+)"[^>]*/>'),
    ]

    for tag_type, pattern in self_closing:
        regex = re.compile(pattern, re.DOTALL)
        matches = list(regex.finditer(result))
        for match in reversed(matches):
            tag_id = match.group(1)
            key = f'{tag_type}_{tag_id}'
            placeholder = f'{{{{_OL_XTAG_{tag_type}_{tag_id}_}}}}'
            shield_map[key] = match.group(0)
            result = result[:match.start()] + placeholder + result[match.end():]

    # Paired tags: mrk, em, ph, alayout, g, ign - use stack-based matching for nesting
    paired = ['mrk', 'em', 'ph', 'alayout', 'g', 'ign']

    for tag_type in paired:
        result, paired_map = _shield_paired_tag(result, tag_type)
        shield_map.update(paired_map)

    return result, shield_map
