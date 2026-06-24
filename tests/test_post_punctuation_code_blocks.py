"""Regression tests for ol_post.punctuation.normalize_to_chinese fenced-code-block
skipping (Issue #5, OL v0.4.7).

The bug (in v0.4.6 and earlier): ``normalize_to_chinese`` ran
``text.translate(_EN_TO_ZH)`` on the entire post-repair body, which replaced
ASCII ``:,.();?!()`` inside ```json``` / ```yaml``` / code fences with
full-width Chinese punctuation. The LLM never saw the fence content
(the shield at ``src/ol_md/shield.py`` replaces it with markers), so the
original ASCII punctuation was correctly restored by ``unshield`` — and then
immediately corrupted again by the post-pass. Output JSON / YAML / CSV
inside fences became syntactically invalid even though the LLM did the
right thing upstream.

The fix splits on a triple-backtick fence regex and only translates the
non-fence spans. Mirrors the fence coverage in ``src/ol_md/shield.py`` so
the post-pass protects the same content the LLM pass protected.

These tests pin the contract so a future refactor can't silently regress
this — and they would have caught the original v0.4.6 bug.
"""
from __future__ import annotations

import pytest

from ol_post.punctuation import (
    _FENCE_RE,
    normalize_to_chinese,
    normalize_to_english,
)


# ── Issue #5: primary bug ──────────────────────────────────────────────────


class TestNormalizeToChineseFencePreservation:
    """ASCII punctuation inside fenced code blocks must NOT be translated."""

    def test_json_fence_punctuation_preserved(self):
        """The original Issue #5 repro: ```json block with JSON syntax.

        All of ``:,.()`` inside the fence must stay ASCII. The header line
        ("Here is JSON:") outside the fence SHOULD be translated.
        """
        text = (
            "Here is JSON:\n"
            "\n"
            "```json\n"
            '{"key": "value", "items": [1, 2, 3]}\n'
            "```\n"
        )
        out = normalize_to_chinese(text)

        # Fence content: ASCII punctuation intact.
        assert '{"key": "value", "items": [1, 2, 3]}' in out, (
            "JSON object body was corrupted by full-width replacement"
        )
        # Fence opener/closer with language tag: intact.
        assert "```json" in out
        assert "```\n" in out

        # Outside the fence: normal punctuation translation still happens.
        assert "Here is JSON：" in out, (
            "Prose outside the fence should have been translated"
        )
        # The full-width colon must NOT have leaked into the JSON.
        assert "：" not in out.split("```json", 1)[1].split("```", 1)[0], (
            "Full-width colon leaked into the JSON fence"
        )

    def test_yaml_fence_punctuation_preserved(self):
        """YAML uses ':' as key/value separator — same JSON problem."""
        text = (
            "Settings:\n"
            "\n"
            "```yaml\n"
            "host: localhost\n"
            "port: 8080\n"
            "paths:\n"
            "  - /api/v1\n"
            "  - /api/v2\n"
            "```\n"
        )
        out = normalize_to_chinese(text)

        assert "host: localhost" in out
        assert "port: 8080" in out
        assert "  - /api/v1" in out
        # Outside the fence, "Settings" should be translated.
        assert "Settings：" in out

    def test_csv_fence_punctuation_preserved(self):
        """CSV uses ',' as field separator — same JSON problem."""
        text = (
            "Data, line:\n"
            "\n"
            "```csv\n"
            "name,age,city\n"
            "Alice,30,Beijing\n"
            "Bob,25,Shanghai\n"
            "```\n"
        )
        out = normalize_to_chinese(text)

        assert "name,age,city" in out
        assert "Alice,30,Beijing" in out
        assert "Bob,25,Shanghai" in out

    def test_inline_code_with_parens_preserved(self):
        """CommonMark inline code (`...`) is NOT protected (matches shield scope).

        The shield only handles fenced blocks, so the post-pass also only
        skips fenced blocks. Inline code's parens and commas get translated
        like regular prose. This test pins that scope decision — if a
        future change widens shield coverage to inline code, this test
        should be updated to reflect the new contract.
        """
        text = "Call `func(arg1, arg2)` please.\n"
        out = normalize_to_chinese(text)
        # Inline-code parens AND commas ARE translated (not in scope of the fix).
        assert "（arg1， arg2）" in out
        # No full-width parens outside the backticks in the input → none in output.
        assert "`func（arg1， arg2）`" in out
        # The trailing period after the inline code is also translated.
        assert "please。" in out

    def test_no_fence_unchanged_behavior(self):
        """Without fences, normalize_to_chinese behaves exactly as before."""
        text = "Hello, world. This is a test; ok?\n"
        assert normalize_to_chinese(text) == "Hello， world。 This is a test； ok？\n"

    def test_multiple_fences(self):
        """Multiple fences in the same doc are all preserved."""
        text = (
            "First block:\n"
            "\n"
            "```json\n"
            '{"a": 1}\n'
            "```\n"
            "\n"
            "Second block:\n"
            "\n"
            "```python\n"
            "x = func(1, 2)\n"
            "```\n"
        )
        out = normalize_to_chinese(text)
        assert '{"a": 1}' in out
        assert "x = func(1, 2)" in out
        assert "First block：" in out
        assert "Second block：" in out

    def test_fence_at_start_of_text(self):
        """Fence at position 0 (no leading prose)."""
        text = (
            "```json\n"
            '{"k": "v"}\n'
            "```\n"
        )
        out = normalize_to_chinese(text)
        assert '{"k": "v"}' in out

    def test_fence_at_end_of_text(self):
        """Fence at the very end (no trailing prose)."""
        text = (
            "Prose first.\n"
            "\n"
            "```json\n"
            '{"k": "v"}\n'
            "```"
        )
        out = normalize_to_chinese(text)
        assert "Prose first。" in out
        assert '{"k": "v"}' in out

    def test_empty_fence(self):
        """Empty fence: ```\\n\\n``` — should not crash and not translate empty body."""
        text = "Prose.\n\n```\n\n```\n"
        out = normalize_to_chinese(text)
        assert "Prose。" in out
        # Fence itself untouched.
        assert "```" in out

    def test_fence_with_no_language_tag(self):
        """Plain fence with no language tag (`` ``` `` not `` ```json ``)."""
        text = "Prose.\n\n```\n{\"k\":\"v\"}\n```\n"
        out = normalize_to_chinese(text)
        assert "{\"k\":\"v\"}" in out


