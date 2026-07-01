"""Post-translation terminology verification (no LLM, no network).

Compares source/target text against a verified glossary and reports:
  - verified: term found with correct translation
  - mismatches: term found with WRONG translation
  - absent: term not found in target at all
  - inconsistencies: same source term translated differently in 2+ places
  - low_confidence: term's confidence below threshold (skipped by default)

This is a pure-logic checker — does NOT make LLM calls or network calls.
The Agent layer is responsible for upstream web search to build the
verified glossary; this module is the lightweight downstream check.

Glossary formats supported:
  - LEGACY: dict[str, dict] = {term: {translation, variants, confidence}}
  - NEW:    ol_terminology.glossary_class.Glossary dataclass
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from ol_terminology.glossary_class import Glossary

logger = logging.getLogger(__name__)

# Common English stop words — excluded from inconsistency detection.
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "and", "but", "or", "nor", "not", "so", "yet", "both",
    "either", "neither", "each", "every", "all", "any", "few", "more",
    "most", "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "if", "when", "where", "how", "what",
    "which", "who", "whom", "this", "that", "these", "those", "it", "its",
})

# Minimum word length for a candidate "term" in no-glossary mode.
# Avoids flagging single CJK characters or 1-letter English words.
_MIN_TERM_WORD_LEN = 3


@dataclass
class TermVerificationEntry:
    """A single term verification result."""

    term: str
    expected: str
    found: str | None
    confidence: float
    status: str  # "verified" | "mismatch" | "absent" | "low_confidence"

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "expected": self.expected,
            "found": self.found,
            "confidence": self.confidence,
            "status": self.status,
        }


@dataclass
class InconsistencyEntry:
    """A detected translation inconsistency.

    Supports dict-style access for backward compatibility:
        entry["source_term"], entry["translations"]
    """

    source_term: str
    translations: list[str]

    def to_dict(self) -> dict:
        return {
            "source_term": self.source_term,
            "translations": self.translations,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


@dataclass
class TermVerificationReport:
    """Full terminology verification report."""

    source_chars: int
    target_chars: int
    verified: list[TermVerificationEntry] = field(default_factory=list)
    mismatches: list[TermVerificationEntry] = field(default_factory=list)
    absent: list[TermVerificationEntry] = field(default_factory=list)
    inconsistencies: list[InconsistencyEntry] = field(default_factory=list)
    low_confidence: list[TermVerificationEntry] = field(default_factory=list)

    @property
    def total_terms_checked(self) -> int:
        return (
            len(self.verified)
            + len(self.mismatches)
            + len(self.absent)
            + len(self.low_confidence)
        )

    def to_dict(self) -> dict:
        return {
            "source_chars": self.source_chars,
            "target_chars": self.target_chars,
            "total_terms_checked": self.total_terms_checked,
            "verified": [e.to_dict() for e in self.verified],
            "mismatches": [e.to_dict() for e in self.mismatches],
            "absent": [e.to_dict() for e in self.absent],
            "inconsistencies": [e.to_dict() for e in self.inconsistencies],
            "low_confidence": [e.to_dict() for e in self.low_confidence],
        }


def _normalize_glossary(
    glossary: Union[dict[str, dict[str, Any]], "Glossary", None],
) -> list[tuple[str, str, float]]:
    """Normalize a glossary (any supported format) into a flat list.

    Returns:
        List of (term, expected_translation, confidence) tuples.
    """
    if glossary is None:
        return []

    # New Glossary dataclass
    if hasattr(glossary, "terms") and hasattr(glossary, "find_relevant"):
        out: list[tuple[str, str, float]] = []
        for src, tgts in glossary.terms.items():
            primary = tgts[0] if tgts else ""
            out.append((src, primary, 1.0))  # NEW format has no confidence
        return out

    # Legacy dict[str, dict]
    if isinstance(glossary, dict):
        out = []
        for term, meta in glossary.items():
            if isinstance(meta, dict):
                translation = meta.get("translation", "")
                confidence = meta.get("confidence", 1.0)
                if translation:
                    out.append((term, translation, float(confidence)))
            else:
                out.append((term, str(meta), 1.0))
        return out

    raise TypeError(f"Unsupported glossary type: {type(glossary)}")


def _check_glossary_coverage(
    source_text: str,
    target_text: str,
    glossary_entries: list[tuple[str, str, float]],
    confidence_threshold: float,
    report: TermVerificationReport,
) -> None:
    """Populate report.verified / mismatches / absent / low_confidence."""
    for term, expected, confidence in glossary_entries:
        # Find term occurrences in source (presence check)
        if term not in source_text:
            # Term not in source — skip
            continue

        # Low confidence → skip main check, record separately
        if confidence < confidence_threshold:
            report.low_confidence.append(
                TermVerificationEntry(
                    term=term,
                    expected=expected,
                    found=None,
                    confidence=confidence,
                    status="low_confidence",
                )
            )
            continue

        # Find expected translation in target
        if expected in target_text:
            report.verified.append(
                TermVerificationEntry(
                    term=term,
                    expected=expected,
                    found=expected,
                    confidence=confidence,
                    status="verified",
                )
            )
        else:
            # Term is in source but its verified translation is not in target.
            # Could be: (a) mismatch — LLM used a different translation,
            # (b) absent — term not translated at all (target omits the concept).
            _found = _find_likely_translation(source_text, target_text, term, expected)
            if _found is not None:
                report.mismatches.append(
                    TermVerificationEntry(
                        term=term,
                        expected=expected,
                        found=_found,
                        confidence=confidence,
                        status="mismatch",
                    )
                )
            else:
                report.absent.append(
                    TermVerificationEntry(
                        term=term,
                        expected=expected,
                        found=None,
                        confidence=confidence,
                        status="absent",
                    )
                )


def _find_likely_translation(
    source: str, target: str, term: str, expected: str,
) -> str | None:
    """Heuristic: find the most likely translation of ``term`` in target.

    Returns the CJK word from the mapped target sentence that most
    plausibly translates ``term``, or None if none found.
    """
    src_sentences = re.split(r"[.!?\n。！？]+", source)
    tgt_sentences = re.split(r"[.!?\n。！？]+", target)
    src_sentences = [s.strip() for s in src_sentences if s.strip()]
    tgt_sentences = [s.strip() for s in tgt_sentences if s.strip()]

    if not src_sentences or not tgt_sentences:
        return None

    src_idx = None
    for i, sent in enumerate(src_sentences):
        if term in sent:
            src_idx = i
            break
    if src_idx is None:
        return None

    tgt_idx = min(
        int(src_idx * len(tgt_sentences) / max(len(src_sentences), 1)),
        len(tgt_sentences) - 1,
    )
    tgt_sent = tgt_sentences[tgt_idx]

    if not tgt_sent:
        return None

    cjk_words: list[str] = re.findall(r"[\u4e00-\u9fff]{2,}", tgt_sent)
    if not cjk_words:
        return None

    # Pick the longest CJK word — most likely to be a term translation
    # rather than a common function word.
    found: str = max(cjk_words, key=len)

    # Plausibility: the expected CJK portion's length vs. the found word.
    expected_cjk: str = "".join(re.findall(r"[\u4e00-\u9fff]+", expected))
    expected_len = len(expected_cjk)
    found_len = len(found)

    if expected_len == 0:
        return found

    ratio = expected_len / max(found_len, 1)

    # Short expected (1-2 CJK chars) + long found (>2x expected):
    # likely a different rendering of the same term (mismatch).
    if expected_len <= 2 and found_len > expected_len * 2:
        return found

    # For longer expected CJK (≥3 chars): similar length → mismatch.
    if expected_len > 2 and ratio >= 0.5:
        return found

    return None


def _extract_cjk_at_position(tgt_sent: str, word_pos: float) -> str:
    """Extract a 2-char CJK window at the proportional position in tgt_sent."""
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", tgt_sent)
    if not cjk_chars:
        return ""
    char_pos = int(word_pos * len(cjk_chars))
    char_pos = min(char_pos, len(cjk_chars) - 1)
    end = min(char_pos + 2, len(cjk_chars))
    return "".join(cjk_chars[char_pos:end])


def _check_consistency(
    source_text: str,
    target_text: str,
    report: TermVerificationReport,
) -> None:
    src_sentences = re.split(r"[.!?\n。！？]+", source_text)
    tgt_sentences = re.split(r"[.!?\n。！？]+", target_text)
    src_sentences = [s.strip() for s in src_sentences if s.strip()]
    tgt_sentences = [s.strip() for s in tgt_sentences if s.strip()]

    if not src_sentences or not tgt_sentences:
        return

    def _map_to_tgt(src_idx: int) -> int:
        return min(
            int(src_idx * len(tgt_sentences) / max(len(src_sentences), 1)),
            len(tgt_sentences) - 1,
        )

    # Build term → [(src_sentence_idx, word_position)] for content words
    term_positions: dict[str, list[tuple[int, float]]] = {}
    for s_idx, sent in enumerate(src_sentences):
        words = re.findall(r"\b[a-zA-Z]+\b", sent.lower())
        total = len(words)
        for w_idx, w in enumerate(words):
            if len(w) >= _MIN_TERM_WORD_LEN and w not in _STOP_WORDS:
                pos = w_idx / max(total, 1)
                term_positions.setdefault(w, []).append((s_idx, pos))

    for term, positions in term_positions.items():
        if len(positions) < 2:
            continue

        translations: list[str] = []
        for src_idx, pos in positions:
            tgt_idx = _map_to_tgt(src_idx)
            if tgt_idx >= len(tgt_sentences):
                continue
            extracted = _extract_cjk_at_position(tgt_sentences[tgt_idx], pos)
            if extracted and extracted not in translations:
                translations.append(extracted)

        if len(translations) > 1:
            report.inconsistencies.append(
                InconsistencyEntry(source_term=term, translations=translations)
            )


def verify_translation(
    source_text: str,
    target_text: str,
    glossary: Union[dict[str, dict[str, Any]], "Glossary", None] = None,
    confidence_threshold: float = 0.7,
) -> TermVerificationReport:
    """Verify glossary term usage in a translated text.

    Args:
        source_text: Original source text.
        target_text: Translated text to verify.
        glossary: Optional glossary in either legacy dict format
            ({term: {translation, variants, confidence}}) or the new
            Glossary dataclass.
        confidence_threshold: Terms with confidence below this are
            reported as `low_confidence` and excluded from main checks.
            Default 0.7.

    Returns:
        TermVerificationReport with verified/mismatches/absent/
        inconsistencies/low_confidence lists.

    Behavior:
        - With glossary: checks each term's verified translation appears
          in target. If term is in source but expected translation is
          not, marks as mismatch (with found translation) or absent.
        - Without glossary: detects inconsistent translations of the
          same source term across sentences.
    """
    report = TermVerificationReport(
        source_chars=len(source_text),
        target_chars=len(target_text),
    )
    entries = _normalize_glossary(glossary)
    if entries:
        _check_glossary_coverage(
            source_text, target_text, entries, confidence_threshold, report,
        )
    else:
        _check_consistency(source_text, target_text, report)
    return report
