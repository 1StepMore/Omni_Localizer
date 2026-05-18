import re
import base64
from typing import Dict, Tuple, List


def _b64_encode(content: str) -> str:
    return base64.b64encode(content.encode('utf-8')).decode('ascii')


def _b64_decode(content: str) -> str:
    return base64.b64decode(content.encode('ascii')).decode('utf-8')


def shield_markdown(md_text: str) -> Tuple[str, Dict[str, str]]:
    shield_map: Dict[str, str] = {}
    text = md_text

    code_pattern = re.compile(r'(```[\w]*\n[\s\S]*?```)')
    matches = list(code_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'OLB64_{i:04d}'
        shield_map[f'code_{i:04d}'] = _b64_encode(match.group(1))
        text = text[:match.start()] + placeholder + text[match.end():]

    inline_code_pattern = re.compile(r'`([^`]+)`')
    matches = list(inline_code_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'OLB64_I{i:04d}'
        shield_map[f'inline_code_{i:04d}'] = _b64_encode(match.group(1))
        text = text[:match.start()] + placeholder + text[match.end():]

    math_pattern = re.compile(r'\$\$([^$]+)\$\$|\$([^$]+)\$')
    matches = list(math_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'OLB64_M{i:04d}'
        shield_map[f'math_{i:04d}'] = _b64_encode(match.group(0))
        text = text[:match.start()] + placeholder + text[match.end():]

    link_pattern = re.compile(r'(?<!!)\[([^\]]*)\]\(([^\)]+)\)')
    matches = list(link_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'OLB64_L{i:04d}'
        shield_map[f'link_{i:04d}'] = _b64_encode(match.group(0))
        text = text[:match.start()] + placeholder + text[match.end():]

    image_pattern = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
    matches = list(image_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'OLB64_G{i:04d}'
        shield_map[f'image_{i:04d}'] = _b64_encode(match.group(0))
        text = text[:match.start()] + placeholder + text[match.end():]

    html_block_pattern = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>[\s\S]*?</\1>|<([a-zA-Z][a-zA-Z0-9]*)[^>]*/>')
    matches = list(html_block_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'OLB64_H{i:04d}'
        shield_map[f'html_block_{i:04d}'] = _b64_encode(match.group(0))
        text = text[:match.start()] + placeholder + text[match.end():]

    autolink_pattern = re.compile(r'<((https?|ftp|mailto):[^\s<>]+)>')
    matches = list(autolink_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'OLB64_A{i:04d}'
        shield_map[f'autolink_{i:04d}'] = _b64_encode(match.group(0))
        text = text[:match.start()] + placeholder + text[match.end():]

    return text, shield_map


def unshield_markdown(translated_text: str, shield_map: Dict[str, str]) -> str:
    result = translated_text
    sorted_items = sorted(shield_map.items(), key=lambda x: x[0], reverse=True)

    for placeholder_id, encoded_content in sorted_items:
        idx = placeholder_id.split('_')[-1]
        original_content = _b64_decode(encoded_content)
        if placeholder_id.startswith('code_'):
            result = result.replace(f'OLB64_{idx}', original_content)
        elif placeholder_id.startswith('inline_code_'):
            result = result.replace(f'OLB64_I{idx}', f'`{original_content}`')
        elif placeholder_id.startswith('math_'):
            result = result.replace(f'OLB64_M{idx}', original_content)
        elif placeholder_id.startswith('link_'):
            result = result.replace(f'OLB64_L{idx}', original_content)
        elif placeholder_id.startswith('image_'):
            result = result.replace(f'OLB64_G{idx}', original_content)
        elif placeholder_id.startswith('html_block_'):
            result = result.replace(f'OLB64_H{idx}', original_content)
        elif placeholder_id.startswith('autolink_'):
            result = result.replace(f'OLB64_A{idx}', original_content)

    return result


def get_placeholders_in_text(text: str) -> List[str]:
    pattern = re.compile(r'OL(B64|I|M|L|G|H|A)_(\d+)')
    matches = pattern.findall(text)
    return matches
