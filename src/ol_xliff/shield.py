import re


def shield_xliff(text: str) -> tuple[str, dict[str, str]]:
    shield_map = {}
    result = text

    tag_config = [
        ('x', r'<x[^>]*id="([^"]+)"[^>]*/>'),
        ('bx', r'<bx[^>]*id="([^"]+)"[^>]*/>'),
        ('ex', r'<ex[^>]*id="([^"]+)"[^>]*/>'),
        ('mrk', r'<mrk[^>]*id="([^"]+)"[^>]*>.*?</mrk>'),
        ('em', r'<em[^>]*id="([^"]+)"[^>]*>.*?</em>'),
        ('ph', r'<ph[^>]*id="([^"]+)"[^>]*(?:/>|>.*?</ph>)'),
        ('alayout', r'<alayout[^>]*id="([^"]+)"[^>]*>.*?</alayout>'),
    ]

    for tag_type, pattern in tag_config:
        regex = re.compile(pattern, re.DOTALL)
        matches = list(regex.finditer(result))
        for match in reversed(matches):
            tag_id = match.group(1)
            key = f'{tag_type}_{tag_id}'
            placeholder = f'{{{{_OL_XTAG_{tag_type}_{tag_id}_}}}}'
            shield_map[key] = match.group(0)
            result = result[:match.start()] + placeholder + result[match.end():]

    return result, shield_map
