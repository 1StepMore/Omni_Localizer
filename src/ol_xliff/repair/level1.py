"""Level 1 regex cleaning for XLIFF placeholder whitespace."""
import re


def level1_regex_clean(text: str) -> tuple[str, bool]:
    """Clean whitespace around XLIFF placeholders and strip prompt injection.

    - Removes leading whitespace before {{ (spaces before placeholder start)
    - Removes trailing whitespace after }} (spaces after placeholder end)
    - Moves punctuation after placeholder (e.g., ". {{" → "{{.")
    - Strips common prompt injection patterns from LLM output (e.g. "CRITICAL: Output ONLY...")

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

    # E2E-65: Strip prompt injection patterns that leak into LLM output
    # Pattern matches: "CRITICAL: Output ONLY the en translation." or similar variants
    text, n = re.subn(
        r'^(?:CRITICAL|IMPORTANT|NOTE):\s*Output ONLY the \w+ translation\.\s*',
        '',
        text,
        count=0,
        flags=re.IGNORECASE,
    )
    count += n

    return text, count > 0
