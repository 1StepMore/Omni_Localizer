import re


def level4_safe_fallback(text: str, missing_placeholders: dict) -> str:
    pattern = re.compile(r'([.!?])\s*$')
    match = pattern.search(text)
    if match:
        insert_pos = match.start() + 1
        text = text[:insert_pos] + '\n' + '\n'.join(missing_placeholders.keys()) + text[insert_pos:]
    else:
        text = text.rstrip() + '\n' + '\n'.join(missing_placeholders.keys())
    return text + '\n<!-- OL_WARN: Tag_auto_appended -->'