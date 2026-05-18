import re


def level4_safe_fallback(text: str, missing_placeholders: dict) -> str:
    pattern = re.compile(r'([.!?])\s*$')
    match = pattern.search(text)
    placeholder_strings = []
    for k in missing_placeholders.keys():
        prefix = "ICODE" if k.startswith("inline_code_") else k.split('_')[0].upper()
        suffix = k.split('_')[-1]
        placeholder_strings.append(f'\x00OL_{prefix}_{suffix}\x00')
    if match:
        insert_pos = match.start() + 1
        text = text[:insert_pos] + '\n' + '\n'.join(placeholder_strings) + text[insert_pos:]
    else:
        text = text.rstrip() + '\n' + '\n'.join(placeholder_strings)
    return text + '\n<!-- OL_WARN: Tag_auto_appended -->'