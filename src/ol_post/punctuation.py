"""Punctuation normalizer for OL output post-processing.

Provides two directions of punctuation normalization:
  - normalize_to_english: Chinese → English punctuation (for en target)
  - normalize_to_chinese: English → Chinese punctuation (for zh target)

Uses str.maketrans() for O(1) character translation with zero dependencies.

Issue #5 (OL v0.4.6 → v0.4.7): ``normalize_to_chinese`` previously
replaced ASCII punctuation in fenced code blocks too, which broke
the syntax of any untranslated JSON / YAML / CSV / code inside
``\`\`\`...\`\`\`\` fences. The fix splits the text on fence spans
and only translates the non-fence parts. Mirrors the fence coverage
in ``src/ol_md/shield.py:CODE_PATTERN`` so anything the shield
protects from LLM translation is also protected from the
post-processing punctuation pass.
"""
import re

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


# ── Fenced code block detection ─────────────────────────────────────────────
# Same shape as src/ol_md/shield.py:CODE_PATTERN — only triple-backtick
# fences with an optional language tag, content separated by newlines.
# Tilde fences (~~~) are not handled because the shield doesn't handle
# them either; matching shield coverage is the right scope boundary.
_FENCE_RE = re.compile(r"```[\w]*\n[\s\S]*?```")


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
    """Replace ASCII punctuation with Chinese equivalents for Chinese-mode output,
    **except inside fenced code blocks** (where ASCII punctuation is structural).

    Issue #5: prior versions called ``text.translate(_EN_TO_ZH)`` on the full
    body, which replaced ``:,.()`` etc. inside ``\`\`\`json\`\`\` code blocks
    with their full-width equivalents and produced invalid JSON / YAML / CSV.
    The fix splits on ``_FENCE_RE`` and only translates the non-fence spans.

    Maps outside code blocks:
        , → ，    . → 。    : → ：    ; → ；    ! → ！
        ? → ？    ( → （    ) → ）

    Note: ASCII straight quotes (\" '\") are left as-is since they are
    context-dependent and cannot be directionally resolved via simple
    character mapping.

    Args:
        text: Input string possibly containing ASCII punctuation.

    Returns:
        String with ASCII punctuation replaced by Chinese equivalents,
        with fenced code blocks preserved verbatim.
    """
    # Fast path: no fences → no split overhead, single translate.
    if _FENCE_RE.search(text) is None:
        return text.translate(_EN_TO_ZH)

    # Slow path: split text on fence spans, translate only the gaps.
    parts = _FENCE_RE.split(text)  # [pre, mid1, mid2, ...] (len = fences+1)
    fences = _FENCE_RE.findall(text)  # [fence1, fence2, ...]
    out = []
    for i, gap in enumerate(parts):
        out.append(gap.translate(_EN_TO_ZH))
        if i < len(fences):
            out.append(fences[i])  # code block: untouched
    return "".join(out)
