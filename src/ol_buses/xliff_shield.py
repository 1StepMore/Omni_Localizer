"""XLIFF tag extraction and restoration for Omni-Localizer."""
import re
from typing import Dict, Tuple


def extract_tags(source_xml: str) -> Dict[str, str]:
    """
    Extract <x/>, <bx/>, <ex/> tags from XLIFF source.

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


def restore_tags(target_text: str, tag_map: Dict[str, str]) -> str:
    """
    Restore tags from placeholder map to target text.

    Args:
        target_text: Text with placeholders like {{_OL_XTAG_x_1_}}
        tag_map: Mapping of placeholder ID to original tag

    Returns:
        Text with tags restored
    """
    result = target_text
    for placeholder, tag in tag_map.items():
        result = result.replace(f'{{{{_OL_XTAG_{placeholder}_}}}}', tag)
    return result


def replace_tags_with_placeholders(source_xml: str) -> Tuple[str, Dict[str, str]]:
    """
    Replace XML tags in source with placeholders.

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