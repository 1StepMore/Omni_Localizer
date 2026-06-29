r"""E2E-77 regression tests.

The bug: ``ol_md.shield.MATH_PATTERN`` was ``r'\$\$([^$]+)\$\$|\$([^$]+)\$'``.
The inner ``[^$]+`` is greedy and Python's ``re`` matches across
intermediate ``$`` characters, so common English text containing two
or more dollar signs gets falsely detected as math:

    "Price: $5.99 and $10 each"  →  whole "$5.99 and $" eaten as math
    "Earnings: $100 today and $50$ yesterday"  →  "$100 today and $" eaten
    "I have $a variable named $b"  →  "$a variable named $b" all eaten
    "Cost is $5$ (a typo)"  →  entire "$5$" eaten

The fix: inline math $..$ now requires a LaTeX marker inside
(backslash command, ^, or _) so it only matches real math. Display
math $$..$$ is unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

import pytest

from ol_md.shield import shield_markdown, unshield_markdown


# Lazy import — see test_e2e_74_translate_context.py for the conftest
# heavy-import blocker that requires this dance for ol_pool.
def _load_pool():
    import importlib
    import sys
    for name in ("litellm", "litellm.types", "litellm.types.router"):
        sys.modules.pop(name, None)
    src = str(Path(__file__).resolve().parents[1] / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    return importlib.import_module("ol_pool.router")


@pytest.fixture
def router_module():
    return _load_pool()


@pytest.fixture
def pool(router_module):
    router_module._pool_cache.clear()
    return router_module.ModelPool(
        str(Path(__file__).resolve().parents[1] / "config" / "default.yaml")
    )


class TestMathShieldFalsePositives:
    """Currency and normal $-text must NOT be eaten as math."""

    def test_two_currency_amounts_with_text_between(self):
        """The original repro: 'Price: $5.99 and $10 each'."""
        text = "Price: $5.99 and $10 each"
        shielded, sm = shield_markdown(text)
        assert sm == {}, (
            f"Currency text must not be detected as math. Got shield_map: {sm}. "
            f"Shielded: {shielded!r}"
        )
        assert shielded == text, "Text without math must be unchanged"

    def test_earnings_with_currency_typo(self):
        text = "Earnings: $100 today and $50$ yesterday"
        shielded, sm = shield_markdown(text)
        assert sm == {}, (
            f"Currency with stray $ must not be detected as math. Got: {sm}"
        )
        assert shielded == text

    def test_variable_names_with_dollar(self):
        text = "I have $a variable named $b"
        shielded, sm = shield_markdown(text)
        assert sm == {}, f"Variable names must not be math. Got: {sm}"
        assert shielded == text

    def test_lone_dollar_pairs(self):
        text = "Cost is $5$ (a typo)"
        shielded, sm = shield_markdown(text)
        assert sm == {}, f"Stray $5$ must not be math. Got: {sm}"
        assert shielded == text

    def test_dollar_at_end_of_word(self):
        text = "I have 5$ and 10$"
        shielded, sm = shield_markdown(text)
        assert sm == {}, f"Suffix $ must not be math. Got: {sm}"
        assert shielded == text

    def test_text_without_dollar_unchanged(self):
        text = "Normal text without any dollar signs"
        shielded, sm = shield_markdown(text)
        assert sm == {}
        assert shielded == text


class TestMathShieldStillMatchesRealMath:
    r"""Genuine LaTeX must still be detected (display $$ and inline $..\cmd..$)."""

    def test_display_math_still_works(self):
        text = "$$x^2 + y^2 = z^2$$"
        shielded, sm = shield_markdown(text)
        assert "math_0000" in sm, (
            f"Display math must still be shielded. Got: {sm}"
        )
        # Round-trip via unshield.
        restored = unshield_markdown(shielded, sm)
        assert restored == text, f"Display math round-trip lost data: {restored!r}"

    def test_inline_math_with_backslash_command(self):
        text = r"Inline $\alpha + \beta$ here"
        shielded, sm = shield_markdown(text)
        assert "math_0000" in sm, (
            f"Inline $..\\cmd..$ must be shielded. Got: {sm}"
        )
        restored = unshield_markdown(shielded, sm)
        assert restored == text

    def test_inline_math_with_superscript(self):
        text = "$x^2$"
        shielded, sm = shield_markdown(text)
        assert "math_0000" in sm, (
            f"$x^2$ has ^ marker and must be shielded. Got: {sm}"
        )
        restored = unshield_markdown(shielded, sm)
        assert restored == text

    def test_inline_math_with_subscript(self):
        text = "$a_1 + a_2$"
        shielded, sm = shield_markdown(text)
        assert "math_0000" in sm
        restored = unshield_markdown(shielded, sm)
        assert restored == text
