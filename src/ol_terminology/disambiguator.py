"""Term disambiguation for polysemous glossary entries."""
from typing import Any, Callable

import logging

logger = logging.getLogger(__name__)

ModelPool = Any


def _default_selector(candidates: list[dict[str, Any]], context: str) -> dict[str, Any]:
    """Select best translation based on confidence only (fallback).

    Args:
        candidates: List of translation candidates.
        context: Source text context.

    Returns:
        Highest confidence candidate.
    """
    if not candidates:
        return {}
    return max(candidates, key=lambda c: c.get("confidence", 0.0))


class Disambiguator:
    """Resolves polysemous terms using context-aware selection.

    Integrates with LLM via dependency injection for smart disambiguation.
    Falls back to confidence-based selection when LLM is unavailable.
    """

    def __init__(
        self,
        model_pool: ModelPool | None = None,
        llm_selector: Callable[[list[dict[str, Any]], str], dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the disambiguator.

        Args:
            model_pool: Optional LLM model pool for context-aware selection.
            llm_selector: Optional custom selector function. If provided, takes
                (candidates, context) and returns selected candidate dict.
                If not provided and model_pool is set, uses LLM-based selection.
                If neither is set, falls back to confidence-based selection.
        """
        self._model_pool = model_pool
        self._llm_selector = llm_selector or _default_selector

    def disambiguate(
        self,
        text: str,
        glossary: dict[str, dict[str, Any]],
    ) -> dict[str, str]:
        """Resolve polysemous terms in text based on glossary.

        Detects terms that have multiple translations in the glossary
        and selects the most contextually appropriate one.

        Args:
            text: Source text to disambiguate.
            glossary: Glossary dictionary with term metadata.

        Returns:
            Dictionary mapping terms to their resolved translations.
            Only includes terms that have multiple translation variants.
        """
        if not text or not glossary:
            return {}

        text_lower = text.lower()
        resolved: dict[str, str] = {}

        for term, meta in glossary.items():
            if term not in text and term.lower() not in text_lower:
                continue

            variants = meta.get("variants", {})
            if len(variants) <= 1:
                continue

            candidates = []
            primary_translation = meta.get("translation", "")
            if primary_translation:
                candidates.append({
                    "term": term,
                    "translation": primary_translation,
                    "confidence": meta.get("confidence", 1.0),
                    "source": "primary",
                })

            for variant_name, variant_translation in variants.items():
                if variant_translation and variant_translation != primary_translation:
                    candidates.append({
                        "term": term,
                        "translation": variant_translation,
                        "variant": variant_name,
                        "confidence": meta.get("confidence", 1.0) * 0.9,
                        "source": "variant",
                    })

            if len(candidates) <= 1:
                continue

            selected = self._select_translation(candidates, text)
            if selected:
                resolved[term] = selected["translation"]

        logger.debug(f"Disambiguated {len(resolved)} polysemous terms")
        return resolved

    def _select_translation(
        self,
        candidates: list[dict[str, Any]],
        context: str,
    ) -> dict[str, Any] | None:
        """Select the best translation from candidates using configured selector.

        Args:
            candidates: List of translation candidates.
            context: Source text context.

        Returns:
            Selected candidate dict or None.
        """
        if self._model_pool is not None and self._llm_selector is not _default_selector:
            return self._llm_selector(candidates, context)

        if self._model_pool is not None:
            return self._llm_selector(candidates, context)

        return _default_selector(candidates, context)


def disambiguate(
    text: str,
    glossary: dict[str, dict[str, Any]],
    model_pool: ModelPool | None = None,
) -> dict[str, str]:
    """Convenience function for disambiguation.

    Creates a Disambiguator and resolves polysemous terms in text.

    Args:
        text: Source text to disambiguate.
        glossary: Glossary dictionary.
        model_pool: Optional LLM model pool for context-aware selection.

    Returns:
        Dictionary mapping terms to their resolved translations.
    """
    disambiguator = Disambiguator(model_pool=model_pool)
    return disambiguator.disambiguate(text, glossary)