# ── Symmetric direction (must NOT regress) ─────────────────────────────────


class TestNormalizeToEnglishUnchanged:
    """normalize_to_english is the reverse — must not be affected by the fix."""

    def test_zh_punct_in_fence_translated_back(self):
        """If a fence somehow contains 中文标点 (shouldn't, but defensively), it should be translated back."""
        text = (
            "Some prose：\n"
            "\n"
            "```\n"
            "code： with： colons\n"
            "```\n"
        )
        out = normalize_to_english(text)
        # Prose translated.
        assert "Some prose:" in out
        # Code block also translated (this direction is the safe one).
        assert "code: with: colons" in out

    def test_zh_punct_no_fence_unchanged(self):
        text = "中文：测试，结束。"
        assert normalize_to_english(text) == "中文:测试,结束."


# ── The regex itself (anchored to shield's CODE_PATTERN) ───────────────────


class TestFenceRePattern:
    """Pin the fence regex shape so it can't drift away from the shield."""

    def test_matches_backtick_fence(self):
        assert _FENCE_RE.search("```\nfoo\n```") is not None
        assert _FENCE_RE.search("```json\nfoo\n```") is not None
        assert _FENCE_RE.search("```python\nx = 1\n```") is not None

    def test_does_not_match_tilde_fence(self):
        """Tilde fences are out of scope (shield doesn't handle them)."""
        assert _FENCE_RE.search("~~~\nfoo\n~~~") is None

    def test_does_not_match_inline_code(self):
        """Single-backtick inline code is out of scope (matches shield)."""
        assert _FENCE_RE.search("`code`") is None
        assert _FENCE_RE.search("`code with spaces`") is None

    def test_does_not_match_unclosed_fence(self):
        """Opening fence with no closing: regex is non-greedy but needs a close."""
        # No closing ``` — should not match (regex would scan to EOF and fail).
        assert _FENCE_RE.search("```\nfoo") is None
