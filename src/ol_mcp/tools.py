"""MCP tools for Omni-Localizer.

All tools are async functions that wrap existing OL infrastructure.
Each tool returns a dict with consistent success/warnings structure for agent-friendly error handling.
"""
import asyncio
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ol_concurrency.scheduler import ConcurrencyLimiter
from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_pool.router import ModelPool
from ol_terminology.glossary import get_relevant_terms as _get_relevant_terms, load_glossary_from_path
from ol_terminology.rag_injector import build_translate_prompt
from ol_tm.service import TMService

# Create the MCP server
mcp = FastMCP("omni-localizer")

# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class TranslateInput(BaseModel):
    """Input for translate_md_text."""

    content: str = Field(description="Markdown text to translate")
    source_lang: str = Field(description="Source language code (e.g. en, zh, ja)")
    target_lang: str = Field(description="Target language code")
    glossary_path: str | None = Field(default=None, description="Path to JSON glossary file")
    config_path: str | None = Field(default=None, description="Path to LLM config")
    add_frontmatter: bool = Field(default=False, description="Add YAML frontmatter to output")


class JudgeInput(BaseModel):
    """Input for judge_text."""

    source: str = Field(description="Original source text")
    target: str = Field(description="Translated target text")
    source_lang: str = Field(default="en", description="Source language code")
    target_lang: str = Field(default="en", description="Target language code")
    glossary: dict[str, Any] | None = Field(default=None, description="Inline glossary dict")


class LoadGlossaryInput(BaseModel):
    """Input for load_glossary."""

    path: str = Field(description="Path to JSON glossary file")
    config_dir: str | None = Field(default=None, description="Base dir for relative paths")


class GetRelevantTermsInput(BaseModel):
    """Input for get_relevant_terms."""

    text: str = Field(description="Source text to match against")
    glossary: dict[str, dict[str, Any]] = Field(description="Glossary dict from load_glossary")
    top_k: int = Field(default=5, description="Maximum terms to return")


class SearchTMInput(BaseModel):
    """Input for search_tm."""

    source_text: str = Field(description="Text to search for in TM")
    tmx_path: str = Field(description="Path to .tmx translation memory file")
    threshold: float = Field(default=0.85, description="Minimum similarity threshold (0-1)")


class BatchTranslateInput(BaseModel):
    """Input for batch_translate_texts."""

    texts: list[str] = Field(description="List of markdown texts to translate")
    source_lang: str = Field(description="Source language code")
    target_lang: str = Field(description="Target language code")
    glossary_path: str | None = Field(default=None, description="Path to JSON glossary")
    concurrency: int = Field(default=5, description="Max parallel translations")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_config_path(config_path: str | None) -> str:
    """Resolve config path: explicit param > env var > default."""
    if config_path:
        return config_path
    return os.environ.get("OL_CONFIG_PATH", "config/default.yaml")


# ---------------------------------------------------------------------------
# Token estimation and chunking
# ---------------------------------------------------------------------------

SAFE_TOKEN_BUDGET = int(503808 * 0.8)  # ~403K tokens (20% buffer for prompt wrapper overhead)

