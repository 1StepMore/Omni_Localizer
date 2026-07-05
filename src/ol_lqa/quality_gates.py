"""Post-translation quality gates for OL (Issue #56).

All gates are pure functions: no LLM calls, no I/O, no side effects.
Warnings follow the ``OL_WARN: <CODE>`` convention established by the
existing codebase (e.g. ``xliff_bus.py:check_cross_unit_uniqueness()``).

Environment variables (read at call time when arguments are ``None``):

* ``OL_LENGTH_RATIO_MIN`` — default lower bound for Gate 3 (fallback 0.5)
* ``OL_LENGTH_RATIO_MAX`` — default upper bound for Gate 3 (fallback 3.0)
* ``OL_TARGET_LOCALE`` — default locale for Gate 4 (e.g. ``en-US``)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

_logger = logging.getLogger(__name__)

# Patterns for inline tags (XLIFF inline codes)
_RE_BX = re.compile(r"<bx")
_RE_EX = re.compile(r"<ex")
_RE_X = re.compile(r"<x(?![a-z])")  # <x followed by non-letter (tag) vs <xbox

# Date leakage: CJK date YYYY年MM月DD日
_RE_CJK_DATE = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")

# Digit grouping patterns
# EU: 1.000.000,00 — digits with dots and a comma as decimal
_RE_EU_GROUPING = re.compile(r"\d{1,3}(?:\.\d{3})+,\d{2}")
# US: 1,000,000.00 — digits with commas and a dot as decimal
_RE_US_GROUPING = re.compile(r"\d{1,3}(?:,\d{3})+\.\d{2}")

# Currency symbols
_CURRENCY_SYMBOLS = {"$", "€", "£", "¥"}

# Non-CJK locales that should not contain CJK date patterns
_NON_CJK_LOCALES = {"en", "fr", "de", "es", "pt", "it"}

# EU locales (using comma as decimal separator)
_EU_LOCALES = {"de", "fr", "es", "it", "pt"}

# British → American spelling map (key: GB spelling, value: US spelling)
_GB_TO_US_SPELLINGS: dict[str, str] = {
    "metre": "meter",
    "colour": "color",
    "centre": "center",
    "favour": "favor",
    "behaviour": "behavior",
    "labour": "labor",
    "neighbour": "neighbor",
    "honour": "honor",
    "armour": "armor",
    "flavour": "flavor",
    "harbour": "harbor",
    "rumour": "rumor",
    "savour": "savor",
    "parlour": "parlor",
    "theatre": "theater",
    "travelling": "traveling",
    "cancelled": "canceled",
    "modelled": "modeled",
    "fuelled": "fueled",
    "centre": "center",
    "litre": "liter",
    "fibre": "fiber",
    "calibre": "caliber",
    "lustre": "luster",
    "sceptre": "scepter",
    "defence": "defense",
    "offence": "offense",
    "licence": "license",
    "practise": "practice",
    "pretence": "pretense",
    "analyse": "analyze",
    "breathalyse": "breathalyze",
    "catalyse": "catalyze",
    "dialyse": "dialyze",
    "hydrolyse": "hydrolyze",
    "paralyse": "paralyze",
    "ageing": "aging",
    "pyjamas": "pajamas",
    "grey": "gray",
    "cosy": "cozy",
    "mould": "mold",
    "moult": "molt",
    "smoulder": "smolder",
    "sulphur": "sulfur",
    "tyre": "tire",
    "aluminium": "aluminum",
    "cheque": "check",
    "draught": "draft",
    "jewellery": "jewelry",
    "plough": "plow",
    "programme": "program",
    "storey": "story",
}

# Reverse: American → British
_US_TO_GB_SPELLINGS: dict[str, str] = {v: k for k, v in _GB_TO_US_SPELLINGS.items()}
# Add some US-only terms not covered by the GB→US map
_US_TO_GB_SPELLINGS.update({
    "apologize": "apologise",
    "organize": "organise",
    "recognize": "recognise",
    "customize": "customise",
    "realize": "realise",
})

# Collect all GB spellings and US spellings for quick lookup
_GB_SPELLINGS_SET = set(_GB_TO_US_SPELLINGS.keys())
_US_SPELLINGS_SET = set(_US_TO_GB_SPELLINGS.keys())


# ---------------------------------------------------------------------------
# Gate 1: Inline tag counts
# ---------------------------------------------------------------------------


def _count_tag(text: str, pattern: re.Pattern[str]) -> int:
    """Count occurrences of a tag pattern in *text*."""
    return len(pattern.findall(text))


def check_inline_tag_counts(source: str, target: str) -> list[str]:
    """Gate 1 — verify inline tag parity between source and target.

    Counts ``<bx``, ``<ex``, and ``<x`` (standalone placeholder) occurrences
    in both strings.  If the count differs for any tag type, emits a warning.

    Returns:
        List of ``OL_WARN: INLINE_TAG_MISMATCH`` strings (empty if clean).
    """
    warnings: list[str] = []

    tag_types = [
        ("bx", _RE_BX),
        ("ex", _RE_EX),
        ("x", _RE_X),
    ]

    for tag_name, pattern in tag_types:
        src_count = _count_tag(source, pattern)
        tgt_count = _count_tag(target, pattern)
        if src_count != tgt_count:
            warnings.append(
                f"OL_WARN: INLINE_TAG_MISMATCH — tag <{tag_name} "
                f"count differs: source has {src_count}, target has {tgt_count}"
            )

    return warnings


# ---------------------------------------------------------------------------
# Gate 2: Terminology consistency
# ---------------------------------------------------------------------------


def check_terminology_consistency(target: str, glossary: dict[str, Any]) -> list[str]:
    """Gate 2 — check that glossary terms are used consistently in *target*.

    For each glossary entry that has a ``translation`` string, checks whether
    *both* the source term and the translation appear in *target*
    (case-insensitive).  If both appear and they are different strings, the
    translator has mixed translated and untranslated forms — an inconsistency.

    Example:
        Glossary: ``{"file": {"translation": "fichier"}}``
        Target:   ``"Ouvrez le fichier. Close the file."``
        → Both ``"fichier"`` and ``"file"`` appear → warning emitted.

    Returns:
        List of ``OL_WARN: TERMINOLOGY_INCONSISTENCY`` strings (empty if clean).
    """
    warnings: list[str] = []

    for source_term, entry in glossary.items():
        translation = entry.get("translation")
        if not isinstance(translation, str) or not translation:
            continue

        source_lower = source_term.lower()
        translation_lower = translation.lower()

        # Skip if source and translation are the same (no ambiguity)
        if source_lower == translation_lower:
            continue

        # Check if both source term and translation appear in target
        source_pattern = re.compile(re.escape(source_term), re.IGNORECASE)
        trans_pattern = re.compile(re.escape(translation), re.IGNORECASE)

        source_found = source_pattern.search(target) is not None
        trans_found = trans_pattern.search(target) is not None

        if source_found and trans_found:
            warnings.append(
                f"OL_WARN: TERMINOLOGY_INCONSISTENCY — term "
                f'"{source_term}" appears as both "{source_term}" '
                f'and "{translation}" in target'
            )

    return warnings


# ---------------------------------------------------------------------------
# Gate 3: Length ratio
# ---------------------------------------------------------------------------


def _parse_float_env(name: str, default: float) -> float:
    """Parse a float from an env var, returning *default* on failure."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        _logger.warning("Invalid %s=%r, falling back to %s", name, raw, default)
        return default


