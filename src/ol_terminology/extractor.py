"""Term extraction using KeyBERT with YAKE fallback.

KeyBERT and YAKE are imported lazily inside `_probe_keybert` /
`_probe_yake` so that simply importing this module (e.g. via
`ol_terminology.__init__` which eagerly pulls in this module) does
not trigger sentence-transformers model download. This fixes
E2E-04 where `from keybert import KeyBERT` at module top-level
caused `ol_cli translate-xliff` to hang in environments without
pre-downloaded HF models.
"""
import logging

logger = logging.getLogger(__name__)

_KeyBERT = None
_yake = None
_KEYBERT_AVAILABLE = False
_YAKE_AVAILABLE = False


def _probe_keybert():
    """Lazy probe for KeyBERT. Returns the class on success, None on failure."""
    global _KeyBERT, _KEYBERT_AVAILABLE
    if _KeyBERT is not None:
        return _KeyBERT
    try:
        from keybert import KeyBERT as _ImportedKeyBERT

        _KeyBERT = _ImportedKeyBERT
        _KEYBERT_AVAILABLE = True
        return _KeyBERT
    except Exception as e:
        logger.debug(f"KeyBERT unavailable: {e}")
        _KEYBERT_AVAILABLE = False
        return None


def _probe_yake():
    """Lazy probe for YAKE. Returns the module on success, None on failure."""
    global _yake, _YAKE_AVAILABLE
    if _yake is not None:
        return _yake
    try:
        import yake as _ImportedYake

        _yake = _ImportedYake
        _YAKE_AVAILABLE = True
        return _yake
    except Exception as e:
        logger.debug(f"YAKE unavailable: {e}")
        _YAKE_AVAILABLE = False
        return None


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

    KeyBERT = _probe_keybert()
    if KeyBERT is not None:
        try:
            kw_model = KeyBERT()
            results = kw_model.extract_keywords(
                combined_text,
                keyphrase_ngram_range=(1, 2),
                stop_words="english",
                top_n=20,
            )
            if results:
                logger.debug(f"KeyBERT extracted {len(results)} terms")
                return {term: float(score) for term, score in results}
        except Exception as e:
            logger.warning(f"KeyBERT extraction failed: {e}, falling back to YAKE")

    yake_mod = _probe_yake()
    if yake_mod is not None:
        try:
            yake_model = yake_mod.KeywordExtractor(
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
