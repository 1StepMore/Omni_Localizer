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
        placeholder_list = ", ".join(shield_map.values())

        prompt = f"""Restore these placeholders to their exact positions in the translation.

Original text with placeholders:
{original_text}

Current translation (placeholders may be missing or moved):
{translated_text}

Placeholders to restore:
{placeholder_list}

Return the translation with all placeholders restored to their correct positions.
Only return the restored translation, nothing else."""

        result = await self._model_pool.translate(
            text=prompt,
            source_lang="en",
            target_lang="en"
        )

        return result


def level3_llm_restore(text: str, original: str, shield_map: dict, restorer) -> str:
    return restorer.restore_placeholders(text, original, shield_map)