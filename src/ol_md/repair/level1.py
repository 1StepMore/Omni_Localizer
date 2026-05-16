from typing import Tuple


def level1_regex_clean(text: str) -> Tuple[str, bool]:
    stripped = text.strip()
    if stripped != text:
        return stripped, True
    return text, False