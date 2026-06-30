"""Shared warning extraction logic for CLI commands.

Provides regex patterns and structured extraction used by both
``extract-warnings`` and ``generate-report --extract-from``.

Without this module, the two CLIs would each maintain their own copy
of the regex patterns — a maintenance hazard when patterns drift.

This module is the single source of truth for OL warning markers in
MD and XLIFF formats.
"""
from __future__ import annotations

import re
from pathlib import Path

from ol_lqa.report import WarningEntry

# MD: HTML comments like <!-- OL_WARN: missing_shields key1,key2 -->
MD_WARN_RE = re.compile(r"<!--\s*OL_WARN:\s*([^>]+?)\s*-->")

# XLIFF: <note from="OL">some text</note>
XLIFF_WARN_RE = re.compile(r'<note\s+from="OL"[^>]*>([^<]+?)</note>')


def extract_warnings_from_file(file_path: str) -> list[WarningEntry]:
    """Read *file_path* and extract OL_WARN markers as WarningEntry objects.

    Supports MD (``<!-- OL_WARN: ... -->``) and XLIFF
    (``<note from="OL">...</note>``) formats. Each match becomes one
    WarningEntry. Returns an empty list if no markers found.

    Field mapping for the WarningEntry:
        - file_path: the input file path
        - line_number: 1-based line number where the match occurs
        - warning_type: "md" for HTML comments, "xliff" for XML notes
        - severity: always "info" (regex doesn't capture severity)
        - model: empty string (not available from markers)
        - cost: 0.0 (not available from markers)
        - source_text: full match (e.g., the full comment or note element)
        - target_text: empty
        - reference: extracted message text (the inner content)
    """
    content = Path(file_path).read_text(encoding="utf-8")
    entries: list[WarningEntry] = []

    for match in MD_WARN_RE.finditer(content):
        line_number = content[: match.start()].count("\n") + 1
        entries.append(WarningEntry(
            file_path=file_path,
            line_number=line_number,
            warning_type="md",
            severity="info",
            model="",
            cost=0.0,
            source_text=match.group(0),
            target_text="",
            reference=match.group(1).strip(),
        ))

    for match in XLIFF_WARN_RE.finditer(content):
        line_number = content[: match.start()].count("\n") + 1
        entries.append(WarningEntry(
            file_path=file_path,
            line_number=line_number,
            warning_type="xliff",
            severity="info",
            model="",
            cost=0.0,
            source_text=match.group(0),
            target_text="",
            reference=match.group(1).strip(),
        ))

    return entries
