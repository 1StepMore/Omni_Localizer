import logging
import re

_logger = logging.getLogger(__name__)

_MARKER_RE = re.compile(r'\[OL:[A-Za-z_]+:\d{4}\]')
_SENTENCE_END_RE = re.compile(r'([.!?])\s*$')


def level4_safe_fallback(text: str, missing_placeholders: dict) -> str:
    if not missing_placeholders:
        return text + '\n<!-- OL_WARN: Tag_auto_appended -->'

    placeholder_strings = [missing_placeholders[k] for k in missing_placeholders]

    surviving_markers = list(_MARKER_RE.finditer(text))
    if surviving_markers:
        insert_pos = surviving_markers[-1].end()
        text = (
            text[:insert_pos]
            + '\n'
            + '\n'.join(placeholder_strings)
            + text[insert_pos:]
        )
    else:
        match = _SENTENCE_END_RE.search(text)
        if match:
            insert_pos = match.start() + 1
            text = (
                text[:insert_pos]
                + '\n'
                + '\n'.join(placeholder_strings)
                + text[insert_pos:]
            )
        else:
            text = text.rstrip() + '\n' + '\n'.join(placeholder_strings)

    _logger.warning("level4_safe_fallback: inserted %d missing placeholder(s)", len(missing_placeholders))
    return text + '\n<!-- OL_WARN: Tag_auto_appended -->'
