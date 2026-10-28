"""Field-level JSON tolerance for LLM responses (Issue #130).

Background
----------
Both ``ModelPool.judge()`` and ``ModelPool.profile()`` parse free-form LLM
output into JSON. Historically each call site had its own *text-level*
fallback and neither had any *field-level* tolerance:

* judge stripped fences, called ``json.loads`` and, on failure, scraped
  four numbers with a regex; still failing, it hard-returned all-zero
  (fail-closed).
* profile stripped fences, called ``json.loads`` and otherwise returned
  ``{"raw_response": ...}``.

A 2026-10-17 incident on a sibling pipeline showed why that is not enough: a model
emitted ``"bridge_score": wiggle`` (a bare identifier in value position),
which made the *whole document* fail to parse.  Re-asking the same
question with the same parameters reproduced the failure four times.

This module centralises the repair strategy so both call sites share one
implementation:

1. :func:`repair_json_text` — pure text-level syntax repair.  It never
   guesses semantics; a value it cannot understand syntactically becomes
   ``null``.
2. :func:`salvage_fields` — field-level tolerance.  A field whose value
   does not match the expected type and cannot be losslessly converted is
   set to ``None`` and reported in ``invalid_fields``.
3. :func:`repair_json_once` — a single LLM-assisted second attempt.  The
   caller injects ``llm_call`` so the helper stays testable and reuses
   whichever transport (judging / profiling) is appropriate.

The module is ``stdlib`` only.
"""
from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable

__all__ = [
    "repair_json_text",
    "salvage_fields",
    "repair_json_once",
]


# ---------------------------------------------------------------------------
# Text-level repair (pure, syntax only)
# ---------------------------------------------------------------------------

_FENCE_OPEN_RE = re.compile(r"^```[\w-]*\s*")
_FENCE_CLOSE_RE = re.compile(r"\s*```\s*$")
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_KEYWORDS = frozenset({"true", "false", "null"})
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
# A value that sits directly after a delimiter and is not a quoted string.
# The character class deliberately stops at structural characters so nested
# objects/arrays are left untouched.
_BARE_VALUE_RE = re.compile(r'(?<=[:,\[])(\s*)([^,}\]:\[\{"]+?)(\s*)(?=[,\}\]])')


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = _FENCE_OPEN_RE.sub("", t)
        t = _FENCE_CLOSE_RE.sub("", t)
    return t.strip()


