import re

_INJECTION_RE = re.compile(
    r'^(?:CRITICAL|IMPORTANT|NOTE):\s*Output ONLY the \w+ translation\.\s*',
    re.IGNORECASE,
)


def level1_regex_clean(text: str) -> tuple[str, bool]:
    count = 0

    text, n = _INJECTION_RE.subn('', text, count=1)
    count += n

    stripped = text.strip()
    if stripped != text:
        return stripped, True
    return text, count > 0