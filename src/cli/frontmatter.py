"""YAML frontmatter generation and related helpers for OL CLI."""
from __future__ import annotations

import re as _re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _escape_yaml_value(value: str) -> str:
    """Escape special characters in YAML string values to prevent injection."""
    if any(c in value for c in ":#\n"):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _validate_lang_code(code: str) -> str:
    """Validate ISO 639-1 language code."""
    if not _re.match(r"^[a-z]{2}(-[A-Z]{2})?$", code):
        raise ValueError(f"Invalid language code: {code}")
    return code


def _escape_xml(value: str) -> str:
    """Escape special characters in XML using single-pass character-by-character approach.

    This prevents double-encoding issues that occur with naive sequential .replace() calls.
    For example: '&lt;' would become '&amp;lt;' with sequential replacement.
    """
    result = []
    for c in value:
        if c == "&":
            result.append("&amp;")
        elif c == "<":
            result.append("&lt;")
        elif c == ">":
            result.append("&gt;")
        elif c == '"':
            result.append("&quot;")
        elif c == "'":
            result.append("&apos;")
        else:
            result.append(c)
    return "".join(result)


def _get_ol_version() -> str:
    """Get OL version from module-level __version__."""
    from ol_cli import __version__
    return __version__


def _generate_frontmatter(
    source_lang: str,
    target_lang: str,
    original_filename: str,
    ol_version: str | None = None,
    request_id: str | None = None,
    extra_frontmatter: dict | None = None,
) -> str:
    """Generate YAML frontmatter header with translation metadata.

    Args:
        source_lang: Source language code (ISO 639-1)
        target_lang: Target language code (ISO 639-1)
        original_filename: Original input filename
        ol_version: OL version number
        request_id: Optional UUID for end-to-end tracing (B2).
        extra_frontmatter: Optional dict of extra keys to merge before the
            closing --- (e.g. email_headers from OPP manifest).

    Returns:
        YAML frontmatter string with leading and trailing ---

    Raises:
        ValueError: If language codes are invalid

    """
    if ol_version is None:
        ol_version = _get_ol_version()
    # Validate inputs to prevent injection
    source_lang = _validate_lang_code(source_lang)
    target_lang = _validate_lang_code(target_lang)
    escaped_filename = _escape_yaml_value(original_filename)

    timestamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    frontmatter_lines = [
        "---",
        f"source_lang: {source_lang}",
        f"target_lang: {target_lang}",
        f"original_file: {escaped_filename}",
        'processor: "OL"',
        f'version: "{ol_version}"',
        f"translated_at: {timestamp}",
    ]
    if request_id:
        frontmatter_lines.append(f"request_id: {request_id}")

    # Merge extra frontmatter keys (e.g. email_headers from OPP manifest)
    if extra_frontmatter:
        for key, value in extra_frontmatter.items():
            if isinstance(value, dict):
                frontmatter_lines.append(f"{key}:")
                for sub_key, sub_value in value.items():
                    escaped_val = _escape_yaml_value(str(sub_value))
                    frontmatter_lines.append(f"  {sub_key}: {escaped_val}")
            else:
                escaped_val = _escape_yaml_value(str(value))
                frontmatter_lines.append(f"{key}: {escaped_val}")

    frontmatter_lines.extend(["---", ""])

    return "\n".join(frontmatter_lines)


def _generate_skip_frontmatter(
    source_lang: str,
    target_lang: str,
    original_filename: str,
    ol_version: str | None = None,
    detected_source_lang: str | None = None,
) -> str:
    if ol_version is None:
        ol_version = _get_ol_version()
    source_lang = _validate_lang_code(source_lang)
    target_lang = _validate_lang_code(target_lang)
    escaped_filename = _escape_yaml_value(original_filename)

    timestamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    frontmatter_lines = [
        "---",
        f"source_lang: {source_lang}",
        f"target_lang: {target_lang}",
        f"original_file: {escaped_filename}",
        'processor: "OL"',
        f'version: "{ol_version}"',
        f"translated_at: {timestamp}",
        "skipped: true",
        'skip_reason: "already_in_target_language"',
    ]
    if detected_source_lang:
        frontmatter_lines.append(f"detected_source_lang: {detected_source_lang}")

    frontmatter_lines.append("---")
    frontmatter_lines.append("")

    return "\n".join(frontmatter_lines)


def _extract_opp_metadata(input_path: Path) -> dict:
    """Extract request_id and email_headers from OPP manifest.json (W2.1).

    Looks for a sibling ``*_manifest.json``, extracts ``request_id`` and
    ``metadata`` fields (where email headers live). Falls back to scanning
    the XLIFF header for a ``request_id=...`` note.

    Returns:
        dict with keys ``request_id`` (str|None) and ``email_headers`` (dict|None).
    """
    result: dict = {"request_id": None, "email_headers": None}
    manifest_candidate = input_path.parent / f"{input_path.stem}_manifest.json"
    if manifest_candidate.exists():
        try:
            data = __import__("json").loads(manifest_candidate.read_text(encoding="utf-8"))
            rid = data.get("request_id")
            if rid:
                result["request_id"] = rid
            metadata = data.get("metadata")
            if isinstance(metadata, dict):
                headers = {}
                sender = metadata.get("sender")
                if sender:
                    headers["from"] = str(sender)
                to_val = metadata.get("to")
                if to_val is not None:
                    headers["to"] = str(to_val)
                subject = metadata.get("subject")
                if subject:
                    headers["subject"] = str(subject)
                cc_val = metadata.get("cc")
                if cc_val is not None:
                    headers["cc"] = str(cc_val)
                date_val = metadata.get("date")
                if date_val:
                    headers["date"] = str(date_val)
                if headers:
                    result["email_headers"] = headers
            return result
        except (OSError, ValueError):
            pass
    if input_path.suffix.lower() in (".xlf", ".xliff"):
        try:
            content = input_path.read_text(encoding="utf-8")
            m = _re.search(r"request_id=([0-9a-fA-F-]{36})", content)
            if m:
                result["request_id"] = m.group(1)
        except OSError:
            pass
    return result


def _extract_request_id(input_path: Path) -> str | None:
    """Backward-compat wrapper for _extract_opp_metadata (B2)."""
    return _extract_opp_metadata(input_path)["request_id"]


def _build_xliff_header_note(src_lang: str, tgt_lang: str, request_id: str | None = None) -> str:
    """Build XLIFF-compliant header note element."""
    validated_src = _validate_lang_code(src_lang)
    validated_tgt = _validate_lang_code(tgt_lang)
    note_text = f"Translated from {validated_src} to {validated_tgt} by OL"
    if request_id:
        note_text += f" request_id={request_id}"
    return f'<header>\n    <note from="OL">{_escape_xml(note_text)}</note>\n  </header>'


def _inject_xliff_header(repaired: str, header_note: str) -> str:
    """Inject header note into XLIFF output at correct position."""
    # Insert header after <xliff ...> opening tag, before <file> element
    if "<file" in repaired:
        return repaired.replace("<file", header_note + "\n  <file", 1)
    return repaired  # No <file> element found, skip header injection
