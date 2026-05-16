"""Level 1 regex cleaning for XLIFF placeholder whitespace."""
import re
from typing import Tuple


def level1_regex_clean(text: str) -> Tuple[str, bool]:
    """
    Clean whitespace around XLIFF placeholders.

    - Removes leading whitespace before {{ (spaces before placeholder start)
    - Removes trailing whitespace after }} (spaces after placeholder end)
    - Moves punctuation after placeholder (e.g., ". {{" → "{{.")

    Args:
        text: Input text with potential whitespace issues around placeholders

    Returns:
        Tuple of (cleaned_text, was_modified_bool)
    """
    original = text
    count = 0

    text, n = re.subn(r'\s+\{\{', '{{', text, count=1)
    count += n

    text, n = re.subn(r'\}\}\s+', '}}', text, count=1)
    count += n

    text, n = re.subn(r'([.,!?])\s+\{\{', r'{{\1', text, count=1)
    count += n

    return text, count > 0