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
# Gate 5: Source copy detection (Issue #57)
# ---------------------------------------------------------------------------


def check_source_copy(source: str, target: str) -> list[str]:
    """Gate 5 — detect when LLM echoes the source text back unchanged.

    Compares the stripped source and target.  When they are identical,
    the LLM effectively skipped the translation request (common for
    short input with inline formatting, proper nouns that look like
    English, chapter numbers, etc.).

    Skips strings that contain no alphabetic characters (pure numbers,
    symbols, whitespace-only) — these should remain unchanged across
    translation and are not meaningful copy-echo signals.

    Returns:
        List of ``OL_WARN: SOURCE_COPY`` strings (empty if source != target
        or the text contains no translatable content).
    """
    if source.strip() == target.strip():
        # Skip pure numeric/symbolic content — numbers and symbols should
        # remain unchanged across translation; flagging them is noise.
        if not re.search(r"[a-zA-Z\u4e00-\u9fff]", source):
            return []
        return [
            "OL_WARN: SOURCE_COPY — target is identical to source, "
            "translation skipped / LLM echoed input back"
        ]
    return []


# ---------------------------------------------------------------------------
# Gate 6: CJK residue in non-CJK target (Issue #61)
# ---------------------------------------------------------------------------

# CJK character ranges
_RE_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")  # CJK Unified Ideographs
_RE_HIRAGANA = re.compile(r"[\u3040-\u309f]")  # Hiragana
_RE_KATAKANA = re.compile(r"[\u30a0-\u30ff]")  # Katakana
_RE_HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff]")  # Hangul

# Non-CJK target locales that should not contain CJK characters
_NON_CJK_LOCALES_TARGET = {"en", "fr", "de", "es", "pt", "it", "nl", "ru", "ar"}


def _contains_cjk(text: str) -> bool:
    """Check if text contains any CJK characters."""
    return bool(
        _RE_CJK.search(text)
        or _RE_HIRAGANA.search(text)
        or _RE_KATAKANA.search(text)
        or _RE_HANGUL.search(text)
    )


def _detect_cjk_language(text: str) -> str | None:
    """Detect which CJK language is present: 'zh', 'ja', 'ko', or None.

    Priority: hiragana/katakana → hangul → CJK ideographs.
    Japanese Kanji shares Unicode ranges with Chinese, so we check
    hiragana/katakana first to distinguish ja from zh.
    """
    if _RE_HIRAGANA.search(text) or _RE_KATAKANA.search(text):
        return "ja"
    if _RE_HANGUL.search(text):
        return "ko"
    if _RE_CJK.search(text):
        return "zh"
    return None


def check_cjk_residue(
    source: str,
    target: str,
    target_lang: str | None = None,
) -> list[str]:
    """Gate 6 — detect CJK characters leaked into a non-CJK target.

    When translating from a CJK source language (zh/ja/ko) into a non-CJK
    target language (en/fr/de/...), warns if any CJK characters remain in
    the translated text.

    Args:
        source: Source (pre-translation) text.
        target: Target (translated) text.
        target_lang: Target language code (e.g. ``en``, ``fr``, ``de``).
            When ``None``, the check is skipped because we cannot determine
            whether CJK characters are expected or not.

    Returns:
        List of ``OL_WARN: CJK_RESIDUE`` strings (empty if clean or skipped).
    """
    if target_lang is None:
        return []

    lang_code = target_lang.split("-")[0].lower()
    if lang_code not in _NON_CJK_LOCALES_TARGET:
        # Target is a CJK language — CJK characters expected, skip check
        return []

    if not _contains_cjk(target):
        return []

    # Identify which CJK characters
    cjk_lang = _detect_cjk_language(target)
    if cjk_lang is None:
        # Edge case: found CJK but couldn't classify — still a residue
        return ["OL_WARN: CJK_RESIDUE — CJK characters found in non-CJK target text"]

    return [
        f"OL_WARN: CJK_RESIDUE — {cjk_lang.upper()} characters found in "
        f"{lang_code.upper()} target text (leaked from source)"
    ]


# ---------------------------------------------------------------------------
# Gate 7: LLM protocol markers detection (Issues #62 / #63)
# ---------------------------------------------------------------------------