def check_length_ratio(
    source: str,
    target: str,
    min_ratio: float | None = None,
    max_ratio: float | None = None,
) -> list[str]:
    """Gate 3 — check that ``len(target) / len(source)`` is within bounds.

    When *min_ratio* / *max_ratio* are ``None``, values are read from
    environment variables ``OL_LENGTH_RATIO_MIN`` / ``OL_LENGTH_RATIO_MAX``
    respectively, falling back to 0.5 / 3.0.

    Returns:
        List of ``OL_WARN: LENGTH_RATIO`` strings (empty if within bounds).
    """
    src_len = len(source)
    if src_len == 0:
        return []  # avoid division by zero

    min_r = min_ratio if min_ratio is not None else _parse_float_env("OL_LENGTH_RATIO_MIN", 0.5)
    max_r = max_ratio if max_ratio is not None else _parse_float_env("OL_LENGTH_RATIO_MAX", 3.0)

    ratio = len(target) / src_len

    if ratio < min_r:
        return [
            f"OL_WARN: LENGTH_RATIO — target/source length ratio {ratio:.2f} "
            f"is below minimum {min_r}"
        ]
    if ratio > max_r:
        return [
            f"OL_WARN: LENGTH_RATIO — target/source length ratio {ratio:.2f} "
            f"is above maximum {max_r}"
        ]

    return []


