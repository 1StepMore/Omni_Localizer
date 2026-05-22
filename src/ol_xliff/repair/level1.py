"""Level 1 regex cleaning for XLIFF placeholder whitespace."""
import re


def level1_regex_clean(text: str) -> tuple[str, bool]:
    """Clean whitespace around XLIFF placeholders.

    - Removes leading whitespace before {{ (spaces before placeholder start)
    - Removes trailing whitespace after }} (spaces after placeholder end)
    - Moves punctuation after placeholder (e.g., ". {{" → "{{.")

    Args:
        text: Input text with potential whitespace issues around placeholders

    Returns:
        Tuple of (cleaned_text, was_modified_bool)

    """
    count = 0

    text, n = re.subn(r'\s+\{\{', '{{', text, count=0)
    count += n

    text, n = re.subn(r'\}\}\s+', '}}', text, count=0)
    count += n

    text, n = re.subn(r'([.,!?])\s+\{\{', r'{{\1', text, count=0)
    count += n

    return text, count > 0