# Patterns for LLM protocol markers that should never appear in translated output
_RE_LLM_CRITICAL = re.compile(
    r"\b(?:CRITICAL|IMPORTANT|NOTE|WARNING|CAUTION|REMEMBER)\b\s*:",
    re.IGNORECASE,
)
_RE_LLM_OUTPUT_ONLY = re.compile(
    r"\bOutput\s+(?:ONLY|only)\b",
    re.IGNORECASE,
)
_RE_LLM_DO_NOT = re.compile(
    r"\bDo\s+not\s+(?:include|add|remove|change|modify|translate|output)\b",
    re.IGNORECASE,
)
_RE_LLM_TRANSLATION = re.compile(
    r"\b(?:Translation|Translated text|Target language)\s*:",
    re.IGNORECASE,
)


def check_llm_protocol_markers(
    source: str,
    target: str,
) -> list[str]:
    """Gate 7 — detect LLM protocol markers in translated output.

    LLMs sometimes echo system-prompt instructions or protocol markers
    into the translated text. Common patterns include:

    * ``CRITICAL:`` / ``IMPORTANT:`` / ``NOTE:`` markers
    * ``Output ONLY the translation`` fragments
    * ``Do not include any explanations`` instructions
    * ``Translation:`` / ``Translated text:`` labels

    These markers indicate that the LLM's output contains leaked
    system-prompt fragments and should be re-translated or cleaned.

    Args:
        source: Source (pre-translation) text.
        target: Target (translated) text.

    Returns:
        List of ``OL_WARN: LLM_PROTOCOL_MARKER`` strings (empty if clean).
    """
    warnings: list[str] = []

    if _RE_LLM_CRITICAL.search(target):
        warnings.append(
            "OL_WARN: LLM_PROTOCOL_MARKER — target contains CRITICAL/IMPORTANT/NOTE "
            "protocol marker (leaked system-prompt instruction)"
        )
    if _RE_LLM_OUTPUT_ONLY.search(target):
        warnings.append(
            "OL_WARN: LLM_PROTOCOL_MARKER — target contains 'Output ONLY' "
            "protocol fragment (leaked system-prompt instruction)"
        )
    if _RE_LLM_DO_NOT.search(target):
        warnings.append(
            "OL_WARN: LLM_PROTOCOL_MARKER — target contains 'Do not ...' "
            "instruction fragment (leaked system-prompt instruction)"
        )
    if _RE_LLM_TRANSLATION.search(target):
        warnings.append(
            "OL_WARN: LLM_PROTOCOL_MARKER — target contains 'Translation:' "
            "or 'Translated text:' label (leaked system-prompt instruction)"
        )

    return warnings


# ---------------------------------------------------------------------------
# Gate: Full glossary term audit via verify_translation
# ---------------------------------------------------------------------------


