"""Document Profiler — analyze a document and produce a StyleGuide.

This is the LLM-calling half of the ol_style module. The other half
(schema.py, cache.py) is pure data.

Architecture:
    profile_document(content)
        ↓
        ProfileCache.get(content)  ← cache hit → return StyleGuide
        ↓ cache miss
        ModelPool.profile(content, source_lang)  ← LLM call
        ↓
        _parse_profile_response(raw_text) → StyleGuide
        ↓
        ProfileCache.put(content, guide)
        ↓
        return StyleGuide

In OMNI_TEST_FAKE_LLM=1 mode, ``_FakeModelPool.profile()`` returns
a deterministic dict, so tests run without network access.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from ol_style.cache import ProfileCache
from ol_style.schema import StyleGuide

logger = logging.getLogger(__name__)


# Max content length sent to LLM (saves tokens; longer docs get truncated
# with a "[... truncated ...]" marker so the LLM knows the document is long).
_MAX_CONTENT_CHARS = 10_000


def _build_profiling_prompt(content: str, source_lang: str = "en") -> str:
    """Build the LLM prompt that asks the model to profile a document.

    The prompt asks for a JSON object with specific fields. We instruct
    the model to output ONLY JSON (no preamble) so the response is
    parseable.
    """
    # Truncate to avoid blowing token budget
    truncated = content
    if len(content) > _MAX_CONTENT_CHARS:
        truncated = content[:_MAX_CONTENT_CHARS] + "\n\n[... truncated for profiling ...]"

    return f"""Analyze the writing style of the following document (language: {source_lang}).

[USER_TEXT_START]
{truncated}
[USER_TEXT_END]

Return ONLY a JSON object (no prose, no markdown fences) with these fields:
- "tone": overall tone (e.g. "formal", "informal", "academic", "casual", "technical")
- "register": language register (e.g. "technical", "conversational", "literary", "business")
- "target_audience": intended readers (e.g. "developers", "general public", "researchers")
- "key_conventions": list of 2-5 style rules the document follows
- "vocabulary": list of domain-specific terms to prefer
- "avoid": list of words or phrases to avoid
- "summary": 1-2 sentence description of the document's style

Output the JSON object now."""


def _parse_profile_response(raw: str | dict) -> StyleGuide:
    """Parse an LLM response into a StyleGuide.

    Accepts either a raw JSON string or a pre-parsed dict (from
    _FakeModelPool). Tolerates malformed JSON by falling back to a
    default StyleGuide. Tries to extract JSON from a markdown-fenced
    response if present.
    """
    # Fast path: dict input (from _FakeModelPool or pre-parsed)
    if isinstance(raw, dict):
        return StyleGuide.from_dict(raw)

    if not raw or not raw.strip():
        return StyleGuide(summary="(empty LLM response)")

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        # Find the first newline and the last ```
        lines = text.split("\n")
        # Drop first line (```json or ```)
        lines = lines[1:]
        # Drop last line if it's just ```
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try strict JSON parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return StyleGuide.from_dict(data)
    except json.JSONDecodeError:
        pass

    # Fallback: try to find a JSON object in the text
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return StyleGuide.from_dict(data)
        except json.JSONDecodeError:
            pass

    # Last resort: return a default
    logger.warning("Could not parse profiling response: %r", raw[:200])
    return StyleGuide(summary=f"(unparseable LLM response, length={len(raw)})")


async def profile_document(
    content: str,
    source_lang: str = "en",
    config_path: str | None = None,
    model_pool: Any = None,
    cache: ProfileCache | None = None,
) -> StyleGuide:
    """Profile a document's writing style.

    Args:
        content: Document content to profile.
        source_lang: Source language code (default "en").
        config_path: Path to OL YAML config. If None, uses default
            ``config/default.yaml``. Ignored if ``model_pool`` is passed.
        model_pool: Pre-built ModelPool instance. If None, builds
            one from config_path (or default).
        cache: ProfileCache for content-hash based caching. If None,
            uses an in-memory-only cache.

    Returns:
        StyleGuide describing the document's style.

    Behavior:
        - Cache hit: returns the cached StyleGuide without calling the LLM.
        - Cache miss: calls the LLM via ModelPool.profile(), parses the
          response, caches it, and returns.
        - With ``OMNI_TEST_FAKE_LLM=1``: uses ``_FakeModelPool.profile()``
          which returns a deterministic placeholder.
    """
    if cache is None:
        cache = ProfileCache()

    # Try cache first
    cached = cache.get(content)
    if cached is not None:
        return cached

    # Build prompt and call LLM
    prompt = _build_profiling_prompt(content, source_lang)

    if model_pool is None:
        if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
            from ol_pool.fake import _FakeModelPool
            model_pool = _FakeModelPool()
        else:
            from ol_pool.router import ModelPool
            model_pool = ModelPool.get_instance(config_path or "config/default.yaml")

    # Call the pool. Both _FakeModelPool.profile() and the future real
    # ModelPool.profile() will have the same signature.
    raw_response = await model_pool.profile(prompt, source_lang)

    # Parse
    guide = _parse_profile_response(raw_response)

    # Cache and return
    cache.put(content, guide)
    return guide


__all__ = [
    "profile_document",
    "_build_profiling_prompt",
    "_parse_profile_response",
]
