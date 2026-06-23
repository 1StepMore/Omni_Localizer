import re

CODE_PATTERN = re.compile(r'(```[\w]*\n[\s\S]*?```)')
INLINE_CODE_PATTERN = re.compile(r'`([^`]+)`')
# E2E-77: require a LaTeX marker (backslash command, ^, or _) inside
# the dollar-delimited run so currency text like "Price: $5.99 and $10
# each" is not matched as math.
MATH_PATTERN = re.compile(
    r'\$\$([^$]+)\$\$'
    r'|'
    r'\$([^$\n]+?[\\\^_][^$]*?)\$'
)
LINK_PATTERN = re.compile(r'(?<!!)\[([^\]]*)\]\(([^\)]+)\)')
IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
HTML_BLOCK_PATTERN = re.compile(
    r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>[\s\S]*?</\1>|<([a-zA-Z][a-zA-Z0-9]*)[^>]*/>'
)
AUTOLINK_PATTERN = re.compile(r'<((https?|ftp|mailto):[^\s<>]+)>')

# E2E-78: switch from \x00OL_TYPE_NNNN\x00 (NUL-delimited) to
# [OL:TYPE:NNNN] (ASCII-delimited). Real LLMs frequently strip or
# mangle the NUL control character, which silently dropped shielded
# content during unshield. The new format is unambiguous vs the
# markdown link / image grammar (no `!` prefix, no `](` close).
PLACEHOLDER_PATTERN = re.compile(r'\[OL:([A-Z_]+):(\d{4})\]')

# Map from shield_map key prefix to marker type name
_KEY_TO_TYPE = {
    'code': 'CODE',
    'inline_code': 'CODE_i',
    'math': 'MATH',
    'link': 'LINK',
    'image': 'IMG',
    'html_block': 'HTML',
    'autolink': 'AUTOLINK',
}


def _make_marker(type_name: str, index: int) -> str:
    return f"[OL:{type_name}:{index:04d}]"


def _key_to_marker(key: str) -> str:
    prefix, _, index_str = key.rpartition('_')
    type_name = _KEY_TO_TYPE.get(prefix, prefix.upper())
    return _make_marker(type_name, int(index_str))


def shield_markdown(md_text: str) -> tuple[str, dict[str, str]]:
    """Shield MD constructs that must survive translation untouched.

    Returns (shielded_text, shield_map) where shield_map maps short keys
    (e.g. 'link_0000') to the original content that was replaced.
    """
    shield_map: dict[str, str] = {}
    text = md_text
    counters = {k: 0 for k in _KEY_TO_TYPE}

    # 1. Fenced code blocks
    for match in reversed(list(CODE_PATTERN.finditer(text))):
        idx = counters['code']
        counters['code'] += 1
        key = f"code_{idx:04d}"
        marker = _make_marker('CODE', idx)
        shield_map[key] = match.group(1)
        text = text[:match.start()] + marker + text[match.end():]

    # 2. Inline code
    for match in reversed(list(INLINE_CODE_PATTERN.finditer(text))):
        idx = counters['inline_code']
        counters['inline_code'] += 1
        key = f"inline_code_{idx:04d}"
        marker = _make_marker('CODE_i', idx)
        shield_map[key] = match.group(1)
        text = text[:match.start()] + marker + text[match.end():]

    # 3. Math (block $$..$$ and inline $..$)
    for match in reversed(list(MATH_PATTERN.finditer(text))):
        idx = counters['math']
        counters['math'] += 1
        key = f"math_{idx:04d}"
        marker = _make_marker('MATH', idx)
        shield_map[key] = match.group(0)
        text = text[:match.start()] + marker + text[match.end():]

    # 4. Links
    for match in reversed(list(LINK_PATTERN.finditer(text))):
        idx = counters['link']
        counters['link'] += 1
        key = f"link_{idx:04d}"
        marker = _make_marker('LINK', idx)
        shield_map[key] = match.group(0)
        text = text[:match.start()] + marker + text[match.end():]

    # 5. Images
    for match in reversed(list(IMAGE_PATTERN.finditer(text))):
        idx = counters['image']
        counters['image'] += 1
        key = f"image_{idx:04d}"
        marker = _make_marker('IMG', idx)
        shield_map[key] = match.group(0)
        text = text[:match.start()] + marker + text[match.end():]

    # 6. HTML blocks
    for match in reversed(list(HTML_BLOCK_PATTERN.finditer(text))):
        idx = counters['html_block']
        counters['html_block'] += 1
        key = f"html_block_{idx:04d}"
        marker = _make_marker('HTML', idx)
        shield_map[key] = match.group(0)
        text = text[:match.start()] + marker + text[match.end():]

    # 7. Autolinks
    for match in reversed(list(AUTOLINK_PATTERN.finditer(text))):
        idx = counters['autolink']
        counters['autolink'] += 1
        key = f"autolink_{idx:04d}"
        marker = _make_marker('AUTOLINK', idx)
        shield_map[key] = match.group(0)
        text = text[:match.start()] + marker + text[match.end():]

    return text, shield_map


def unshield_markdown(translated_text: str, shield_map: dict[str, str]) -> str:
    """Restore the original content for each shielded marker in the text.

    E2E-78: missing markers are appended at the end under an
    OL_WARN:missing_shields HTML comment so content is never silently
    lost.
    """
    import logging
    log = logging.getLogger("ol_md.shield")
    result = translated_text
    missing: list[tuple[str, str]] = []
    for key, original_content in shield_map.items():
        marker = _key_to_marker(key)
        if marker in result:
            result = result.replace(marker, original_content)
        else:
            missing.append((key, original_content))
    if missing:
        warn_lines = ["<!-- OL_WARN:missing_shields " + ",".join(k for k, _ in missing) + " -->"]
        for _, content in missing:
            warn_lines.append(content)
        warn_block = "\n\n" + "\n".join(warn_lines) + "\n"
        result = result + warn_block
        log.warning(
            "unshield_markdown: %d marker(s) missing from LLM output; "
            "appended originals to end with OL_WARN comment",
            len(missing),
        )
    return result


def get_placeholders_in_text(text: str) -> list[str]:
    """Return the list of placeholder type names found in text."""
    return [m.group(1) for m in PLACEHOLDER_PATTERN.finditer(text)]
