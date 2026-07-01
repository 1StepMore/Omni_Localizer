"""Term extraction using YAKE.

YAKE is imported lazily inside `_probe_yake` so that simply importing
this module (e.g. via `ol_terminology.__init__` which eagerly pulls in
this module) does not trigger heavy ML imports.
"""
import logging
import re

logger = logging.getLogger(__name__)

# CJK regex covers Chinese (CJK Unified Ideographs \u4e00-\u9fff) and
# Japanese (Hiragana \u3040-\u309f + Katakana \u30a0-\u30ff).
# Does NOT cover CJK Extension A/B (rare in modern text) or Korean Hangul.
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]")

_yake = None
_YAKE_AVAILABLE = False


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
    """Extract important terms from a list of texts using YAKE.

    Args:
        texts: List of source texts to extract terms from.

    Returns:
        Dictionary mapping terms to importance scores.
        Lower scores = more relevant (YAKE convention).
        Returns empty dict if texts is empty.
        Raises ImportError if YAKE is not installed.

    Note: YAKE returns (term, score) where lower score = more relevant.
    Callers should sort accordingly (NOT with reverse=True).
    """
    if not texts:
        return {}

    combined_text = " ".join(texts)

    yake_mod = _probe_yake()
    if yake_mod is None:
        raise ImportError(
            "ML dependencies not available. Install: pip install omni-localizer[ml]"
        )
    try:
        yake_model = yake_mod.KeywordExtractor(
            lan="en",
            n=2,
            dedupLim=0.7,
            top=20,
            features=None,
        )
        results = yake_model.extract_keywords(combined_text)
        if not results:
            return {}
        raw = {term: float(score) for term, score in results}
        # CJK post-processing: when input has CJK (Chinese/Japanese kana),
        # drop terms without CJK characters. Pure-English input unaffected.
        # Also drops single-char noise regardless of CJK content.
        if _CJK_RE.search(combined_text):
            raw = {
                term: score
                for term, score in raw.items()
                if len(term) >= 2 and _CJK_RE.search(term)
            }
        if raw:
            logger.debug(f"YAKE extracted {len(raw)} terms (post-filter)")
        return raw
    except Exception as e:
        logger.warning(f"YAKE extraction failed: {e}")
        raise ImportError(
            f"YAKE extraction failed: {e}. Reinstall: pip install --upgrade omni-localizer[ml]"
        ) from e
