"""OMNI_Localizer#150 — heading level must come from the tag, not the markup.

`heading_open.markup` is the ATX prefix for `#`-style headings, but a setext
heading carries `markup='-'` (h2) or `'='` (h1). Rebuild prepended that markup,
so `Title\\n---` came out as a bullet-list item and `Title\\n===` as a paragraph
starting with `=`. `tag` is `h1`-`h6` for both spellings.
"""
from __future__ import annotations

import os
from pathlib import Path

import markdown_it
import pytest
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


class TestHeadingLevel:
    def test_setext_h2_becomes_atx_h2(self):
        assert _rebuild("Title\n---\n\nbody\n") == "## Title\n\nbody\n\n"

    def test_setext_h1_becomes_atx_h1(self):
        assert _rebuild("Title\n===\n\nbody\n") == "# Title\n\nbody\n\n"

    @pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6])
    def test_atx_level_is_unchanged(self, level):
        hashes = "#" * level
        assert _rebuild(f"{hashes} Title\n\nbody\n") == f"{hashes} Title\n\nbody\n\n"

    def test_closed_atx_keeps_its_level(self):
        assert _rebuild("## Title ##\n\nbody\n") == "## Title\n\nbody\n\n"

    def test_setext_underline_does_not_become_a_rule(self):
        assert "---" not in _rebuild("Title\n---\n\nbody\n")

    def test_horizontal_rule_still_survives(self):
        assert "---" in _rebuild("a\n\n---\n\nb\n")


class TestCliSetextDocument:
    def test_both_heading_levels_survive_translation(self, tmp_path):
        md = tmp_path / "in.md"
        md.write_text(
            "Document Title\n==============\n\nIntro paragraph.\n\n"
            "Section One\n-----------\n\nBody text.\n",
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
        assert "# [zh] Document Title" in body
        assert "## [zh] Section One" in body
        assert "- [zh] Section One" not in body
        assert "\n= " not in body
