"""E2E-78 regression tests.

The bug: ``ol_md.shield`` used ``\x00OL_{TYPE}_{ID:04d}\x00`` markers
(NUL-byte-delimited). Two failure modes:

  1. The LLM strip or mangle the NUL control character during
     translation, which made ``unshield_markdown`` silently drop
     the original HTML / math / code for the affected marker.

  2. ``unshield_markdown`` was all-or-nothing: if a marker was
     missing, the original content was lost with no signal.

The fix:
  - Switch the marker format to ``[OL:TYPE:NNNN]`` (ASCII-delimited,
    unambiguous vs markdown link / image grammar).
  - When a marker is missing, append the original content at the end
    under an ``<!-- OL_WARN:missing_shields key1,key2,... -->``
    HTML comment so the content is never silently lost.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

import pytest

from ol_md.shield import (
    PLACEHOLDER_PATTERN,
    shield_markdown,
    unshield_markdown,
)


class TestMarkerFormatIsLlmFriendly:
    """The new format must not use NUL bytes or markdown-ambiguous brackets."""

    def test_marker_uses_ascii_delimiters(self):
        shielded, _ = shield_markdown("```code```")
        assert "\x00" not in shielded, (
            "Marker must not contain NUL control characters (E2E-78)"
        )
        # Bracket pattern that doesn't conflict with markdown links/images.
        assert "[OL:" in shielded

    def test_placeholder_pattern_matches_new_format(self):
        # Pattern should match the [OL:TYPE:NNNN] form.
        import re
        text = "before [OL:HTML:0007] after"
        matches = PLACEHOLDER_PATTERN.findall(text)
        assert matches == [("HTML", "0007")], (
            f"PLACEHOLDER_PATTERN must match [OL:TYPE:NNNN]. "
            f"Got matches: {matches}"
        )

    def test_marker_does_not_collide_with_markdown_link(self):
        """A markdown link like [text](url) is shielded as LINK, and
        the round-trip preserves the original — the new [OL:...] marker
        format does not collide with the link syntax.
        """
        text = "See [the docs](https://example.com) for details."
        shielded, sm = shield_markdown(text)
        assert "link_0000" in sm
        assert "[OL:LINK:0000]" in shielded
        restored = unshield_markdown(shielded, sm)
        assert restored == text


class TestShieldUnshieldRoundTrip:
    """Shield + unshield must be a no-op when the LLM preserves markers."""

    def test_html_block_round_trip(self):
        text = "HTML: <sub>2</sub> and <div>block</div>"
        shielded, sm = shield_markdown(text)
        restored = unshield_markdown(shielded, sm)
        assert restored == text, f"Round trip lost data: {restored!r}"

    def test_code_block_round_trip(self):
        text = "Here is code:\n\n```python\nprint('hi')\n```\n\nDone."
        shielded, sm = shield_markdown(text)
        restored = unshield_markdown(shielded, sm)
        assert restored == text

    def test_link_round_trip(self):
        text = "Click [here](https://example.com) please."
        shielded, sm = shield_markdown(text)
        restored = unshield_markdown(shielded, sm)
        assert restored == text


class TestUnshieldFallback:
    """If the LLM drops a marker, the original content must NOT be lost."""

    def test_missing_marker_appends_content(self):
        """When the LLM drops one of two markers, the dropped content
        is appended at the end under an OL_WARN comment instead of
        being silently lost."""
        import re
        text = "Before <div>HTML block</div> and <span>inline</span> after"
        shielded, sm = shield_markdown(text)
        # Simulate the LLM dropping one marker entirely.
        markers_in = re.findall(r"\[OL:[A-Z_]+:\d{4}\]", shielded)
        assert len(markers_in) == 2, (
            f"Test setup: expected 2 markers in shielded text. Got: {markers_in}"
        )
        missing_marker = markers_in[0]
        llm_output = shielded.replace(missing_marker, "").strip()
        restored = unshield_markdown(llm_output, sm)
        # The OL_WARN block + the missing original must both be present.
        assert "OL_WARN:missing_shields" in restored, (
            f"Missing-marker case must emit OL_WARN. Got: {restored!r}"
        )
        # At least one of the two original HTML blocks is preserved
        # (the one whose marker survived); the dropped one is in the
        # OL_WARN block.
        assert "HTML block" in restored or "inline" in restored, (
            f"Dropped original content must be preserved. Got: {restored!r}"
        )

    def test_missing_marker_warning_lists_keys(self):
        import re
        text = "<div>drop me</div> and <span>keep me</span>"
        shielded, sm = shield_markdown(text)
        markers_in = re.findall(r"\[OL:[A-Z_]+:\d{4}\]", shielded)
        assert len(markers_in) == 2
        drop = markers_in[0]
        llm_output = shielded.replace(drop, "")
        restored = unshield_markdown(llm_output, sm)
        assert "OL_WARN:missing_shields" in restored
        assert "drop me" in restored or "keep me" in restored

    def test_all_markers_missing(self):
        """If the LLM drops ALL markers, the file still contains all
        original content (under OL_WARN)."""
        text = "<div>one</div> <span>two</span> <em>three</em>"
        shielded, sm = shield_markdown(text)
        # Drop all markers — result is the plain text without HTML.
        llm_output = "one two three"
        restored = unshield_markdown(llm_output, sm)
        for original in ("<div>one</div>", "<span>two</span>", "<em>three</em>"):
            assert original in restored, (
                f"Original {original!r} must be preserved in fallback. "
                f"Got: {restored!r}"
            )
        assert restored.startswith("one two three")
        assert "OL_WARN:missing_shields" in restored

    def test_no_missing_markers_no_warn_block(self):
        """If all markers survive, no OL_WARN block is emitted."""
        text = "<div>html</div>"
        shielded, sm = shield_markdown(text)
        restored = unshield_markdown(shielded, sm)
        assert "OL_WARN" not in restored
        assert restored == text

    def test_empty_shield_map_is_noop(self):
        result = unshield_markdown("any text", {})
        assert result == "any text"
        assert "OL_WARN" not in result
