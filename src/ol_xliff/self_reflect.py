"""LLM self-reflection pass for OL (Gate 8, Issue #64).

After all trans-units are translated and quality gates have run, this
module makes a single LLM call across the translated output to let the
LLM self-reflect on its own work and identify/fix issues such as:

1. Terminology errors or inconsistent glossary usage
2. Missing content or incomplete sentences
3. Awkward phrasing or unnatural expressions
4. Grammar mistakes (subject-verb agreement, articles, tense)
5. Accuracy issues in the translation

Uses the ``system_message_override`` to replace the default translator
message with a "self-reflective reviewer" role. Follows the same pattern
as ``polish_translated_units()`` in polish.py but differs in purpose:
polish fixes cross-unit inconsistencies; self-reflection improves
per-unit translation quality against the source.
"""
from __future__ import annotations

import logging
import re

from ol_pool.router import has_source_language_residual

logger = logging.getLogger(__name__)

_MAX_SELF_REFLECT_CHARS = 50_000

_CORRECTION_RE = re.compile(
    r"id:\s*(\S+)\s*\n"
    r"fix:\s*(.+?)\s*\n"
    r"reason:\s*(.+?)(?=\nid:|\nNO_ISSUES|\Z)",
    re.DOTALL,
)

_SELF_REFLECT_SYSTEM_MESSAGE = (
    "You are a self-reflective translator. Review your own translation below "
    "and identify any issues: terminology errors, grammar mistakes, incomplete "
    "sentences, awkward phrasing, or inaccurate translations. Then provide an "
    "improved version. Do NOT introduce new errors or change correct translations. "
    "Focus on accuracy and fluency."
)


def _build_self_reflect_prompt(pairs: list[dict]) -> str:
    """Build the prompt for the self-reflection LLM call."""
    lines = [
        "Review your own translations below and identify issues.",
        "For each issue found, output in this exact format:",
        "  id: <unit_id>",
        "  fix: <corrected target text>",
        "  reason: <issue identified>",
        "",
        "Separate multiple fixes with a blank line.",
        "If no issues found, output only: NO_ISSUES",
        "",
    ]
    for p in pairs:
        lines.append("---")
        lines.append(f"id: {p['id']}")
        if p.get("src"):
            lines.append(f"src: {p['src']}")
        lines.append(f"tgt: {p['tgt']}")
        if p.get("warnings"):
            lines.append(f"quality_gate_warnings: {p['warnings']}")
    lines.append("---")
    return "\n".join(lines)


def _parse_self_reflect_response(response: str) -> list[dict]:
    """Parse the self-reflection LLM response into correction dicts."""
    response = response.strip()
    if response == "NO_ISSUES" or not response:
        return []
    corrections: list[dict] = []
    for match in _CORRECTION_RE.finditer(response):
        corrections.append({
            "id": match.group(1).strip(),
            "fix": match.group(2).strip(),
            "reason": match.group(3).strip(),
        })
    if corrections:
        return corrections
    # Fallback: try breaking by blank lines
    blocks = re.split(r'\n\s*\n', response)
    for block in blocks:
        id_match = re.search(r'id:\s*(\S+)', block)
        fix_match = re.search(
            r'fix:\s*(.+?)(?=\s*\n\s*(?:reason|id)|$)',
            block, re.DOTALL,
        )
        reason_match = re.search(r'reason:\s*(.+?)$', block, re.MULTILINE)
        if id_match and fix_match:
            corrections.append({
                "id": id_match.group(1).strip(),
                "fix": fix_match.group(1).strip(),
                "reason": reason_match.group(1).strip() if reason_match else "unknown",
            })
    return corrections


