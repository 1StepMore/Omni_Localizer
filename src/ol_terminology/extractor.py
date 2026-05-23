"""Term extraction using KeyBERT with YAKE fallback."""
from typing import Any

import logging

logger = logging.getLogger(__name__)

try:
    from keybert import KeyBERT

    _KEYBERT_AVAILABLE = True
except ImportError:
    _KEYBERT_AVAILABLE = False
    KeyBERT = None

try:
    import yake

    _YAKE_AVAILABLE = True
except ImportError:
    _YAKE_AVAILABLE = False
    yake = None


def extract_terms(texts: list[str]) -> dict[str, float]:
    """Extract important terms from a list of texts.

    Uses KeyBERT with sentence-transformers as primary extractor.
    Falls back to YAKE if KeyBERT is unavailable or fails.

    Args:
        texts: List of source texts to extract terms from.

    Returns:
        Dictionary mapping terms to importance scores (higher = more important).
        Returns empty dict if both KeyBERT and YAKE fail.
    """
    if not texts:
        return {}

    combined_text = " ".join(texts)

    if _KEYBERT_AVAILABLE:
        try:
            kw_model = KeyBERT()
            results = kw_model.extract_keywords(
                combined_text,
                keyphrase_ngrams=(1, 2),
                stop_words="english",
                top_n=20,
            )
            if results:
                logger.debug(f"KeyBERT extracted {len(results)} terms")
                return {term: float(score) for term, score in results}
        except Exception as e:
            logger.warning(f"KeyBERT extraction failed: {e}, falling back to YAKE")

    if _YAKE_AVAILABLE:
        try:
            yake_model = yake.KeywordExtractor(
                lan="en",
                n=2,
                dedupLim=0.7,
                top=20,
                features=None,
            )
            results = yake_model.extract_keywords(combined_text)
            if results:
                logger.debug(f"YAKE extracted {len(results)} terms")
                return {term: float(score) for term, score in results}
        except Exception as e:
            logger.warning(f"YAKE extraction failed: {e}")

    logger.error("Both KeyBERT and YAKE failed to extract terms")
    return {}