def _estimate_tokens(text: str) -> int:
    """Estimate token count using CJK/EN character ratio formula.

    MiniMax-M2.7 tokenizer approximation:
    - CJK (Chinese/Japanese/Korean): 1 token ≈ 4 characters
    - Non-CJK (English, symbols): 1 token ≈ 5 characters
    """
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return int(cjk / 4 + (len(text) - cjk) / 5)


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text at priority boundaries within max_chars budget.

    Priority order (P0=highest):
    - P0: --- (horizontal rule — strongest semantic break)
    - P1: # ## ### (markdown headings — natural section break)
    - P2: ``` (code fences — NEVER split inside a code block)
    - P3: \\n\\n (paragraph break — core boundary)
    - P4: sentence-end punctuation (CJK: 。！？ / EN: .!?)
    - P5: hard-split at max_chars (last resort, cut mid-sentence)

    Returns:
        List of text chunks, each <= max_chars characters.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []

    # P0: Split on --- (horizontal rules) — these are document-level separators
    hr_chunks = text.split('\n---\n')
    if len(hr_chunks) > 1:
        # Recursively chunk each HR section, then re-add the HR as separator
        for i, section in enumerate(hr_chunks):
            if i > 0:
                chunks.append('---')
            if len(section) <= max_chars:
                if section:
                    chunks.append(section)
            else:
                chunks.extend(_chunk_text(section, max_chars))
        return chunks

    # P1: Split on markdown headings (# ## ###)
    heading_pattern = '\n#'
    heading_chunks = text.split(heading_pattern)
    if len(heading_chunks) > 1:
        for i, section in enumerate(heading_chunks):
            if i > 0:
                # Re-add the # that was split off
                section = '#' + section
            if len(section) <= max_chars:
                if section:
                    chunks.append(section)
            else:
                chunks.extend(_chunk_text(section, max_chars))
        return chunks

    # P2: Split on code fences (```) — never split inside code blocks
    fence_chunks = text.split('\n```\n')
    if len(fence_chunks) > 1:
        for i, section in enumerate(fence_chunks):
            if i % 2 == 1:
                # Odd indices are inside code fences — don't split
                if section:
                    if len(section) <= max_chars:
                        chunks.append('\n```\n' + section + '\n```\n')
                    else:
                        # Hard-split code block at max_chars (code can't be safely split)
                        for j in range(0, len(section), max_chars):
                            if j > 0:
                                chunks.append('\n```\n')  # re-open fence after split
                            chunk = section[j:j + max_chars]
                            chunks.append(chunk)
                            if j + max_chars < len(section):
                                chunks.append('\n```\n')  # close and reopen
            else:
                # Even indices are outside code fences — can split
                if len(section) <= max_chars:
                    if section:
                        chunks.append(section)
                else:
                    chunks.extend(_chunk_text(section, max_chars))
        return chunks

    # P3: Split on paragraph breaks (\\n\\n)
    para_chunks = text.split('\n\n')
    if len(para_chunks) > 1:
        current = ''
        for section in para_chunks:
            if len(current) + 2 + len(section) <= max_chars:
                if current:
                    current += '\n\n' + section
                else:
                    current = section
            else:
                if current:
                    chunks.append(current)
                if len(section) <= max_chars:
                    current = section
                else:
                    # Section too big even for one paragraph — recurse
                    sub_chunks = _chunk_text(section, max_chars)
                    # Don't start a new current from last sub-chunk, just append all
                    if len(sub_chunks) > 1:
                        chunks.extend(sub_chunks[:-1])
                        current = sub_chunks[-1] if sub_chunks else ''
                    else:
                        current = sub_chunks[0] if sub_chunks else ''
        if current:
            chunks.append(current)
        return chunks

    # P4: Split on sentence-end punctuation
    for punct in ['。', '！', '？', '. ', '! ', '? ']:
        if punct in text:
            sent_chunks = text.split(punct)
            current = ''
            for i, sentence in enumerate(sent_chunks):
                sentence_with_punct = sentence + (punct if i < len(sent_chunks) - 1 else '')
                if len(current) + len(sentence_with_punct) <= max_chars:
                    current += sentence_with_punct
                else:
                    if current:
                        chunks.append(current)
                    if len(sentence_with_punct) <= max_chars:
                        current = sentence_with_punct
                    else:
                        # Sentence too long even alone — hard split
                        for j in range(0, len(sentence_with_punct), max_chars):
                            chunk = sentence_with_punct[j:j + max_chars]
                            chunks.append(chunk)
                        current = ''
            if current:
                chunks.append(current)
            return chunks

    # P5: Hard split at max_chars as last resort
    for i in range(0, len(text), max_chars):
        chunk = text[i:i + max_chars]
        if chunk:
            chunks.append(chunk)

    return chunks


async def _translate_single(
    content: str,
    source_lang: str,
    target_lang: str,
    glossary: dict[str, dict[str, Any]] | None,
    config_path: str,
) -> tuple[str, list[str]]:
    """Translate a single text through shield → translate → repair → unshield."""
    warnings: list[str] = []

    shielded, shield_map = shield_markdown(content)

    context = None
    if glossary:
        terms = _get_relevant_terms(shielded, glossary=glossary, top_k=5)
        if terms:
            context = build_translate_prompt(
                text=shielded,
                src_lang=source_lang,
                tgt_lang=target_lang,
                tm_matches=None,
                glossary_terms=terms,
            )

    pool = ModelPool(config_path)
    translated = await pool.translate(shielded, source_lang, target_lang, context)

    if shield_map:
        unshielded = unshield_markdown(translated, shield_map)
        repaired = MDRepairPipeline().repair(unshielded, content, shield_map)
    else:
        repaired = translated

    return repaired, warnings


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