# ---------------------------------------------------------------------------
# Gate 4: Locale conventions
# ---------------------------------------------------------------------------


def _normalize_locale(target_locale: str | None) -> str | None:
    """Resolve locale from argument or env var ``OL_TARGET_LOCALE``."""
    if target_locale is not None:
        return target_locale
    raw = os.environ.get("OL_TARGET_LOCALE")
    if raw:
        return raw
    return None


def _get_language_code(locale: str) -> str:
    """Extract the primary language code from a locale string.

    ``en-US`` → ``en``, ``fr-FR`` → ``fr``, ``zh-CN`` → ``zh``.
    """
    return locale.split("-")[0].lower()


def _check_currency_mixing(target: str) -> list[str]:
    """Check for ≥2 distinct currency symbols in *target*."""
    found = {s for s in _CURRENCY_SYMBOLS if s in target}
    if len(found) >= 2:
        symbols = " ".join(sorted(found))
        return [f"OL_WARN: CURRENCY_MIXING — multiple currency symbols found: {symbols}"]
    return []


def _check_date_leakage(target: str, language_code: str) -> list[str]:
    """Check for CJK date patterns in non-CJK locales."""
    if language_code in _NON_CJK_LOCALES and _RE_CJK_DATE.search(target):
        return ["OL_WARN: DATE_LEAKAGE — CJK date pattern (YYYY年MM月DD日) found in non-CJK locale"]
    return []


def _check_digit_grouping(target: str, language_code: str, locale: str) -> list[str]:
    """Check for mismatched digit grouping conventions."""
    warnings: list[str] = []

    if locale == "en-US":
        # en-US should not use EU grouping (dots as thousand sep, comma as decimal)
        if _RE_EU_GROUPING.search(target):
            warnings.append(
                "OL_WARN: DIGIT_GROUPING — EU format (1.000.000,00) detected in en-US locale"
            )
    elif language_code in _EU_LOCALES:
        # EU locales should not use US grouping (commas as thousand sep, dot as decimal)
        if _RE_US_GROUPING.search(target):
            lang_upper = language_code.upper()
            warnings.append(
                f"OL_WARN: DIGIT_GROUPING — US format (1,000,000.00) detected in {lang_upper} locale"
            )

    return warnings


def _check_unit_spelling(target: str, language_code: str, locale: str) -> list[str]:
    """Check for GB/US spelling mismatches per locale."""
    target_lower = target.lower()
    warnings: list[str] = []

    if locale == "en-US":
        # British spellings in US English
        found_gb = [w for w in _GB_SPELLINGS_SET if w in target_lower]
        if found_gb:
            warnings.append(
                "OL_WARN: UNIT_SPELLING — British spellings found in en-US locale: "
                + ", ".join(sorted(found_gb))
            )
    elif locale == "en-GB":
        # American spellings in GB English
        found_us = [w for w in _US_SPELLINGS_SET if w in target_lower]
        if found_us:
            warnings.append(
                "OL_WARN: UNIT_SPELLING — US spellings found in en-GB locale: "
                + ", ".join(sorted(found_us))
            )

    return warnings