def _normalize_single_quotes(text: str) -> str:
    """Convert ``'...'`` strings to ``"..."`` while respecting double quotes.

    Everything inside an existing double-quoted string is copied verbatim,
    so an apostrophe (``"it's"``) is never mistaken for a string delimiter.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                c = text[i]
                out.append(c)
                i += 1
                if c == "\\" and i < n:
                    out.append(text[i])
                    i += 1
                elif c == '"':
                    break
            continue
        if ch == "'":
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    if nxt == "'":
                        buf.append("'")
                        i += 2
                        continue
                    buf.append(c)
                    buf.append(nxt)
                    i += 2
                    continue
                if c == "'":
                    i += 1
                    break
                buf.append(c)
                i += 1
            inner = "".join(buf).replace('"', '\\"')
            out.append('"' + inner + '"')
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_outermost_json(text: str) -> str:
    """Return the outermost balanced ``{...}`` / ``[...]`` substring.

    String-aware, so braces inside string literals do not affect depth.  If
    no opening brace/bracket exists the (stripped) input is returned as-is.
    """
    start = None
    opener = ""
    for i, ch in enumerate(text):
        if ch == "{" or ch == "[":
            start = i
            opener = ch
            break
    if start is None:
        return text.strip()

    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def _iter_segments(text: str):
    """Yield ``(is_string, segment)`` pairs, splitting on double-quoted strings."""
    i = 0
    n = len(text)
    start = 0
    while i < n:
        if text[i] == '"':
            if i > start:
                yield False, text[start:i]
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            yield True, text[i:j]
            i = j
            start = j
        else:
            i += 1
    if start < n:
        yield False, text[start:]


def _null_bare_value(match: re.Match[str]) -> str:
    token = match.group(2).strip()
    if not token:
        return match.group(0)
    lowered = token.lower()
    if lowered in _KEYWORDS:
        return match.group(0)
    if _NUMBER_RE.fullmatch(token):
        return match.group(0)
    return match.group(1) + "null" + match.group(3)


def _fix_non_string_segment(segment: str) -> str:
    segment = _TRAILING_COMMA_RE.sub(r"\1", segment)
    segment = re.sub(
        r"[-+]?\b(?:Infinity|NaN|inf|nan)\b",
        "null",
        segment,
        flags=re.IGNORECASE,
    )
    segment = re.sub(r"(?<=[:,\[\s])\+(\d)", r"\1", segment)
    segment = re.sub(r"^\+(\d)", r"\1", segment)
    return _BARE_VALUE_RE.sub(_null_bare_value, segment)


def repair_json_text(text: str) -> str:
    """Best-effort syntactic repair of an LLM JSON blob.

    Transformations (in order):

    1. strip markdown code fences
    2. normalise single-quoted strings to double quotes
    3. extract the outermost ``{...}`` / ``[...]``
    4. drop trailing commas, map ``NaN``/``Infinity`` to ``null``, drop a
       leading ``+`` from numbers and replace bare identifiers in value
       position with ``null`` (``"score": wiggle`` → ``"score": null``).

    Only syntax is repaired — no semantic guessing.  The returned string is
    not guaranteed to be valid JSON; callers still pass it to ``json.loads``.
    """
    if not text:
        return ""
    repaired = _strip_fences(str(text))
    repaired = _normalize_single_quotes(repaired)
    repaired = _extract_outermost_json(repaired)
    repaired = "".join(
        seg if is_str else _fix_non_string_segment(seg)
        for is_str, seg in _iter_segments(repaired)
    )
    return repaired


# ---------------------------------------------------------------------------
# Field-level tolerance
# ---------------------------------------------------------------------------

_NO_CONVERT = object()


def _parse_number(value: str) -> float | None:
    """Parse a numeric string, tolerating a trailing percent sign."""
    t = value.strip()
    if t.endswith("%"):
        t = t[:-1].strip()
    if not t:
        return None
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


def _coerce(value: Any, expected: type) -> Any:
    """Losslessly coerce ``value`` to ``expected`` or return ``_NO_CONVERT``.

    Numeric expectations preserve the original ``int``/``float`` type so that
    already-valid ints are not widened to floats (which would break callers
    comparing exact dicts).  Strings, lists and bools are handled
    conservatively; anything that would require guessing is rejected.
    """
    if expected is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "false"):
                return lowered == "true"
        return _NO_CONVERT

    if expected in (int, float):
        if isinstance(value, bool):
            return _NO_CONVERT
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            parsed = _parse_number(value)
            if parsed is None:
                return _NO_CONVERT
            if expected is int and isinstance(parsed, float) and parsed.is_integer():
                return int(parsed)
            return parsed
        return _NO_CONVERT

    if expected is str:
        return value if isinstance(value, str) else _NO_CONVERT

    if expected is list:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return _NO_CONVERT

    if expected is dict:
        return value if isinstance(value, dict) else _NO_CONVERT

    return value if isinstance(value, expected) else _NO_CONVERT


def salvage_fields(
    payload: dict, expectations: dict[str, type],
) -> tuple[dict, list[str]]:
    """Return ``(payload, invalid_fields)`` with unusable fields nulled out.

    For every field in ``expectations`` that is present in ``payload``:

    * a value already of the expected type is kept;
    * a value that can be losslessly converted (``"90%"`` → ``90.0``) is
      converted;
    * anything else — including an explicit ``None`` — is set to ``None`` and
      its name is appended to ``invalid_fields``.

    Fields absent from ``payload`` are left absent (the caller decides
    whether absence is fatal).  The input dict is not mutated.
    """
    if not isinstance(payload, dict):
        return payload, []

    result = dict(payload)
    invalid: list[str] = []
    for field, expected in expectations.items():
        if field not in result:
            continue
        value = result[field]
        if value is None:
            if field not in invalid:
                invalid.append(field)
            continue
        converted = _coerce(value, expected)
        if converted is _NO_CONVERT:
            result[field] = None
            if field not in invalid:
                invalid.append(field)
        else:
            result[field] = converted
    return result, invalid


# ---------------------------------------------------------------------------
# One-shot LLM-assisted repair
# ---------------------------------------------------------------------------

_REPAIR_PROMPT_TEMPLATE = (
    "The following text was supposed to be a single JSON object but could "
    "not be parsed.\n"
    "Parse error: {error}\n\n"
    "Fix ONLY the JSON syntax (quoting, commas, unquoted/invalid values). "
    "Do NOT change any of the values that are already valid.\n"
    "Output ONLY the corrected JSON object — no prose, no markdown fences.\n\n"
    "Broken output:\n{raw}"
)

_MAX_RAW_CHARS = 4000


def _build_repair_prompt(raw_text: str, error: BaseException) -> str:
    return _REPAIR_PROMPT_TEMPLATE.format(
        error=f"{type(error).__name__}: {error}",
        raw=raw_text[:_MAX_RAW_CHARS],
    )


async def repair_json_once(
    raw_text: str,
    error: BaseException,
    llm_call: Callable[[str], Any],
) -> Any:
    """Ask the LLM exactly once to return corrected JSON and parse it.

    ``llm_call`` is injected by the caller and receives the repair prompt;
    it may be a plain callable returning ``str`` or an async callable
    returning an awaitable.  The repaired text goes through
    :func:`repair_json_text` before ``json.loads``.

    Raises the underlying ``json.JSONDecodeError`` (or any transport error
    from ``llm_call``) if the second attempt is still unusable — the caller
    is expected to fail-closed.
    """
    prompt = _build_repair_prompt(raw_text, error)
    output = llm_call(prompt)
    if inspect.isawaitable(output):
        output = await output
    if output is None:
        output = ""
    if not isinstance(output, str):
        output = str(output)
    return json.loads(repair_json_text(output))
