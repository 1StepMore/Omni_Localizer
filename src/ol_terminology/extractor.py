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

# N3: full-width space included
_CJK_PUNCT_RE = re.compile(
    r'[\u3000'                        # 　 full-width space (N3)
    r'\uff0c\u3002\u3001\uff1b\uff01\uff1f'  # ，。、；！？
    r'\uff1a\u201c\u201d\u2018\u2019'  # ：""''
    r'\uff08\uff09\u3010\u3011'       # （）【】
    r'\u300a\u300b\u300c\u300d'       # 《》「」
    r'\u300e\u300f\u3008\u3009'       # 『』〈〉
    r'\u00b7\u2026\u2014\u2013]'      # ·…—–
)
# Strip link/image syntax, NOT individual markdown chars (B1 fix: don't strip _ from __init__)
_LINK_RE = re.compile(r'!\[.*?\]\(.*?\)|\[.*?\]\(.*?\)')
_URL_RE = re.compile(r'https?://\S+')
_WS_RE = re.compile(r'[\s\u3000]+')  # \s + full-width space (N3)

# T0.3: Chinese stopwords to filter out (top 40 function words)
_CJK_STOPWORDS = frozenset({
    '的', '了', '是', '在', '我', '你', '他', '她', '它',
    '这', '那', '和', '与', '但', '或', '也', '就', '都',
    '还', '只', '要', '能', '会', '可', '于', '对', '从',
    '向', '至', '以', '为', '把', '被', '让', '给', '着',
    '过', '呢', '吗', '吧', '啊', '哦', '嗯', '噢',
})
# Same character set as _CJK_PUNCT_RE but without \u3000 (full-width space)
_CJK_PUNCT_FILTER_RE = re.compile(
    r'[\uff0c\u3002\u3001\uff1b\uff01\uff1f\uff1a'
    r'\u201c\u201d\u2018\u2019\uff08\uff09'
    r'\u3010\u3011\u300a\u300b\u300c\u300d\u300e\u300f'
    r'\u3008\u3009\u00b7\u2026\u2014\u2013]'
)
_MAX_CJK_TERM_LEN = 10

_yake = None
_YAKE_AVAILABLE = False

_jieba = None
_JIEBA_AVAILABLE = False


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


def _probe_jieba():
    """Lazy probe for jieba. Returns the module on success, None on failure."""
    global _jieba, _JIEBA_AVAILABLE
    if _jieba is not None:
        return _jieba
    try:
        import jieba as _ImportedJieba

        _jieba = _ImportedJieba
        _JIEBA_AVAILABLE = True
        return _jieba
    except Exception as e:
        logger.debug(f"jieba unavailable: {e}")
        _JIEBA_AVAILABLE = False
        return None


def _detect_language(text: str) -> str:
    """Detect dominant language for YAKE lan parameter.

    Uses non-whitespace character counts to avoid diluting CJK ratio
    in text with lots of spacing/newlines.

    Returns:
        "zh" if text is >30% CJK characters (Chinese, Japanese kanji)
        "ja" if text is >10% hiragana/katakana
        "en" otherwise
    """
    non_ws = sum(1 for c in text if not c.isspace())
    if non_ws == 0:
        return "en"
    cjk_count = len(_CJK_RE.findall(text))
    ja_kana = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
    if ja_kana / non_ws > 0.1:
        return "ja"
    if cjk_count / non_ws > 0.3:
        return "zh"
    return "en"


def _clean_text(text: str) -> str:
    """Clean text for YAKE extraction.

    URLs and link/image syntax are always stripped (noise).
    CJK punctuation is stripped only when the text contains CJK characters,
    so English contractions (don't, it's), abbreviations (e.g., Mr.),
    and word-internal characters (user_name, __init__) are preserved.
    """
    text = _URL_RE.sub(' ', text)       # always: URLs are noise
    text = _LINK_RE.sub(' ', text)      # always: link syntax is noise
    if _CJK_RE.search(text):            # CJK-specific: strip CJK punctuation
        text = _CJK_PUNCT_RE.sub(' ', text)
    text = _WS_RE.sub(' ', text)        # always: normalize whitespace
    return text.strip()


def extract_terms(texts: list[str], language: str | None = None) -> dict[str, float]:
    """Extract important terms from a list of texts using YAKE.

    Args:
        texts: List of source texts to extract terms from.
        language: Language hint for YAKE ("en", "zh", "ja", or None for auto-detect).

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

    combined_text = _clean_text(" ".join(texts))

    yake_mod = _probe_yake()
    if yake_mod is None:
        raise ImportError(
            "ML dependencies not available. Install: pip install omni-localizer[ml]"
        )
    try:
        lang = language if language else _detect_language(combined_text)

        # T1.1: For Chinese, pre-segment with jieba (improves YAKE quality)
        if lang == "zh":
            jieba_mod = _probe_jieba()
            if jieba_mod is not None:
                try:
                    words = list(jieba_mod.cut(combined_text))
                    combined_text = " ".join(words)
                except Exception as e:
                    logger.debug(f"jieba.cut failed, falling back: {e}")

        yake_model = yake_mod.KeywordExtractor(
            lan=lang,  # FIX: was hardcoded "en"
            n=1 if lang in ("zh", "ja") else 2,  # FIX: shorter n-grams for CJK
            dedupLim=0.7,
            top=20,
            features=None,
        )
        results = yake_model.extract_keywords(combined_text)
        if not results:
            return {}
        raw = {term: float(score) for term, score in results}
        # CJK post-processing: when input has CJK (Chinese/Japanese kana),
        # drop terms without CJK characters, terms with CJK punctuation,
        # terms exceeding max length, and Chinese stopwords.
        # Pure-English input unaffected.
        if _CJK_RE.search(combined_text):
            raw = {
                term: score
                for term, score in raw.items()
                if len(term) >= 2
                and _CJK_RE.search(term)
                and not _CJK_PUNCT_FILTER_RE.search(term)
                and len(term) <= _MAX_CJK_TERM_LEN
                and term not in _CJK_STOPWORDS
            }
        if raw:
            logger.debug(f"YAKE extracted {len(raw)} terms (post-filter)")
        return raw
    except Exception as e:
        logger.warning(f"YAKE extraction failed: {e}")
        raise ImportError(
            f"YAKE extraction failed: {e}. Reinstall: pip install --upgrade omni-localizer[ml]"
        ) from e
