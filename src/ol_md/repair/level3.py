"""Level 3 LLM restoration for MD channel.

Phase 3a: LiteLLMRestorer implementation using ModelPool.
"""
import asyncio
from typing import Dict

from ol_core.interfaces import LLMRestorer


class LiteLLMRestorer(LLMRestorer):
    """
    Phase 3a real implementation using LiteLLM Router.

    Uses ModelPool for LLM calls with proper failover and timeout handling.
    """

    def __init__(self, model_pool=None, temperature: float = 0.0):
        if model_pool is None:
            from ol_pool.router import ModelPool
            model_pool = ModelPool()
        self._model_pool = model_pool
        self._temperature = temperature

    def restore_placeholders(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        if not shield_map:
            return translated_text

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                restored = loop.run_until_complete(
                    self._call_llm(translated_text, original_text, shield_map)
                )
                return restored
            finally:
                loop.close()
        except Exception:
            return translated_text

    async def _call_llm(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        # Build a clear mapping of placeholder IDs to original content
        placeholder_mapping = "\n".join(
            f"  {pid}: {content[:200]}{'...' if len(content) > 200 else ''}"
            for pid, content in shield_map.items()
        )

        prompt = f"""You are a placeholder restoration specialist. The translation process shielded certain content (code blocks, math, etc.) with HTML comment markers. Your job is to FIX the translated text by restoring placeholders to their correct positions.

CRITICAL RULES:
1. The text between <!--OL_CODE_X|-- and <!--/OL_CODE_X|--> markers is SHIELDED CONTENT that should NOT be translated - restore it EXACTLY as shown in the mapping below
2. DO NOT translate or modify the shielded content - restore it verbatim
3. Return ONLY the corrected translation text, nothing else

Shielded content mapping (placeholder_id -> original content to restore):
{placeholder_mapping}

Original text with placeholders (what it should look like):
{original_text}

Current broken translation (placeholders may be missing, duplicated, or in wrong positions):
{translated_text}

Return the corrected translation with all placeholders restored to match the original pattern."""

        result = await self._model_pool.translate(
            text=prompt,
            source_lang="en",
            target_lang="en"
        )

        return result


def level3_llm_restore(text: str, original: str, shield_map: dict, restorer) -> str:
    return restorer.restore_placeholders(text, original, shield_map)