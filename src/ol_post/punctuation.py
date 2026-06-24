"""Punctuation normalizer for OL output post-processing.

Provides per-language-pair punctuation normalization via
``normalize(text, source_lang, target_lang)`` backed by a dispatch
table ``_PUNCT_TABLES`` keyed by ``"source_target"`` string.

Current supported pairs:
  - zh_en: Chinese → English (full-width → ASCII)
  - en_zh: English → Chinese (ASCII → full-width)
  - en_ja: English → Japanese (ASCII → full-width)

Other language pairs (fr/de/ru/ko/…) use ASCII punctuation that is
already correct — they fall through to identity.

Uses str.maketrans() for O(1) character translation with zero dependencies.

Issue #5 (OL v0.4.6 → v0.4.7): ``normalize_to_chinese`` previously
replaced ASCII punctuation in fenced code blocks too, which broke
the syntax of any untranslated JSON / YAML / CSV / code inside
``\`\`\`...\`\`\`\` fences. The fix splits the text on fence spans
and only translates the non-fence parts. Mirrors the fence coverage
in ``src/ol_md/shield.py:CODE_PATTERN`` so anything the shield
protects from LLM translation is also protected from the
post-processing punctuation pass. Fence-aware logic now lives in
``normalize()`` so all dispatch-table entries benefit from it.
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


# ── Per-language-pair normalization tables ───────────────────────────────────
# Keyed by "source_target" string.  Unknown pairs fall through to identity.
_PUNCT_TABLES = {
    "zh_en": _ZH_TO_EN,    # Chinese → English (full-width → ASCII)
    "en_zh": _EN_TO_ZH,    # English → Chinese (ASCII → full-width)
    "en_ja": str.maketrans({
        ",": "\u3001",     # , → 、 (ideographic comma)
        ".": "\u3002",     # . → 。 (ideographic full stop)
        "?": "\uff1f",     # ? → ？
        "!": "\uff01",     # ! → ！
        ":": "\uff1a",     # : → ：
        ";": "\uff1b",     # ; → ；
        "(": "\uff08",     # ( → （
        ")": "\uff09",     # ) → ）
    }),
}


def normalize(text: str, source_lang: str, target_lang: str) -> str:
    """Normalize punctuation based on source→target language pair.

    Uses the dispatch table ``_PUNCT_TABLES``.  Fenced code blocks
    (triple-backtick spans) are preserved verbatim — only the non-fence
    gaps are translated — so that JSON / YAML / CSV / code syntax is
    never corrupted (Issue #5).

    Args:
        text: Input string possibly containing punctuation to convert.
        source_lang: Source language code (e.g. ``"en"``, ``"zh"``).
        target_lang: Target language code (e.g. ``"ja"``, ``"en"``).

    Returns:
        String with punctuation normalized for the target language,
        or the original text if no mapping exists for the pair.
    """
    pair = f"{source_lang}_{target_lang}"
    table = _PUNCT_TABLES.get(pair)
    if not table:
        return text

    # Fast path: no fences → no split overhead, single translate.
    if _FENCE_RE.search(text) is None:
        return text.translate(table)

    # Slow path: split text on fence spans, translate only the gaps.
    parts = _FENCE_RE.split(text)  # [pre, mid1, mid2, ...] (len = fences+1)
    fences = _FENCE_RE.findall(text)  # [fence1, fence2, ...]
    out = []
    for i, gap in enumerate(parts):
        out.append(gap.translate(table))
        if i < len(fences):
            out.append(fences[i])  # code block: untouched
    return "".join(out)


def normalize_to_english(text: str) -> str:
    """Backward-compat wrapper: normalize Chinese → English punctuation.
    Equivalent to ``normalize(text, "zh", "en")``."""
    return normalize(text, "zh", "en")


def normalize_to_chinese(text: str) -> str:
    """Backward-compat wrapper: normalize English → Chinese punctuation.
    Equivalent to ``normalize(text, "en", "zh")``."""
    return normalize(text, "en", "zh")
