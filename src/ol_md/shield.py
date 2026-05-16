import re
from typing import Dict, Tuple, List


def shield_markdown(md_text: str) -> Tuple[str, Dict[str, str]]:
    shield_map: Dict[str, str] = {}
    text = md_text

    code_pattern = re.compile(r'(```[\w]*\n[\s\S]*?```)')
    matches = list(code_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'\x00OL_CODE_{i:04d}\x00'
        shield_map[f'code_{i:04d}'] = match.group(1)
        text = text[:match.start()] + placeholder + text[match.end():]

    inline_code_pattern = re.compile(r'`([^`\x00]+)`')
    matches = list(inline_code_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'\x00OL_CODE_i{i:04d}\x00'
        shield_map[f'inline_code_{i:04d}'] = match.group(1)
        text = text[:match.start()] + placeholder + text[match.end():]

    math_pattern = re.compile(r'\$\$([^$]+)\$\$|\$([^$]+)\$')
    matches = list(math_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'\x00OL_MATH_{i:04d}\x00'
        shield_map[f'math_{i:04d}'] = match.group(0)
        text = text[:match.start()] + placeholder + text[match.end():]

    link_pattern = re.compile(r'(?<!!)\[([^\]]*)\]\(([^\)]+)\)')
    matches = list(link_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'\x00OL_LINK_{i:04d}\x00'
        shield_map[f'link_{i:04d}'] = match.group(0)
        text = text[:match.start()] + placeholder + text[match.end():]

    image_pattern = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
    matches = list(image_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'\x00OL_IMG_{i:04d}\x00'
        shield_map[f'image_{i:04d}'] = match.group(0)
        text = text[:match.start()] + placeholder + text[match.end():]

    html_block_pattern = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>[\s\S]*?</\1>|<([a-zA-Z][a-zA-Z0-9]*)[^>]*/>')
    matches = list(html_block_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'\x00OL_HTML_{i:04d}\x00'
        shield_map[f'html_block_{i:04d}'] = match.group(0)
        text = text[:match.start()] + placeholder + text[match.end():]

    autolink_pattern = re.compile(r'<((https?|ftp|mailto):[^\s<>]+)>')
    matches = list(autolink_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'\x00OL_AUTOLINK_{i:04d}\x00'
        shield_map[f'autolink_{i:04d}'] = match.group(0)
        text = text[:match.start()] + placeholder + text[match.end():]

    return text, shield_map


def unshield_markdown(translated_text: str, shield_map: Dict[str, str]) -> str:
    result = translated_text
    sorted_items = sorted(shield_map.items(), key=lambda x: x[0], reverse=True)

    for placeholder_id, original_content in sorted_items:
        if placeholder_id.startswith('code_'):
            idx = placeholder_id.split('_')[1]
            result = result.replace(f'\x00OL_CODE_{idx}\x00', original_content)
        elif placeholder_id.startswith('inline_code_'):
            idx = placeholder_id.split('_')[2]
            result = result.replace(f'\x00OL_CODE_i{idx}\x00', f'`{original_content}`')
        elif placeholder_id.startswith('math_'):
            idx = placeholder_id.split('_')[1]
            result = result.replace(f'\x00OL_MATH_{idx}\x00', original_content)
        elif placeholder_id.startswith('link_'):
            idx = placeholder_id.split('_')[1]
            result = result.replace(f'\x00OL_LINK_{idx}\x00', original_content)
        elif placeholder_id.startswith('image_'):
            idx = placeholder_id.split('_')[1]
            result = result.replace(f'\x00OL_IMG_{idx}\x00', original_content)
        elif placeholder_id.startswith('html_block_'):
            idx = placeholder_id.split('_')[2]
            result = result.replace(f'\x00OL_HTML_{idx}\x00', original_content)
        elif placeholder_id.startswith('autolink_'):
            idx = placeholder_id.split('_')[1]
            result = result.replace(f'\x00OL_AUTOLINK_{idx}\x00', original_content)

    return result


def get_placeholders_in_text(text: str) -> List[str]:
    pattern = re.compile(r'\x00OL_([A-Z_]+)_\d+\x00')
    matches = pattern.findall(text)
    return matches
