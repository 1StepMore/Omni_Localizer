"""OMNI_Localizer#148 — horizontal rules must survive translation.

`TokenPositionTracker.rebuild` had no branch for the `hr` token, so it fell
through to the generic `token.content` append; `hr.content` is empty, so every
`---` / `***` / `___` was silently dropped from the output. The extractor also
warned "Unknown token type: hr" on each one.

The chosen policy is canonical output: all three markups are re-emitted as
`---`. `rebuild` already emits block markers canonically rather than recovering
source bytes (list bullets and blockquote markers are not preserved either), so
`token.markup` -- which markdown-it normalises, e.g. `-----` -> `'------'` -- is
deliberately not used.
"""
from __future__ import annotations

import os
import warnings

import markdown_it
from typer.testing import CliRunner

from cli.frontmatter import strip_frontmatter
from ol_cli import app
from ol_core.dataclass import TranslationUnit
from ol_md.extractor import extract_and_shield_md_units, extract_translatable_tokens
from ol_md.token_stream import TokenPositionTracker

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

runner = CliRunner()

MD = markdown_it.MarkdownIt()


def _parse(text: str):
    return MD.parse(text)


def _units(tokens) -> list[TranslationUnit]:
    return [
        TranslationUnit(unit_id=f"u{i}", source_text=t.content, target_text=t.content)
        for i, t in enumerate(tokens)
        if t.type == "inline" and t.content
    ]


def _rebuild(text: str) -> str:
    tokens = _parse(text)
    return TokenPositionTracker.rebuild(tokens, _units(tokens))


def _rule_count(text: str) -> int:
    return text.count("---")


class TestRebuildEmitsHorizontalRules:
    def test_dash_rule_survives(self):
        rebuilt = _rebuild("a\n\n---\n\nb\n")
        assert rebuilt == "a\n\n---\n\nb\n\n"

    def test_star_rule_is_emitted_as_canonical_dashes(self):
        rebuilt = _rebuild("a\n\n***\n\nb\n")
        assert _rule_count(rebuilt) == 1
        assert "***" not in rebuilt

    def test_underscore_rule_is_emitted_as_canonical_dashes(self):
        rebuilt = _rebuild("a\n\n___\n\nb\n")
        assert _rule_count(rebuilt) == 1
        assert "___" not in rebuilt

    def test_two_consecutive_rules_both_survive(self):
        rebuilt = _rebuild("a\n\n---\n\nb\n\n---\n\nc\n")
        assert _rule_count(rebuilt) == 2

    def test_rule_inside_blockquote_survives(self):
        rebuilt = _rebuild("> a\n>\n> ---\n>\n> b\n")
        assert _rule_count(rebuilt) == 1

    def test_rule_inside_list_survives(self):
        rebuilt = _rebuild("- a\n\n  ---\n\n- b\n")
        assert _rule_count(rebuilt) == 1

    def test_setext_heading_does_not_gain_a_rule(self):
        rebuilt = _rebuild("Title\n---\n\nbody\n")
        assert "---" not in rebuilt
        assert "Title" in rebuilt
        assert "body" in rebuilt


class TestExtractorAcceptsHr:
    def test_no_unknown_token_type_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            extract_and_shield_md_units("a\n\n---\n\nb\n")

        unknown = [str(w.message) for w in caught if "Unknown token type" in str(w.message)]
        assert unknown == []

    def test_hr_adds_no_translation_unit(self):
        tokens = _parse("a\n\n---\n\nb\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            units = list(extract_translatable_tokens(tokens))

        assert len(units) == 2
        assert all(unit.source_text.strip() != "---" for unit in units)


class TestCliKeepsHorizontalRule:
    def test_translated_output_keeps_the_rule_between_paragraphs(self, tmp_path):
        md = tmp_path / "in.md"
        md.write_text("# Title\n\nFirst part.\n\n---\n\nSecond part.\n", encoding="utf-8")
        cfg = tmp_path / "config.yaml"
        cfg.write_text(_config_yaml(), encoding="utf-8")
        out = tmp_path / "out"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = runner.invoke(
                app,
                ["translate-md", str(md), "-s", "en", "-t", "zh",
                 "-o", str(out), "-c", str(cfg), "--no-cache"],
            )

        assert result.exit_code == 0, result.output
        assert not any("Unknown token type" in str(w.message) for w in caught)

        body = strip_frontmatter((out / "in.md").read_text(encoding="utf-8"))
        first = body.find("First")
        rule = body.find("---", first)
        second = body.find("Second")
        assert first != -1 and rule != -1 and second != -1, body
        assert first < rule < second, body


def _config_yaml() -> str:
    entry = (
        "    - provider: openai\n"
        "      model: glm-4-flash\n"
        "      priority: {priority}\n"
        "      role: {role}\n"
        "      api_key: ${{ZHIPU_API_KEY}}\n"
        "      base_url: http://localhost\n"
    )
    lines = ["project_id: test", "source_lang: en", "target_lang: zh", "llm_pool:"]
    for role in ("translation", "judging", "restoration"):
        lines.append(f"  {role}:")
        for priority in (1, 2):
            lines.append(entry.format(priority=priority, role=role))
    return "\n".join(lines)