def check_terms_audit(
    source: str,
    target: str,
    glossary: dict[str, Any] | None = None,
    confidence_threshold: float = 0.7,
) -> list[str]:
    """Gate — full glossary term audit using verify_translation.

    Runs ``verify_translation()`` on the source-target pair with the
    provided glossary and flattens the report into ``OL_WARN`` lines.
    Four warning codes are produced depending on severity:

    * ``TERM_AUDIT_MISMATCH`` — term translated using a non-glossary variant
    * ``TERM_AUDIT_ABSENT`` — source term found but expected translation absent
    * ``TERM_AUDIT_INCONSISTENCY`` — same source term → different translations
    * ``TERM_AUDIT_LOW_CONFIDENCE`` — best guess fell below threshold

    This gate is richer than Gate 2 (terminology consistency) because it
    also reports mismatches, absent terms, and cross-segment inconsistencies.

    Args:
        source: Source text.
        target: Translated text.
        glossary: Glossary dict. When ``None`` the check is skipped.
        confidence_threshold: Minimum confidence (0.0-1.0) for term matches.

    Returns:
        List of ``OL_WARN: TERM_AUDIT_<STATUS>`` strings (empty if clean).
    """
    if glossary is None:
        return []

    from ol_terminology.verifier import verify_translation

    report = verify_translation(source, target, glossary, confidence_threshold)

    warnings: list[str] = []

    for m in report.mismatches:
        warnings.append(
            f"OL_WARN: TERM_AUDIT_MISMATCH — term '{m.term}' "
            f"expected '{m.expected}' got '{m.found}'"
        )
    for a in report.absent:
        warnings.append(
            f"OL_WARN: TERM_AUDIT_ABSENT — term '{a.term}' "
            f"expected '{a.expected}' not found"
        )
    for i in report.inconsistencies:
        translations = ", ".join(i.translations)
        warnings.append(
            f"OL_WARN: TERM_AUDIT_INCONSISTENCY — term '{i.source_term}' "
            f"has {len(i.translations)} translations: {translations}"
        )
    for lc in report.low_confidence:
        warnings.append(
            f"OL_WARN: TERM_AUDIT_LOW_CONFIDENCE — term '{lc.term}' "
            f"confidence {lc.confidence} below threshold"
        )

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
    source_copy_enabled: bool = True,
    cjk_residue_enabled: bool = True,
    target_lang: str | None = None,
    llm_markers_enabled: bool = True,
    terms_audit_enabled: bool = True,
    terms_audit_confidence: float = 0.7,
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
        source_copy_enabled: Run Gate 5 (source copy detection).
        cjk_residue_enabled: Run Gate 6 (CJK residue in non-CJK target).
        target_lang: Target language code for Gate 6 (e.g. ``en``).
        llm_markers_enabled: Run Gate 7 (LLM protocol markers).
    terms_audit_enabled: Run full glossary term audit via verify_translation.
    terms_audit_confidence: Confidence threshold for term audit.

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

    # Gate 5
    if source_copy_enabled:
        try:
            all_warnings.extend(check_source_copy(source, target))
        except Exception as exc:
            _logger.exception("Gate 5 (source copy) failed: %s", exc)

    # Gate 6: CJK residue (Issue #61)
    if cjk_residue_enabled:
        try:
            all_warnings.extend(
                check_cjk_residue(source, target, target_lang=target_lang)
            )
        except Exception as exc:
            _logger.exception("Gate 6 (CJK residue) failed: %s", exc)

    # Gate 7: LLM protocol markers (Issues #62 / #63)
    if llm_markers_enabled:
        try:
            all_warnings.extend(check_llm_protocol_markers(source, target))
        except Exception as exc:
            _logger.exception("Gate 7 (LLM protocol markers) failed: %s", exc)

    # Gate: Terms audit (full glossary term verification via verify_translation)
    if terms_audit_enabled:
        try:
            all_warnings.extend(
                check_terms_audit(
                    source,
                    target,
                    glossary=glossary,
                    confidence_threshold=terms_audit_confidence,
                )
            )
        except Exception as exc:
            _logger.exception("Gate (terms audit) failed: %s", exc)

    return all_warnings


# ---------------------------------------------------------------------------
# Gate 5 retry: re-translate units flagged as SOURCE_COPY
# ---------------------------------------------------------------------------


