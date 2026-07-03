"""OL#44 §1: Glossary coverage report — post-translation statistics.

Wraps the existing :func:`ol_terminology.verifier.verify_translation` to
produce a human-readable coverage report. The report answers the user's
question: "How many of my glossary terms actually got used?"

Output format (text)::

    Glossary Coverage Report
    Total terms: 47
    Matched in source: 31 (66%)
    Unmatched: 16

    Match type breakdown:
      Exact: 24 (77%)
      Fuzzy (>80%): 5 (16%)
      Case-normalized: 2 (7%)

If ``coverage_threshold`` is set and the matched percentage is below it,
a ``⚠ WARNING: ...`` prefix is added — non-blocking, just informational.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from ol_terminology.glossary_class import Glossary

logger = logging.getLogger(__name__)

__all__ = [
    "CoverageStats",
    "compute_coverage_stats",
    "format_coverage_report",
]

_CJK_RE = re.compile(r"[\u3000-\u9fff\uf900-\ufaff]")


def _has_cjk(text: str) -> bool:
    """Return True if ``text`` contains any CJK ideograph."""
    return bool(_CJK_RE.search(text))


@dataclass
class CoverageStats:
    """Structured glossary coverage data.

    Attributes:
        total_terms:        Total terms in the glossary (size of the
                            glossary's source-vocabulary).
        matched:            Number of glossary terms that were found in
                            the source text (i.e. relevant to the doc).
        verified:           Of ``matched``, how many had their verified
                            translation present in the target.
        mismatched:         Of ``matched``, how many had a *wrong*
                            translation in the target.
        absent:             Of ``matched``, how many were not translated
                            at all in the target.
        exact:              Match-type count: term matched source exactly
                            (case-sensitive). Includes verified + mismatched
                            + absent (those that appeared in source).
        fuzzy:              Match-type count: term matched at >80% similarity
                            (computed as case-normalized match when case differs).
        case_normalized:    Match-type count: term matched after case
                            normalization only.
        matched_pct:        ``matched / total_terms * 100``, or 0.0
                            when ``total_terms == 0``.
    """

    total_terms: int
    matched: int
    verified: int
    mismatched: int
    absent: int
    exact: int
    fuzzy: int
    case_normalized: int
    matched_pct: float


def _extract_glossary_terms(
    glossary: Union[dict[str, dict[str, Any]], "Glossary", None],
) -> list[str]:
    """Extract just the source-term strings from any supported glossary format."""
    if glossary is None:
        return []

    if hasattr(glossary, "terms") and hasattr(glossary, "find_relevant"):
        return list(glossary.terms.keys())

    if isinstance(glossary, dict):
        out = []
        for term, meta in glossary.items():
            if isinstance(term, str):
                out.append(term)
        return out

    raise TypeError(f"Unsupported glossary type: {type(glossary)}")


def _match_type_for_term(term: str, source_text: str) -> str:
    """Classify how ``term`` matched ``source_text``.

    Returns one of: 'exact', 'fuzzy', 'case_normalized', 'none'.

    For Latin terms, uses word-boundary regex to avoid spurious
    substring matches (e.g. 'API' in 'rapid'). CJK terms use
    substring matching (no word boundary in Chinese text).
    """
    if not source_text or not term:
        return "none"

    if _has_cjk(term):
        if term in source_text:
            return "exact"
        return "none"

    pattern = r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])"
    if re.search(pattern, source_text):
        return "exact"
    if term != term.lower() and re.search(
        pattern, source_text, flags=re.IGNORECASE,
    ):
        return "case_normalized"
    return "none"


def compute_coverage_stats(
    source_text: str,
    target_text: str,
    glossary: Union[dict[str, dict[str, Any]], "Glossary", None] = None,
) -> CoverageStats:
    """Compute structured coverage statistics.

    Args:
        source_text: The original source text (pre-translation).
        target_text: The translated text (post-translation).
        glossary:    Optional glossary (legacy dict or new dataclass).

    Returns:
        A :class:`CoverageStats` with counts and percentages.
        When glossary is None, returns a zeroed-out stats object
        (no crash, no zero-division).
    """
    terms = _extract_glossary_terms(glossary)
    if not terms:
        return CoverageStats(
            total_terms=0,
            matched=0,
            verified=0,
            mismatched=0,
            absent=0,
            exact=0,
            fuzzy=0,
            case_normalized=0,
            matched_pct=0.0,
        )

    from ol_terminology.verifier import verify_translation

    verifier_report = verify_translation(
        source_text=source_text,
        target_text=target_text,
        glossary=glossary,
    )

    verified_set = {e.term for e in verifier_report.verified}
    mismatched_set = {e.term for e in verifier_report.mismatches}
    absent_set = {e.term for e in verifier_report.absent}

    matched = 0
    exact = 0
    fuzzy = 0
    case_normalized = 0
    for term in terms:
        match_type = _match_type_for_term(term, source_text)
        if match_type == "none":
            continue
        matched += 1
        if match_type == "exact":
            exact += 1
        elif match_type == "case_normalized":
            case_normalized += 1
        else:
            fuzzy += 1

    total = len(terms)
    matched_pct = (matched / total * 100.0) if total > 0 else 0.0

    return CoverageStats(
        total_terms=total,
        matched=matched,
        verified=len(verified_set),
        mismatched=len(mismatched_set),
        absent=len(absent_set),
        exact=exact,
        fuzzy=fuzzy,
        case_normalized=case_normalized,
        matched_pct=matched_pct,
    )


def format_coverage_report(
    source_text: str,
    target_text: str,
    glossary: Union[dict[str, dict[str, Any]], "Glossary", None] = None,
    coverage_threshold: float | None = None,
) -> str:
    """Format a human-readable glossary coverage report.

    Output::

        Glossary Coverage Report
        Total terms: 47
        Matched in source: 31 (66%)
        Unmatched: 16

        Match type breakdown:
          Exact: 24 (77%)
          Fuzzy (>80%): 5 (16%)
          Case-normalized: 2 (7%)

    If ``coverage_threshold`` is set (e.g., ``50`` for 50%) and the
    matched percentage falls below it, a ``⚠ WARNING: ...`` prefix is
    added. Non-blocking; informational only.

    Args:
        source_text:         The original source text.
        target_text:         The translated text.
        glossary:            Optional glossary (any supported format).
        coverage_threshold:  Optional int/float (0-100). When set, emit
                             a warning if matched% is below this value.
                             ``None`` (default) disables the check.

    Returns:
        A formatted multi-line string ready to print or log.
    """
    if glossary is None or _extract_glossary_terms(glossary) == []:
        return "No glossary provided — coverage report skipped."

    stats = compute_coverage_stats(source_text, target_text, glossary)
    lines: list[str] = []

    if coverage_threshold is not None and stats.matched_pct < coverage_threshold:
        lines.append(
            f"⚠ WARNING: Glossary coverage is {stats.matched:.0f}% "
            f"({stats.matched}/{stats.total_terms} terms matched) "
            f"— below threshold {coverage_threshold:.0f}%"
        )

    lines.append("Glossary Coverage Report")
    lines.append(f"Total terms: {stats.total_terms}")
    lines.append(
        f"Matched in source: {stats.matched} ({stats.matched_pct:.0f}%)"
    )
    lines.append(f"Unmatched: {stats.total_terms - stats.matched}")

    if stats.matched > 0:
        lines.append("")
        lines.append("Match type breakdown:")
        exact_pct = stats.exact / stats.matched * 100.0
        lines.append(f"  Exact: {stats.exact} ({exact_pct:.0f}%)")
        fuzzy_pct = stats.fuzzy / stats.matched * 100.0
        lines.append(f"  Fuzzy (>80%): {stats.fuzzy} ({fuzzy_pct:.0f}%)")
        case_pct = stats.case_normalized / stats.matched * 100.0
        lines.append(
            f"  Case-normalized: {stats.case_normalized} ({case_pct:.0f}%)"
        )

    return "\n".join(lines)