async def self_reflect_translated_units(
    units: list,
    src_lang: str,
    tgt_lang: str,
    pool,
    warnings_per_unit: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """Apply the self-reflection pass to a list of TranslationUnit objects.

    For each unit with target text, sends a prompt to the LLM showing the
    source, target, and any quality gate warnings, then asks the LLM to
    self-reflect and provide an improved translation.

    Args:
        units: List of TranslationUnit objects with ``source_text`` and
            ``target_text`` populated.
        src_lang: Source language code.
        tgt_lang: Target language code.
        pool: Async LLM pool with a ``.translate()`` method.
        warnings_per_unit: Optional dict mapping unit_id to list of
            ``OL_WARN`` strings from quality gates.

    Returns:
        Dict mapping unit_id to list of self-reflection warning strings
        (e.g. ``self_reflect:<reason>``). Empty dict means no corrections.
    """
    pairs: list[dict] = []
    for u in units:
        if not u.target_text:
            continue
        pair: dict = {
            "id": u.unit_id,
            "src": u.source_text[:200] if u.source_text != u.target_text else "",
            "tgt": u.target_text[:200],
        }
        if warnings_per_unit and u.unit_id in warnings_per_unit:
            unit_warnings = warnings_per_unit[u.unit_id]
            if unit_warnings:
                pair["warnings"] = "; ".join(unit_warnings[:3])
        pairs.append(pair)

    if not pairs:
        return {}

    total_chars = sum(len(p["src"]) + len(p["tgt"]) for p in pairs)
    if total_chars > _MAX_SELF_REFLECT_CHARS:
        logger.warning(
            f"Self-reflection skipped: {len(pairs)} units, {total_chars} chars "
            f"exceeds max {_MAX_SELF_REFLECT_CHARS}."
        )
        return {"_self_reflect": ["Skipped: content too large for self-reflection budget guard"]}

    prompt = _build_self_reflect_prompt(pairs)
    logger.info(
        f"Self-reflection pass: checking {len(pairs)} units "
        f"({total_chars} chars)"
    )

    try:
        result = await pool.translate(
            "", src_lang, tgt_lang, context=prompt, temperature=0.0,
            system_message_override=_SELF_REFLECT_SYSTEM_MESSAGE,
        )
    except Exception as e:
        logger.warning(f"Self-reflection LLM call failed: {e}")
        return {"_self_reflect": [f"Self-reflection LLM call failed: {e}"]}

    corrections = _parse_self_reflect_response(result)
    if not corrections:
        logger.info("Self-reflection pass: no issues found")
        return {}

    warnings: dict[str, list[str]] = {}
    unit_map = {u.unit_id: u for u in units}
    for corr in corrections:
        uid = corr["id"]
        if uid not in unit_map:
            logger.warning(f"Self-reflection correction references unknown unit {uid}")
            continue
        old_text = unit_map[uid].target_text
        new_text = corr["fix"]
        if new_text and new_text != old_text:
            if has_source_language_residual(new_text, src_lang, tgt_lang):
                logger.warning(
                    f"Self-reflection correction SKIPPED for unit={uid}: "
                    f"fix reverts to source language "
                    f"({new_text[:80]!r})"
                )
                continue
            logger.info(
                f"Self-reflection correction: unit={uid} "
                f"old={old_text[:80]!r} "
                f"new={new_text[:80]!r} "
                f"reason={corr['reason']!r}"
            )
            unit_map[uid].target_text = new_text
            warnings.setdefault(uid, []).append(
                f"self_reflect:{corr['reason']}"
            )

    applied = len(corrections)
    logger.info(
        f"Self-reflection pass: applied {applied} correction(s) to "
        f"{len(warnings)} unit(s)"
    )
    return warnings


async def self_reflect_md_text(
    text: str, src_lang: str, tgt_lang: str, pool,
    warnings_text: str | None = None,
) -> str:
    """Apply the self-reflection pass to a markdown string.

    Splits text by paragraph boundaries (\\n\\n), creates pseudo
    TranslationUnit objects, runs the self-reflection internals, then
    rejoins.  For MD both source and target are the same translated text
    (the LLM self-reflects on output quality without source comparison).

    Args:
        text: Translated markdown text to self-reflect on.
        src_lang: Source language code.
        tgt_lang: Target language code.
        pool: Async LLM pool.
        warnings_text: Optional string of quality gate warnings.

    Returns:
        Self-reflected text (may be unchanged if no corrections).
    """
    if not text or not text.strip():
        return text

    paragraphs = text.split("\n\n")
    if not paragraphs:
        return text

    from ol_core.dataclass import TranslationUnit

    units = []
    for i, p in enumerate(paragraphs):
        if not p.strip():
            continue
        unit = TranslationUnit(
            unit_id=f"md-para-{i}",
            source_text=p,
            target_text=p,
            shield_map={},
        )
        units.append(unit)

    if not units:
        return text

    result = await self_reflect_translated_units(
        units, src_lang, tgt_lang, pool, warnings_per_unit=None,
    )

    if not result:
        return text

    para_index_map = {f"md-para-{i}": i for i in range(len(paragraphs))}
    for uid in result:
        idx = para_index_map.get(uid)
        if idx is not None:
            unit = next((u for u in units if u.unit_id == uid), None)
            if unit and unit.target_text:
                paragraphs[idx] = unit.target_text

    applied = len(result)
    logger.info(f"MD self-reflection pass: applied corrections to {applied} unit(s)")
    return "\n\n".join(paragraphs)