async def retry_critical_failures(
    units: list,
    pool: Any,
    src_lang: str,
    tgt_lang: str,
    quality_gates_cfg: Any,
    glossary: dict[str, Any] | None,
    warnings_per_unit: dict[str, list[str]],
    max_retries: int = 1,
) -> int:
    """Re-translate units where a critical pipeline failure was detected.

    Scans ``warnings_per_unit`` for ``OL_WARN: SOURCE_COPY`` or
    ``OL_WARN: TRANSLATION_FAILED`` entries.  For each affected unit,
    calls ``pool.translate()`` again, applies the repair pipeline,
    and re-runs quality gates on the retried translation.

    Covers two scenarios:

    * **SOURCE_COPY** — the LLM echoed the source text back unchanged.
      Gate 5 catches this and the retry gives the LLM another chance
      to produce a real translation.

    * **TRANSLATION_FAILED** — the translation call itself raised an
      exception (timeout, rate limit, API error).  The pipeline drops
      the source text as a fallback; retry is the only way to recover.

    If all retries still fail (still copy or another transport error),
    the last best-effort target is kept and the warning is upgraded
    to ``OL_WARN: FAILED_RETRY (retry exhausted -- kept best-effort translation)``.

    Args:
        units: All translated units (may include units without warnings).
        pool: Async LLM pool with a ``.translate(text, src, tgt, ...)`` method.
        src_lang: Source language code.
        tgt_lang: Target language code.
        quality_gates_cfg: A ``QualityGateConfig``-like object with
            ``inline_tags``, ``terminology``, ``length_ratio``,
            ``locale``, and ``source_copy`` boolean attributes.
        glossary: Glossary dict for terminology checks.
        warnings_per_unit: Mutable dict mapping unit_id to warning list.
            SOURCE_COPY / TRANSLATION_FAILED entries are removed on
            retry and replaced with the new gate results.
        max_retries: Max LLM calls per retried unit (default 1).

    Returns:
        Number of units that were successfully re-translated
        (critical failure resolved).
    """
    _CRITICAL_PREFIXES = ("SOURCE_COPY", "TRANSLATION_FAILED")

    to_retry: list[str] = []
    for uid, warns in warnings_per_unit.items():
        if any(_p in w for w in warns for _p in _CRITICAL_PREFIXES):
            to_retry.append(uid)

    if not to_retry:
        return 0

    from ol_xliff.pipeline import XLIFFRepairPipeline
    from ol_buses.xliff_shield import restore_tags

    repair_pipeline = XLIFFRepairPipeline()
    resolved = 0

    for unit in units:
        uid = unit.unit_id
        if uid not in to_retry:
            continue

        still_copy = True
        last_translation: str | None = None
        for attempt in range(max_retries):
            try:
                new_target = await pool.translate(
                    unit.source_text, src_lang, tgt_lang,
                )
            except Exception:
                _logger.warning(
                    "SOURCE_COPY retry translate failed for unit=%s "
                    "(attempt %d/%d)",
                    uid, attempt + 1, max_retries,
                )
                break

            if unit.shield_map:
                unshielded = restore_tags(new_target, unit.shield_map)
                repaired, _ = repair_pipeline.repair(
                    unshielded, unit.source_text, unit.shield_map,
                )
            else:
                repaired = new_target

            last_translation = repaired

            new_gate_warnings = run_quality_gates(
                source=unit.source_text,
                target=repaired,
                glossary=glossary,
                inline_tags_enabled=quality_gates_cfg.inline_tags,
                terminology_enabled=(
                    quality_gates_cfg.terminology and glossary is not None
                ),
                length_ratio_enabled=quality_gates_cfg.length_ratio.enabled,
                length_ratio_min=quality_gates_cfg.length_ratio.min,
                length_ratio_max=quality_gates_cfg.length_ratio.max,
                locale_enabled=quality_gates_cfg.locale.enabled,
                target_locale=quality_gates_cfg.locale.target_locale,
                source_copy_enabled=quality_gates_cfg.source_copy,
                cjk_residue_enabled=quality_gates_cfg.cjk_residue,
                target_lang=tgt_lang,
                llm_markers_enabled=quality_gates_cfg.llm_markers,
            )

            still_copy = any("SOURCE_COPY" in w for w in new_gate_warnings)

            unit.target_text = repaired

            old_non_copy = [
                w for w in warnings_per_unit.get(uid, [])
                if "SOURCE_COPY" not in w
            ]
            warnings_per_unit[uid] = old_non_copy + new_gate_warnings

            if not still_copy:
                resolved += 1
                break

        if still_copy and last_translation is not None:
            warnings_per_unit[uid] = [
                w for w in warnings_per_unit.get(uid, [])
                if "SOURCE_COPY" not in w
            ]
            warnings_per_unit[uid].append(
                "OL_WARN: FAILED_RETRY (retry exhausted -- "
                "kept best-effort translation)"
            )

    return resolved


# ---------------------------------------------------------------------------
# Warning summary
# ---------------------------------------------------------------------------


def format_warning_summary(warnings_per_unit: dict[str, list[str]]) -> str:
    """Build a one-line summary of all ``OL_WARN`` codes for a translation run.

    Example::

        12 warnings (LENGTH_RATIOx8, SOURCE_COPYx1, UNIT_SPELLINGx1, INLINE_TAG_MISMATCHx2)

    Returns:
        Human-readable summary string.  Returns ``"0 warnings"`` when
        *warnings_per_unit* is empty or contains no ``OL_WARN`` entries.
    """
    from collections import Counter

    codes: list[str] = []
    for warns in warnings_per_unit.values():
        for w in warns:
            m = re.search(r"OL_WARN:\s*(\w+)", w)
            if m:
                codes.append(m.group(1))

    if not codes:
        return "0 warnings"

    counts = Counter(codes)
    parts = [f"{code}x{n}" for code, n in counts.most_common()]
    return f'{sum(counts.values())} warnings ({", ".join(parts)})'
