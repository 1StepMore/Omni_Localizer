"""Punctuation normalizer for OL output post-processing.

Provides two directions of punctuation normalization:
  - normalize_to_english: Chinese → English punctuation (for en target)
  - normalize_to_chinese: English → Chinese punctuation (for zh target)

Uses str.maketrans() for O(1) character translation with zero dependencies.
"""

# ── Chinese → English mappings ──────────────────────────────────────────────
# Chinese punctuation characters to replace
_ZH_PUNCT = (
    "\uff0c\u3002\u3001\uff1a\uff1b\uff01\uff1f\uff08\uff09"  # ，。、：；！？（）
    "\u201c\u201d\u2018\u2019"                                   # “ ” ‘ ’
)
# Corresponding ASCII equivalents (same length as _ZH_PUNCT)
_EN_PUNCT = ",.,:;!?()\"\"''"

_ZH_TO_EN = str.maketrans(
    {zh: en for zh, en in zip(_ZH_PUNCT, _EN_PUNCT)}
)


# ── English → Chinese mappings ──────────────────────────────────────────────
_EN_TO_ZH = str.maketrans({
    ",": "\uff0c",   # , → ，
    ".": "\u3002",   # . → 。
    ":": "\uff1a",   # : → ：
    ";": "\uff1b",   # ; → ；
    "!": "\uff01",   # ! → ！
    "?": "\uff1f",   # ? → ？
    "(": "\uff08",   # ( → （
    ")": "\uff09",   # ) → ）
})


def normalize_to_english(text: str) -> str:
    """Replace Chinese punctuation with English equivalents for English-mode output.

    Maps:
        ， → ,    。 → .    、 → ,    ： → :    ； → ;
        ！ → !    ？ → ?    （ → (    ） → )    “ → "
        ” → "    ‘ → '    ’ → '

    Args:
        text: Input string possibly containing Chinese punctuation.

    Returns:
        String with Chinese punctuation replaced by English equivalents.
    """
    return text.translate(_ZH_TO_EN)


def normalize_to_chinese(text: str) -> str:
    """Replace ASCII punctuation with Chinese equivalents for Chinese-mode output.

    Maps:
        , → ，    . → 。    : → ：    ; → ；    ! → ！
        ? → ？    ( → （    ) → ）

    Note: ASCII straight quotes (\" '\") are left as-is since they are
    context-dependent and cannot be directionally resolved via simple
    character mapping.

    Args:
        text: Input string possibly containing ASCII punctuation.

    Returns:
        String with ASCII punctuation replaced by Chinese equivalents.
    """
    return text.translate(_EN_TO_ZH)
