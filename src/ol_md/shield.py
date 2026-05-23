import base64
import re
import uuid

CODE_PATTERN = re.compile(r'(```[\w]*\n[\s\S]*?```)')
INLINE_CODE_PATTERN = re.compile(r'`([^`]+)`')
MATH_PATTERN = re.compile(r'\$\$([^$]+)\$\$|\$([^$]+)\$')
LINK_PATTERN = re.compile(r'(?<!!)\[([^\]]*)\]\(([^\)]+)\)')
IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
HTML_BLOCK_PATTERN = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>[\s\S]*?</\1>|<([a-zA-Z][a-zA-Z0-9]*)[^>]*/>')
AUTOLINK_PATTERN = re.compile(r'<((https?|ftp|mailto):[^\s<>]+)>')
PLACEHOLDER_PATTERN = re.compile(r'OL(B64|I|M|L|G|H|A)_([0-9a-fA-F]+)')


def _b64_encode(content: str) -> str:
    return base64.b64encode(content.encode('utf-8')).decode('ascii')


def _b64_decode(content: str) -> str:
    return base64.b64decode(content.encode('ascii')).decode('utf-8')


def _make_marker(prefix: str) -> str:
    uid = str(uuid.uuid4()).replace('-', '')[:8]
    return f"OL{prefix.upper()}_{uid}_"


def shield_markdown(md_text: str) -> tuple[str, dict[str, str]]:
    shield_map: dict[str, str] = {}
    text = md_text

    matches = list(CODE_PATTERN.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('CODE')
        shield_map[marker] = _b64_encode(match.group(1))
        text = text[:match.start()] + marker + text[match.end():]

    matches = list(INLINE_CODE_PATTERN.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('ICODE')
        shield_map[marker] = _b64_encode(match.group(1))
        text = text[:match.start()] + marker + text[match.end():]

    matches = list(MATH_PATTERN.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('MATH')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    matches = list(LINK_PATTERN.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('LINK')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    matches = list(IMAGE_PATTERN.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('IMG')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    matches = list(HTML_BLOCK_PATTERN.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('HTML')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    matches = list(AUTOLINK_PATTERN.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('AUTO')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    return text, shield_map


def unshield_markdown(translated_text: str, shield_map: dict[str, str]) -> str:
    result = translated_text
    sorted_items = sorted(shield_map.items(), key=lambda x: len(x[0]), reverse=True)

    for marker, encoded_content in sorted_items:
        original_content = _b64_decode(encoded_content)
        if marker.startswith('OLCODE_'):
            result = result.replace(marker, original_content)
        elif marker.startswith('OLICODE_'):
            result = result.replace(marker, f'`{original_content}`')
        elif marker.startswith('OLMATH_') or marker.startswith('OLLINK_') or marker.startswith('OLIMG_') or marker.startswith('OLHTML_') or marker.startswith('OLAUTO_'):
            result = result.replace(marker, original_content)

    return result


def get_placeholders_in_text(text: str) -> list[str]:
    matches = PLACEHOLDER_PATTERN.findall(text)
    return matches
