"""OMNI_Localizer#152 — lists and blockquotes must survive `rebuild`.

`rebuild` had no branches for the list/blockquote open-close tokens, whose
structural markers live in `markup`/`attrs` rather than `content`. Every item
therefore fell through to the generic `content` append and lost its marker,
numbering, indentation, and `>` prefix.
"""
from __future__ import annotations

import os
from pathlib import Path

import markdown_it
from typer.testing import CliRunner

from cli.frontmatter import strip_frontmatter
from ol_cli import app
from ol_core.dataclass import TranslationUnit
from ol_md.token_stream import TokenPositionTracker

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

runner = CliRunner()
MD = markdown_it.MarkdownIt()
CONFIG = Path(__file__).resolve().parents[1] / "config" / "test_universal.yaml"


def _units(tokens) -> list[TranslationUnit]:
    return [
        TranslationUnit(unit_id=f"u{i}", source_text=t.content, target_text=t.content)
        for i, t in enumerate(tokens)
        if t.type == "inline" and t.content
    ]


def _rebuild(text: str) -> str:
    tokens = MD.parse(text)
    return TokenPositionTracker.rebuild(tokens, _units(tokens))


class TestBulletLists:
    def test_tight_list_keeps_bullets_on_consecutive_lines(self):
        assert _rebuild("- one\n- two\n") == "- one\n- two\n\n"

    def test_loose_list_keeps_its_blank_line(self):
        assert _rebuild("- one\n\n- two\n") == "- one\n\n- two\n\n"

    def test_star_marker_is_normalised_to_dash(self):
        assert _rebuild("* one\n* two\n") == "- one\n- two\n\n"

    def test_two_nesting_levels_are_indented(self):
        assert (
            _rebuild("- parent\n  - child\n  - child two\n")
            == "- parent\n  - child\n  - child two\n\n"
        )

    def test_sibling_after_a_nested_list_is_not_indented(self):
        assert (
            _rebuild("- parent\n  - child\n- sibling\n")
            == "- parent\n  - child\n- sibling\n\n"
        )


class TestOrderedLists:
    def test_items_are_numbered(self):
        assert _rebuild("1. one\n2. two\n") == "1. one\n2. two\n\n"

    def test_start_attribute_is_honoured(self):
        assert _rebuild("3. three\n4. four\n") == "3. three\n4. four\n\n"


class TestBlockquotes:
    def test_single_line(self):
        assert _rebuild("> quoted\n") == "> quoted\n\n"

    def test_each_line_of_one_inline_gets_the_prefix(self):
        assert _rebuild("> line one\n> line two\n") == "> line one\n> line two\n\n"

    def test_nested_quote_gets_a_doubled_prefix(self):
        assert _rebuild("> outer\n> > inner\n") == "> outer\n\n> > inner\n\n"

    def test_list_inside_a_quote_keeps_both_markers(self):
        assert (
            _rebuild("> - item one\n> - item two\n")
            == "> - item one\n> - item two\n\n"
        )

    def test_translated_newlines_are_prefixed_too(self):
        tokens = MD.parse("> line one\n> line two\n")
        units = [
            TranslationUnit(
                unit_id="u0",
                source_text="line one\nline two",
                target_text="译一\n译二",
            )
        ]
        assert TokenPositionTracker.rebuild(tokens, units) == "> 译一\n> 译二\n\n"


class TestStructureIsPreservedTogether:
    def test_heading_list_and_quote_in_one_document(self):
        rebuilt = _rebuild("# Title\n\n- one\n- two\n\n> quoted\n")
        assert rebuilt.startswith("# Title")
        assert "- one" in rebuilt
        assert "- two" in rebuilt
        assert "> quoted" in rebuilt

    def test_fence_is_separated_from_the_next_paragraph(self):
        rebuilt = _rebuild("```\ncode\n```\n\nnext paragraph\n")
        assert rebuilt == "```\ncode\n```\n\nnext paragraph\n\n"


class TestEarlierFixesDoNotRegress:
    def test_horizontal_rule_still_survives(self):
        assert "---" in _rebuild("a\n\n---\n\nb\n")

    def test_setext_heading_is_still_an_atx_heading(self):
        assert _rebuild("Title\n---\n\nbody\n").startswith("## Title")


class TestCliKeepsBlockStructure:
    def test_lists_and_quotes_survive_translation(self, tmp_path):
        md = tmp_path / "in.md"
        md.write_text(
            "# Lists\n\n- bullet one\n- bullet two\n\n"
            "1. ordered one\n2. ordered two\n\n"
            "- parent\n  - nested child\n\n"
            "> quoted line\n> second line\n",
            encoding="utf-8",
        )
        out = tmp_path / "out"

        result = runner.invoke(
            app,
            ["translate-md", str(md), "-s", "en", "-t", "zh",
             "-o", str(out), "-c", str(CONFIG), "--no-cache"],
        )

        assert result.exit_code == 0, result.output
        body = strip_frontmatter((out / "in.md").read_text(encoding="utf-8"))
        assert "- [zh] bullet one" in body
        assert "- [zh] bullet two" in body
        assert "1. [zh] ordered one" in body
        assert "2. [zh] ordered two" in body
        assert "  - [zh] nested child" in body
        assert "> [zh] quoted line" in body
        assert "> second line" in body