@mcp.tool(description="Translate markdown text directly without file I/O.")
async def translate_md_text(
    content: str,
    source_lang: str,
    target_lang: str,
    glossary_path: str | None = None,
    config_path: str | None = None,
    add_frontmatter: bool = False,
    max_chars_per_chunk: int | None = None,
) -> str:
    """
    Translate markdown text using OL's translation pipeline.

    Handles code blocks, links, images automatically (preserved, not translated).
    Runs through shield → translate → repair → unshield pipeline.
    Auto-chunks content when max_chars_per_chunk is set and content exceeds the limit.

    Returns a JSON string with: success, translated, warnings, source_lang, target_lang
    """
    import json

    warnings: list[str] = []
    resolved_config_path = _get_config_path(config_path)

    try:
        glossary: dict[str, dict[str, Any]] | None = None
        if glossary_path:
            try:
                glossary = load_glossary_from_path(
                    glossary_path,
                    config_dir=Path(glossary_path).parent if not Path(glossary_path).is_absolute() else None,
                )
            except Exception as e:
                warnings.append(f"Glossary load failed: {e}")

        # Auto-chunking: split large content and translate in sequence
        if max_chars_per_chunk is not None and len(content) > max_chars_per_chunk:
            all_chunks = _chunk_text(content, max_chars_per_chunk)
            all_warnings: list[str] = []
            translated_parts: list[str] = []
            from ol_cli import _generate_frontmatter, _validate_lang_code, _get_ol_version
            for idx, chunk in enumerate(all_chunks):
                chunk_result, chunk_warnings = await _translate_single(
                    chunk,
                    source_lang,
                    target_lang,
                    glossary,
                    resolved_config_path,
                )
                translated_parts.append(chunk_result)
                all_warnings.extend(chunk_warnings)
            result = ''.join(translated_parts)
            all_warnings.append(f"Content split into {len(all_chunks)} chunks for translation")
            warnings = all_warnings
            if add_frontmatter:
                safe_src = _validate_lang_code(source_lang)
                safe_tgt = _validate_lang_code(target_lang)
                frontmatter = _generate_frontmatter(
                    source_lang=safe_src,
                    target_lang=safe_tgt,
                    original_filename="input.md",
                    ol_version=_get_ol_version(),
                )
                result = frontmatter + result
            return json.dumps(
                {
                    "success": True,
                    "translated": result,
                    "warnings": warnings,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                },
                ensure_ascii=False,
            )

        result, _ = await _translate_single(
            content,
            source_lang,
            target_lang,
            glossary,
            resolved_config_path,
        )

        from ol_cli import _generate_frontmatter, _validate_lang_code, _get_ol_version

        if add_frontmatter:
            safe_src = _validate_lang_code(source_lang)
            safe_tgt = _validate_lang_code(target_lang)
            frontmatter = _generate_frontmatter(
                source_lang=safe_src,
                target_lang=safe_tgt,
                original_filename="input.md",
                ol_version=_get_ol_version(),
            )
            result = frontmatter + result

        return json.dumps(
            {
                "success": True,
                "translated": result,
                "warnings": warnings,
                "source_lang": source_lang,
                "target_lang": target_lang,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "translated": "",
                "warnings": warnings + [str(e)],
                "source_lang": source_lang,
                "target_lang": target_lang,
            },
            ensure_ascii=False,
        )


@mcp.tool(description="Evaluate translation quality using LLM judge.")
async def judge_text(
    source: str,
    target: str,
    source_lang: str = "en",
    target_lang: str = "en",
    glossary: dict[str, Any] | None = None,
) -> str:
    """
    Evaluate translation quality with rubric scores.

    Returns: success, score (0-100), reason, judge_scores breakdown, warnings
    """
    import json

    warnings: list[str] = []

    try:
        config_path = _get_config_path(None)
        pool = ModelPool(config_path)
        result = await pool.judge(
            source,
            target,
            source_lang,
            target_lang,
            glossary,
        )

        return json.dumps(
            {
                "success": True,
                "score": result.get("score", 50),
                "reason": result.get("reason", ""),
                "judge_scores": {
                    "adequacy": result.get("adequacy", 50),
                    "fluency": result.get("fluency", 50),
                    "terminology_consistency": result.get("terminology_consistency", 50),
                    "format_preservation": result.get("format_preservation", 50),
                },
                "warnings": warnings,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "score": 0,
                "reason": "",
                "judge_scores": {},
                "warnings": warnings + [str(e)],
            },
            ensure_ascii=False,
        )


@mcp.tool(description="Load a JSON glossary file for use in translation.")
async def load_glossary(path: str, config_dir: str | None = None) -> str:
    """
    Load a JSON glossary file.

    Returns: success, glossary dict, term_count, warnings
    """
    import json

    warnings: list[str] = []

    try:
        glossary = load_glossary_from_path(
            path,
            config_dir=Path(config_dir) if config_dir else None,
        )
        return json.dumps(
            {
                "success": True,
                "glossary": glossary,
                "term_count": len(glossary),
                "warnings": warnings,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "glossary": {},
                "term_count": 0,
                "warnings": warnings + [str(e)],
            },
            ensure_ascii=False,
        )


