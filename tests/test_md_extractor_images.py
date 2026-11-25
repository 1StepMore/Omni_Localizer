"""OL#215 — markdown images must not be translated.

A real en→zh run turned ``![Image 1](./sample_images/sample_image_1.png)``
into ``！[图片 1]（。/sampleimages/sampleimage_1。png）``: the punctuation was
localised and the URL path rewritten, so the image resolved to nothing.
`extract_and_shield_md_units` is documented as preserving markdown structure
but the whole ``![alt](url)`` line was handed to the LLM as a translatable
unit. Images are now shielded into ``[OL:IMG:NNNN]`` markers using the
existing shield/unshield mechanism, and restored byte-identical.
"""
from __future__ import annotations

import re

from ol_md.extractor import extract_and_shield_md_units
from ol_md.shield import unshield_markdown
from ol_md.token_stream import TokenPositionTracker
from ol_buses.md_bus import parse_md_to_tokens

IMAGE_SYNTAX_RE = re.compile(r"!\[[^\]]*\]")

ISSUE_LINE = "![Image 1](./sample_images/sample_image_1.png)"

TWO_IMAGES_AND_PROSE = (
    f"{ISSUE_LINE}\n"
    "\n"
    "Some prose between the images.\n"
    "\n"
    "![Image 2](./sample_images/sample_image_2.png)\n"
)


def _identity_translate(units):
    """Stand-in for the LLM: echo source_text as target_text."""
    for unit in units:
        unit.target_text = unit.source_text
    return units


def _rebuild(md_text: str, units) -> str:
    tokens = parse_md_to_tokens(md_text)
    return TokenPositionTracker.rebuild(tokens, units)


def _round_trip(md_text: str) -> str:
    units = _identity_translate(extract_and_shield_md_units(md_text))
    for unit in units:
        unit.target_text = unshield_markdown(unit.target_text, unit.shield_map)
    return _rebuild(md_text, units)


def _images_in(text: str) -> list[str]:
    return re.findall(r"!\[[^\]]*\]\([^)]+\)|!\[[^\]]*\]\[[^\]]*\]", text)


class TestImagesAreShielded:
    def test_no_image_syntax_reaches_the_llm(self):
        units = extract_and_shield_md_units(TWO_IMAGES_AND_PROSE)

        assert units, "expected translatable units"
        for unit in units:
            assert IMAGE_SYNTAX_RE.search(unit.source_text) is None, unit.source_text

    def test_prose_is_still_extracted(self):
        units = extract_and_shield_md_units(TWO_IMAGES_AND_PROSE)

        assert any("Some prose" in unit.source_text for unit in units)

    def test_each_image_gets_its_own_shield_entry(self):
        units = extract_and_shield_md_units(TWO_IMAGES_AND_PROSE)
        # Keys restart at image_0000 per unit (each unit is unshielded with its
        # own map), so collect the values rather than keying a dict.
        shielded_values = [v for unit in units for v in unit.shield_map.values()]

        assert sorted(shielded_values) == [
            "![Image 1](./sample_images/sample_image_1.png)",
            "![Image 2](./sample_images/sample_image_2.png)",
        ]

    def test_reference_style_image_is_shielded(self):
        units = extract_and_shield_md_units("![logo][logo-ref]\n")

        assert all(IMAGE_SYNTAX_RE.search(u.source_text) is None for u in units)
        assert any(
            v == "![logo][logo-ref]" for u in units for v in u.shield_map.values()
        )


class TestImagesSurviveRebuild:
    def test_two_images_round_trip_byte_identical_in_order(self):
        rebuilt = _round_trip(TWO_IMAGES_AND_PROSE)

        assert _images_in(rebuilt) == [
            "![Image 1](./sample_images/sample_image_1.png)",
            "![Image 2](./sample_images/sample_image_2.png)",
        ]

    def test_reported_line_round_trips_unchanged(self):
        rebuilt = _round_trip(f"{ISSUE_LINE}\n")

        assert ISSUE_LINE in rebuilt
        assert "！[" not in rebuilt
        assert "（" not in rebuilt
        assert "。" not in rebuilt

    def test_image_in_the_middle_of_a_sentence_keeps_its_position(self):
        source = "Before ![Image 1](./sample_images/sample_image_1.png) after.\n"

        rebuilt = _round_trip(source)

        assert "Before ![Image 1](./sample_images/sample_image_1.png) after." in rebuilt


class TestNoOverShielding:
    def test_plain_link_is_not_shielded(self):
        units = extract_and_shield_md_units("See [the docs](https://example.com/a_b).\n")

        assert [u.shield_map for u in units] == [{}]
        assert "See [the docs](https://example.com/a_b)." in units[0].source_text

    def test_link_round_trips_unchanged(self):
        source = "See [the docs](https://example.com/a_b).\n"

        assert "See [the docs](https://example.com/a_b)." in _round_trip(source)

    def test_link_with_exclamation_is_not_treated_as_an_image(self):
        units = extract_and_shield_md_units("Wow! [the docs](https://example.com).\n")

        assert [u.shield_map for u in units] == [{}]

    def test_table_row_text_is_unchanged(self):
        source = "| a | b |\n| --- | --- |\n| c | d |\n"

        units = extract_and_shield_md_units(source)

        assert [u.shield_map for u in units] == [{} for _ in units]
        assert all("|" in unit.source_text for unit in units)

    def test_paragraph_without_images_keeps_an_empty_shield_map(self):
        units = extract_and_shield_md_units("Plain prose, nothing to shield.\n")

        assert [u.shield_map for u in units] == [{}]
