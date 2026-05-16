import re


def level4_safe_fallback(text: str, missing_placeholders: dict) -> str:
    if not missing_placeholders:
        return text

    placeholder_strings = []
    for p_id, original_tag in missing_placeholders.items():
        placeholder_strings.append(f'{{{{_OL_XTAG_{p_id}_}}}}')

    placeholder_str = ' '.join(placeholder_strings)

    unit_end_pattern = re.compile(r'</(?:trans-)?unit>')
    match = unit_end_pattern.search(text)

    if match:
        insert_pos = match.start()
        text = text[:insert_pos] + ' ' + placeholder_str + ' ' + text[insert_pos:]
        text = text + ' <note from="OL">Warning: Tag auto-appended at end, manual check needed</note>'
    else:
        text = text.rstrip() + ' ' + placeholder_str
        text = text + ' <note from="OL">Warning: Tag auto-appended at end, manual check needed</note>'

    return text