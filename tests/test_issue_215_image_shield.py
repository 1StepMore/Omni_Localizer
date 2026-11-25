"""Issue #215 — markdown image syntax must never reach the LLM.

``extract_and_shield_md_units`` sent the whole ``![alt](url)`` inline content
to the model as a translatable unit with an empty ``shield_map``, so a real
en→zh run rewrote ``![Image 1](./sample_images/sample_image_1.png)`` into
``！[图片 1]（。/sampleimages/sampleimage_1。png）`` — the URL no longer
pointed at anything. Two layers were broken:

1. the extractor did not apply ``ol_md.shield`` to unit content, and
2. ``ol_post.punctuation.normalize`` re-mangled the byte-identical image the
   unshield had just restored (Issue #5 precedent: the post-pass must
   protect the same content the shield protects).

These tests pin both layers: images are shielded out of the units, restored
byte-identical at their original position/order by rebuild, and survive the
punctuation post-pass.
"""
from __future__ import annotations

import os
import re

import markdown_it

from ol_buses.md_bus import parse_md_to_tokens
from ol_md.extractor import extract_and_shield_md_units
from ol_md.shield import unshield_markdown
from ol_md.token_stream import TokenPositionTracker
from ol_post.punctuation import normalize

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

MD = markdown_it.MarkdownIt()

IMAGE_TOKEN_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _image_tokens(text: str) -> list[str]:
    """Image tokens as markdown-it sees them, in document order."""
    found: list[str] = []
    for token in MD.parse(text):
        for child in token.children or []:
            if child.type == "image":
                found.append(child.content)
    return found


def _identity_round_trip(md_text: str) -> str:
    """extract → identity 'translate' → unshield → rebuild, as the CLI does."""
    units = extract_and_shield_md_units(md_text)
    for unit in units:
        translated = unit.source_text  # identity translation
        unit.target_text = unshield_markdown(translated, unit.shield_map)
    tokens = parse_md_to_tokens(md_text)
    return TokenPositionTracker.rebuild(tokens, units)


class TestImagesShieldedOutOfUnits:
    def test_units_contain_no_image_syntax(self):
        md = (
            "Intro paragraph here.\n"
            "\n"
            "![Image 1](./sample_images/sample_image_1.png)\n"
            "\n"
            "![Image 2](./sample_images/sample_image_2.png)\n"
            "\n"
            "Closing text.\n"
        )
        units = extract_and_shield_md_units(md)
        assert len(units) == 4
        for unit in units:
            assert "![" not in unit.source_text, unit.source_text
        # The image lines themselves became IMG markers in unit order.
        img_markers = [
            u.source_text for u in units if u.source_text.startswith("[OL:IMG:")
        ]
        assert len(img_markers) == 2

    def test_units_carry_shield_map_for_unshield(self):
        units = extract_and_shield_md_units("![Image 1](./sample_images/sample_image_1.png)\n")
        assert units[0].shield_map
        assert "[OL:IMG:" in units[0].source_text
        assert list(units[0].shield_map.values()) == [
            "![Image 1](./sample_images/sample_image_1.png)"
        ]

    def test_reference_style_image_shielded(self):
        units = extract_and_shield_md_units("Logo: ![alt][logo-id]\n")
        assert "![" not in units[0].source_text
        assert "[OL:IMG:" in units[0].source_text
        restored = unshield_markdown(units[0].source_text, units[0].shield_map)
        assert restored == "Logo: ![alt][logo-id]"


class TestRebuildRestoresImagesByteIdentical:
    def test_two_image_lines_round_trip_in_order(self):
        md = (
            "Intro paragraph here.\n"
            "\n"
            "![Image 1](./sample_images/sample_image_1.png)\n"
            "\n"
            "![Image 2](./sample_images/sample_image_2.png)\n"
            "\n"
            "Closing text.\n"
        )
        rebuilt = _identity_round_trip(md)
        # Same number of image tokens, same order, byte-identical.
        assert IMAGE_TOKEN_RE.findall(rebuilt) == IMAGE_TOKEN_RE.findall(md)
        assert _image_tokens(md) == _image_tokens(rebuilt)
        assert (
            "![Image 1](./sample_images/sample_image_1.png)" in rebuilt
        )
        assert (
            "![Image 2](./sample_images/sample_image_2.png)" in rebuilt
        )
        # Original position: image 1 before image 2, both after intro.
        assert rebuilt.index("Intro paragraph") < rebuilt.index("![Image 1]")
        assert rebuilt.index("![Image 1]") < rebuilt.index("![Image 2]")
        assert rebuilt.index("![Image 2]") < rebuilt.index("Closing text")

    def test_issue_215_regression_line_round_trips(self):
        line = "![Image 1](./sample_images/sample_image_1.png)"
        rebuilt = _identity_round_trip(line + "\n")
        assert line in rebuilt
        assert IMAGE_TOKEN_RE.findall(rebuilt) == [line]

    def test_mixed_prose_and_image_unit_restored_in_place(self):
        md = "See this ![diagram](./img/a_b.png) for details.\n"
        rebuilt = _identity_round_trip(md)
        assert "See this ![diagram](./img/a_b.png) for details." in rebuilt

    def test_link_and_table_not_over_shielded(self):
        md = (
            "Read the [docs](http://example.com/guide).\n"
            "\n"
            "| Col A | Col B |\n"
            "|-------|-------|\n"
            "| a1 | b2 |\n"
        )
        rebuilt = _identity_round_trip(md)
        # Link survives byte-identical.
        assert "[docs](http://example.com/guide)" in rebuilt
        # Table rows still reach the units as raw text (unchanged behaviour)
        # and are re-emitted intact.
        units = extract_and_shield_md_units(md)
        table_units = [u for u in units if "|" in u.source_text]
        assert table_units, "table rows must remain translatable units"
        assert "| Col A | Col B |" in rebuilt
        assert "| a1 | b2 |" in rebuilt


class TestPunctuationPassKeepsImages:
    def test_normalize_en_zh_keeps_image_line_byte_identical(self):
        line = "![Image 1](./sample_images/sample_image_1.png)"
        assert normalize(line, "en", "zh") == line

    def test_normalize_en_zh_keeps_reference_image(self):
        line = "![alt][logo-id]"
        assert normalize(line, "en", "zh") == line

    def test_normalize_still_converts_prose(self):
        out = normalize("End. See [docs](http://example.com/a.b).\n", "en", "zh")
        assert out == "End。 See [docs](http://example.com/a.b)。\n"
