import re


def level4_safe_fallback(text: str, missing_placeholders: dict) -> str:
    # E2E-37 fix: never return source language as fallback
    # If no placeholders missing AND text is unchanged (source language present), return marker
    if not missing_placeholders:
        if re.search(r'[\u4e00-\u9fff]', text):
            return '[TRANSLATION_FAILED]'  # Signal that translation failed
        return text

    placeholder_strings = []
    for p_id, original_tag in missing_placeholders.items():
        placeholder_strings.append(original_tag)

    placeholder_str = ' '.join(placeholder_strings)

    unit_end_pattern = re.compile(r'</(?:trans-)?unit>')
    match = unit_end_pattern.search(text)

    if match:
        insert_pos = match.start()
        text = text[:insert_pos] + ' ' + placeholder_str + ' ' + text[insert_pos:]
    else:
        text = text.rstrip() + ' ' + placeholder_str

    # E2E-69: removed `<note from="OL">Warning:...</note>` append.
    # `<note>` is XLIFF 1.2 metadata (sibling of `<target>`, not child of `<target>`).
    # Writing it inside `<target>` lets ORF `itertext()` extract the warning string
    # and leak it into result.docx paragraphs.
    return text
