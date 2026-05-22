

def level1_regex_clean(text: str) -> tuple[str, bool]:
    stripped = text.strip()
    if stripped != text:
        return stripped, True
    return text, False
