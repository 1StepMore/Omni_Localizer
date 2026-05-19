import re
import base64
import uuid
from typing import Dict, Tuple, List


def _b64_encode(content: str) -> str:
    return base64.b64encode(content.encode('utf-8')).decode('ascii')


def _b64_decode(content: str) -> str:
    return base64.b64decode(content.encode('ascii')).decode('utf-8')


def _make_marker(prefix: str) -> str:
    uid = str(uuid.uuid4()).replace('-', '')[:8]
    return f"OL{prefix.upper()}_{uid}_"


def shield_markdown(md_text: str) -> Tuple[str, Dict[str, str]]:
    shield_map: Dict[str, str] = {}
    text = md_text

    code_pattern = re.compile(r'(```[\w]*\n[\s\S]*?```)')
    matches = list(code_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('CODE')
        shield_map[marker] = _b64_encode(match.group(1))
        text = text[:match.start()] + marker + text[match.end():]

    inline_code_pattern = re.compile(r'`([^`]+)`')
    matches = list(inline_code_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('ICODE')
        shield_map[marker] = _b64_encode(match.group(1))
        text = text[:match.start()] + marker + text[match.end():]

    math_pattern = re.compile(r'\$\$([^$]+)\$\$|\$([^$]+)\$')
    matches = list(math_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('MATH')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    link_pattern = re.compile(r'(?<!!)\[([^\]]*)\]\(([^\)]+)\)')
    matches = list(link_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('LINK')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    image_pattern = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
    matches = list(image_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('IMG')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    html_block_pattern = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>[\s\S]*?</\1>|<([a-zA-Z][a-zA-Z0-9]*)[^>]*/>')
    matches = list(html_block_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('HTML')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    autolink_pattern = re.compile(r'<((https?|ftp|mailto):[^\s<>]+)>')
    matches = list(autolink_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        marker = _make_marker('AUTO')
        shield_map[marker] = _b64_encode(match.group(0))
        text = text[:match.start()] + marker + text[match.end():]

    return text, shield_map


def unshield_markdown(translated_text: str, shield_map: Dict[str, str]) -> str:
    result = translated_text
    sorted_items = sorted(shield_map.items(), key=lambda x: len(x[0]), reverse=True)

    for marker, encoded_content in sorted_items:
        original_content = _b64_decode(encoded_content)
        if marker.startswith('OLCODE_'):
            result = result.replace(marker, original_content)
        elif marker.startswith('OLICODE_'):
            result = result.replace(marker, f'`{original_content}`')
        elif marker.startswith('OLMATH_'):
            result = result.replace(marker, original_content)
        elif marker.startswith('OLLINK_'):
            result = result.replace(marker, original_content)
        elif marker.startswith('OLIMG_'):
            result = result.replace(marker, original_content)
        elif marker.startswith('OLHTML_'):
            result = result.replace(marker, original_content)
        elif marker.startswith('OLAUTO_'):
            result = result.replace(marker, original_content)

    return result


def get_placeholders_in_text(text: str) -> List[str]:
    pattern = re.compile(r'OL(B64|I|M|L|G|H|A)_([0-9a-fA-F]+)')
    matches = pattern.findall(text)
    return matches
