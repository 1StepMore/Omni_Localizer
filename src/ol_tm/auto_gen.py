"""Auto-gen translation memory (Phase D4).

On a new translation request, search past TMX for similar segments.
Top-3 similar segments are injected as in-context examples in the
LLM prompt.

No embeddings required for MVP — uses token-overlap (Jaccard) as
the similarity metric. Can be upgraded to embeddings later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

DEFAULT_TM_DIR = Path.home() / ".local" / "share" / "omni-suite" / "tm"


@dataclass
class TMEntry:
    """Single TM entry: source segment + target translation."""

    source: str
    target: str
    lang_pair: str = ""
    score: float = 0.0


def _tokenize(text: str) -> set[str]:
    """Lowercase + split on non-word characters for token comparison."""
    return set(re.findall(r"\w+", text.lower()))


def jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity between two strings (0.0-1.0)."""
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_similar(
    query: str,
    entries: Sequence[TMEntry],
    top_k: int = 3,
    min_similarity: float = 0.3,
) -> list[TMEntry]:
    """Find top-k most similar TM entries for a query.

    Args:
        query: source text to find matches for
        entries: pool of TM entries to search
        top_k: number of results to return (default 3)
        min_similarity: minimum similarity threshold (0.0-1.0)

    Returns:
        List of TMEntry sorted by similarity (highest first), with
        score field populated. Empty list if no matches above threshold.
    """
    scored = []
    for entry in entries:
        sim = jaccard_similarity(query, entry.source)
        if sim >= min_similarity:
            scored.append(TMEntry(
                source=entry.source,
                target=entry.target,
                lang_pair=entry.lang_pair,
                score=sim,
            ))
    scored.sort(key=lambda e: e.score, reverse=True)
    return scored[:top_k]


def build_in_context_examples(matches: Sequence[TMEntry]) -> str:
    """Format TM matches as in-context examples for LLM prompt.

    Args:
        matches: list of TMEntry from find_similar()

    Returns:
        Formatted string ready to inject into prompt, or empty
        string if no matches.
    """
    if not matches:
        return ""
    lines = ["Translation Memory (top matches):"]
    for i, m in enumerate(matches, 1):
        lines.append(f"{i}. {m.source} -> {m.target}")
    return "\n".join(lines)


def save_tmx(entries: Sequence[TMEntry], path: Path) -> None:
    """Save entries to a simple TSV file (TMX-substitute for MVP).

    Format: source<TAB>target<TAB>lang_pair per line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(f"{entry.source}\t{entry.target}\t{entry.lang_pair}\n")


def load_tmx(path: Path) -> list[TMEntry]:
    """Load entries from a TSV file."""
    entries = []
    if not path.exists():
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                entries.append(TMEntry(
                    source=parts[0],
                    target=parts[1],
                    lang_pair=parts[2] if len(parts) > 2 else "",
                ))
    return entries
