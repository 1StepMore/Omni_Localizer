"""RAG-based prompt injection for translation context."""
from typing import Any

import logging

logger = logging.getLogger(__name__)

TM_MATCH_LIMIT = 3
GLOSSARY_TERM_LIMIT = 20


def build_translate_prompt(
    text: str,
    src_lang: str,
    tgt_lang: str,
    tm_matches: list[dict[str, Any]] | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
) -> str:
    """Build a translation prompt with injected TM matches and glossary terms.

    Args:
        text: The source text to translate.
        src_lang: Source language code (e.g., "en").
        tgt_lang: Target language code (e.g., "zh").
        tm_matches: List of TM matches (dicts with source, target, score).
        glossary_terms: List of glossary term dicts (term, translation, confidence).

    Returns:
        Formatted translation prompt string with injected context.
    """
    tm_matches = tm_matches or []
    glossary_terms = glossary_terms or []

    limited_tm = tm_matches[:TM_MATCH_LIMIT]
    limited_glossary = glossary_terms[:GLOSSARY_TERM_LIMIT]

    parts = []

    context_parts = []
    if limited_tm:
        tm_lines = []
        for m in limited_tm:
            src = m.get("source", m.get("src", ""))
            tgt = m.get("target", m.get("tgt", ""))
            score = m.get("score", m.get("imilarity", 0.0))
            tm_lines.append(f"  - \"{src}\" -> \"{tgt}\" (score: {score:.2f})")
        context_parts.append(f"[Translation Memory (top {len(limited_tm)} matches)]\n" + "\n".join(tm_lines))

    if limited_glossary:
        glossary_lines = []
        for t in limited_glossary:
            glossary_lines.append(f"  - {t['term']} -> {t['translation']}")
        context_parts.append(f"[Glossary Terms (top {len(limited_glossary)} terms)]\n" + "\n".join(glossary_lines))

    if context_parts:
        parts.append("\n\n".join(context_parts))

    parts.append(f"[Source Text ({src_lang} -> {tgt_lang})]\n{text}")

    instruction = f"Translate the following {src_lang} text to {tgt_lang}, using the above translation memory and glossary terms when applicable."
    parts.insert(0, instruction)

    return "\n\n".join(parts)