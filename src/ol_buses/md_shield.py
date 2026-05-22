"""MD special token shielding and restoration for Omni-Localizer."""
import re


def shield_special_tokens(md_text: str) -> tuple[str, dict[str, str]]:
    """Shield code blocks, formulas, and other special content with placeholders.

    Args:
        md_text: Raw markdown text

    Returns:
        Tuple of (text_with_placeholders, shield_map)

    """
    shield_map = {}
    text = md_text

    # Shield code blocks: ```language\ncode\n```
    code_pattern = re.compile(r'(```[\w]*\n[\s\S]*?```)')
    matches = list(code_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'{{{{_OL_CODE_{i:04d}_}}}}'
        shield_map[f'code_{i:04d}'] = match.group(1)
        text = text[:match.start()] + placeholder + text[match.end():]

    # Shield inline code: `code`
    inline_code_pattern = re.compile(r'`([^`]+)`')
    matches = list(inline_code_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'{{{{_OL_CODE_i{i:04d}_}}}}'
        shield_map[f'inline_code_{i:04d}'] = match.group(1)
        text = text[:match.start()] + placeholder + text[match.end():]

    # Shield math expressions: $math$ and $$math$$
    math_pattern = re.compile(r'\$\$([^$]+)\$\$|\$([^$]+)\$')
    matches = list(math_pattern.finditer(text))
    for i, match in enumerate(reversed(matches)):
        placeholder = f'{{{{_OL_MATH_{i:04d}_}}}}'
        shield_map[f'math_{i:04d}'] = match.group(0)
        text = text[:match.start()] + placeholder + text[match.end():]

    return text, shield_map

def unshield_special_tokens(translated_text: str, shield_map: dict[str, str]) -> str:
    """Restore special tokens from shield map to translated text.

    Args:
        translated_text: Text with placeholders
        shield_map: Mapping of placeholder ID to original content

    Returns:
        Text with special tokens restored

    """
    result = translated_text

    # Restore in reverse order to handle overlapping placeholders
    for placeholder_id, original_content in sorted(shield_map.items(), reverse=True):
        if placeholder_id.startswith('code_'):
            result = result.replace(f'{{{{_OL_CODE_{placeholder_id.split("_")[1]}_}}}}', original_content)
        elif placeholder_id.startswith('inline_code_'):
            # Inline code restoration
            idx = placeholder_id.split('_')[2]
            result = result.replace(f'{{{{_OL_CODE_i{idx}_}}}}', f'`{original_content}`')
        elif placeholder_id.startswith('math_'):
            result = result.replace(f'{{{{_OL_MATH_{placeholder_id.split("_")[1]}_}}}}', original_content)

    return result