def check_locale_conventions(
    target: str,
    target_locale: str | None = None,
) -> list[str]:
    """Gate 4 — locale-specific formatting convention checks.

    Checks performed:

    1. **Currency mixing** — warns if ≥2 of ``{$ € £ ¥}`` appear in *target*.
    2. **Date leakage** — warns if a CJK date (``YYYY年MM月DD日``) appears
       in a non-CJK locale (``en`` / ``fr`` / ``de`` / ``es`` / ``pt`` / ``it``).
    3. **Digit grouping** — warns if EU decimal-comma format
       (``1.000.000,00``) appears in ``en-US``, or US decimal-dot format
       (``1,000,000.00``) in EU locales.
    4. **Unit spelling** — warns if British spellings (e.g. ``colour``)
       appear in ``en-US``, or US spellings (e.g. ``color``) appear in
       ``en-GB``.

    Args:
        target: Translated text to inspect.
        target_locale: Target locale (e.g. ``en-US``, ``fr-FR``).
            Falls back to ``OL_TARGET_LOCALE`` env var when ``None``.
            When both are ``None``, only currency mixing is checked.

    Returns:
        List of ``OL_WARN: <CODE>`` strings (empty if all checks pass).
    """
    resolved_locale = _normalize_locale(target_locale)

    warnings: list[str] = []

    # Currency mixing — always checked (locale-independent)
    warnings.extend(_check_currency_mixing(target))

    if resolved_locale is not None:
        language_code = _get_language_code(resolved_locale)

        # Date leakage
        warnings.extend(_check_date_leakage(target, language_code))

        # Digit grouping
        warnings.extend(_check_digit_grouping(target, language_code, resolved_locale))

        # Unit spelling (only for English locales)
        if language_code == "en":
            warnings.extend(_check_unit_spelling(target, language_code, resolved_locale))

    return warnings


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_quality_gates(
    source: str,
    target: str,
    glossary: dict[str, Any] | None = None,
    *,
    inline_tags_enabled: bool = True,
    terminology_enabled: bool = True,
    length_ratio_enabled: bool = True,
    length_ratio_min: float | None = None,
    length_ratio_max: float | None = None,
    locale_enabled: bool = True,
    target_locale: str | None = None,
) -> list[str]:
    """Run all enabled quality gates on a source-target pair.

    Each gate is wrapped in its own ``try/except`` so that a failure
    in one gate does not prevent other gates from running.  Exceptions
    are logged and the next gate continues.

    Args:
        source: Source (pre-translation) text.
        target: Target (translated) text.
        glossary: Glossary dict for terminology consistency checks.
            May be ``None`` to skip terminology checks entirely.
        inline_tags_enabled: Run Gate 1 (inline tag parity).
        terminology_enabled: Run Gate 2 (terminology consistency).
        length_ratio_enabled: Run Gate 3 (length ratio bounds).
        length_ratio_min: Minimum length ratio override.
        length_ratio_max: Maximum length ratio override.
        locale_enabled: Run Gate 4 (locale conventions).
        target_locale: Target locale override.  Falls back to
            ``OL_TARGET_LOCALE`` env var.

    Returns:
        Combined list of all ``OL_WARN: <CODE>`` strings from all
        enabled gates, in execution order.
    """
    all_warnings: list[str] = []

    # Gate 1
    if inline_tags_enabled:
        try:
            all_warnings.extend(check_inline_tag_counts(source, target))
        except Exception as exc:
            _logger.exception("Gate 1 (inline tags) failed: %s", exc)

    # Gate 2
    if terminology_enabled and glossary is not None:
        try:
            all_warnings.extend(check_terminology_consistency(target, glossary))
        except Exception as exc:
            _logger.exception("Gate 2 (terminology) failed: %s", exc)

    # Gate 3
    if length_ratio_enabled:
        try:
            all_warnings.extend(
                check_length_ratio(
                    source,
                    target,
                    min_ratio=length_ratio_min,
                    max_ratio=length_ratio_max,
                )
            )
        except Exception as exc:
            _logger.exception("Gate 3 (length ratio) failed: %s", exc)

    # Gate 4
    if locale_enabled:
        try:
            all_warnings.extend(
                check_locale_conventions(target, target_locale=target_locale)
            )
        except Exception as exc:
            _logger.exception("Gate 4 (locale conventions) failed: %s", exc)

    return all_warnings