@mcp.tool(description="Extract relevant glossary terms for a given text.")
async def get_relevant_terms(
    text: str,
    glossary: dict[str, dict[str, Any]],
    top_k: int = 5,
) -> str:
    """
    Select top-k terms from glossary relevant to the given text.

    Matching is based on exact/partial substring + confidence scoring.

    Returns: success, terms list, count
    """
    import json

    try:
        terms = _get_relevant_terms(text, glossary, top_k=top_k)
        return json.dumps(
            {
                "success": True,
                "terms": terms,
                "count": len(terms),
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "terms": [],
                "count": 0,
                "warnings": [str(e)],
            },
            ensure_ascii=False,
        )


@mcp.tool(description="Search translation memory for similar past translations.")
async def search_tm(
    source_text: str,
    tmx_path: str,
    threshold: float = 0.85,
) -> str:
    """
    Search TMX file for similar past translations.

    Uses embedding-based similarity search with configurable threshold.

    Returns: success, matches list, count
    """
    import json

    warnings: list[str] = []

    try:
        svc = TMService(tmx_path)
        matches = svc.search(source_text, threshold=threshold)
        return json.dumps(
            {
                "success": True,
                "matches": [
                    {
                        "source": m.source,
                        "target": m.target,
                        "similarity": m.similarity,
                        "language_pair": m.language_pair,
                    }
                    for m in matches
                ],
                "count": len(matches),
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "matches": [],
                "count": 0,
                "warnings": warnings + [str(e)],
            },
            ensure_ascii=False,
        )


@mcp.tool(description="Translate multiple texts in parallel.")
async def batch_translate_texts(
    texts: list[str],
    source_lang: str,
    target_lang: str,
    glossary_path: str | None = None,
    concurrency: int = 5,
    max_chars_per_chunk: int | None = None,
) -> str:
    """
    Translate multiple markdown texts in parallel using asyncio.gather.

    Each text goes through full shield → translate → repair → unshield pipeline.
    Respects concurrency limit via ConcurrencyLimiter.

    Returns: success, results list with per-item success/translated/warnings, total, succeeded, failed
    """
    import json

    warnings: list[str] = []
    config_path = _get_config_path(None)

    glossary: dict[str, dict[str, Any]] | None = None
    if glossary_path:
        try:
            glossary = load_glossary_from_path(glossary_path)
        except Exception as e:
            warnings.append(f"Glossary load failed: {e}")

    async def translate_one(idx: int, text: str) -> dict[str, Any]:
        try:
            # Chunking: split large text and translate each chunk
            if max_chars_per_chunk is not None and len(text) > max_chars_per_chunk:
                chunks = _chunk_text(text, max_chars_per_chunk)
                all_warnings: list[str] = []
                translated_parts: list[str] = []
                for chunk in chunks:
                    chunk_result, chunk_warnings = await _translate_single(
                        chunk,
                        source_lang,
                        target_lang,
                        glossary,
                        config_path,
                    )
                    translated_parts.append(chunk_result)
                    all_warnings.extend(chunk_warnings)
                return {
                    "index": idx,
                    "success": True,
                    "translated": ''.join(translated_parts),
                    "warnings": all_warnings,
                    "chunked": True,
                }
            # Single-shot translation
            result, w = await _translate_single(
                text,
                source_lang,
                target_lang,
                glossary,
                config_path,
            )
            return {"index": idx, "success": True, "translated": result, "warnings": w, "chunked": False}
        except Exception as e:
            return {"index": idx, "success": False, "translated": "", "warnings": [str(e)], "chunked": False}

    limiter = ConcurrencyLimiter(concurrency)

    async def guarded(idx: int, text: str) -> dict[str, Any]:
        async with limiter.translation(timeout=180.0):
            return await translate_one(idx, text)

    tasks = [guarded(i, text) for i, text in enumerate(texts)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed.append({"index": i, "success": False, "translated": "", "warnings": [str(result)]})
            failed += 1
        elif result.get("success"):
            processed.append(result)
            succeeded += 1
        else:
            processed.append(result)
            failed += 1

    return json.dumps(
        {
            "success": failed == 0,
            "results": processed,
            "total": len(texts),
            "succeeded": succeeded,
            "failed": failed,
            "warnings": warnings,
        },
        ensure_ascii=False,
    )