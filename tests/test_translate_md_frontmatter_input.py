"""OMNI_Localizer#146 — an input frontmatter block must not reach the LLM.

`translate-md` read the input file verbatim, so a Markdown file that already
carries YAML frontmatter (an earlier OL output being re-translated, or a
hand-written file) had its `---` read as a horizontal rule and the YAML block
translated as prose. The default path now strips the block before translating,
and both code paths share one helper.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

# Activate the FAKE_LLM seam BEFORE any ol_cli imports.
os.environ["OMNI_TEST_FAKE_LLM"] = "1"

_suite_root = Path(__file__).resolve().parents[2]
if str(_suite_root) not in sys.path:
    sys.path.insert(0, str(_suite_root))

from typer.testing import CliRunner

from cli.frontmatter import strip_frontmatter
from ol_cli import app

runner = CliRunner()

_CONFIG = """project_id: test
source_lang: en
target_lang: zh
llm_pool:
  translation:
    - provider: openai
      model: glm-4-flash
      priority: 1
      role: translation
      api_key: ${ZHIPU_API_KEY}
      base_url: http://localhost
    - provider: openai
      model: glm-4-flash
      priority: 2
      role: translation
      api_key: ${ZHIPU_API_KEY}
      base_url: http://localhost
  judging:
    - provider: openai
      model: glm-4-flash
      priority: 1
      role: judging
      api_key: ${ZHIPU_API_KEY}
      base_url: http://localhost
    - provider: openai
      model: glm-4-flash
      priority: 2
      role: judging
      api_key: ${ZHIPU_API_KEY}
      base_url: http://localhost
  restoration:
    - provider: openai
      model: glm-4-flash
      priority: 1
      role: restoration
      api_key: ${ZHIPU_API_KEY}
      base_url: http://localhost
    - provider: openai
      model: glm-4-flash
      priority: 2
      role: restoration
      api_key: ${ZHIPU_API_KEY}
      base_url: http://localhost
"""

_FRONTMATTERED = """---
source_lang: en
target_lang: zh
format: docx
---

# Hello World

This is a translatable paragraph.
"""


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    md = tmp_path / "in.md"
    md.write_text(_FRONTMATTERED, encoding="utf-8")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CONFIG, encoding="utf-8")
    return md, cfg


def _body_only(text: str) -> str:
    return strip_frontmatter(text)


class TestStripFrontmatterHelper:
    def test_strips_leading_block(self):
        assert strip_frontmatter(_FRONTMATTERED).lstrip().startswith("# Hello World")

    def test_handles_crlf(self):
        raw = "---\r\nsource_lang: en\r\n---\r\n\r\nbody\r\n"
        assert strip_frontmatter(raw).strip() == "body"

    def test_leaves_text_without_frontmatter_unchanged(self):
        raw = "# Title\n\nbody\n"
        assert strip_frontmatter(raw) == raw

    def test_leaves_unterminated_leading_rule_unchanged(self):
        raw = "---\n\nnot frontmatter, no closing rule\n"
        assert strip_frontmatter(raw) == raw

    def test_preserves_a_horizontal_rule_inside_the_body(self):
        raw = "# Title\n\nfirst\n\n---\n\nsecond\n"
        assert strip_frontmatter(raw) == raw


class TestTranslateMdStripsInputFrontmatter:
    def test_default_path_does_not_translate_the_yaml_block(self, tmp_path):
        md, cfg = _write_inputs(tmp_path)
        out = tmp_path / "out"

        result = runner.invoke(
            app,
            ["translate-md", str(md), "-s", "en", "-t", "zh",
             "-o", str(out), "-c", str(cfg), "--no-cache"],
        )

        assert result.exit_code == 0, result.output
        body = _body_only((out / "in.md").read_text(encoding="utf-8"))
        assert "source_lang" not in body, body
        assert "target_lang" not in body, body
        assert "format:" not in body, body

    def test_chunked_path_matches_the_default_path(self, tmp_path):
        md, cfg = _write_inputs(tmp_path)
        out = tmp_path / "out_chunk"

        result = runner.invoke(
            app,
            ["translate-md", str(md), "-s", "en", "-t", "zh",
             "-o", str(out), "-c", str(cfg), "--no-cache",
             "--chunk-by-paragraph"],
        )

        assert result.exit_code == 0, result.output
        body = _body_only((out / "in.md").read_text(encoding="utf-8"))
        assert "source_lang" not in body, body
        assert "format:" not in body, body

    def test_no_horizontal_rule_warning_for_frontmatter_input(self, tmp_path):
        md, cfg = _write_inputs(tmp_path)
        out = tmp_path / "out_warn"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = runner.invoke(
                app,
                ["translate-md", str(md), "-s", "en", "-t", "zh",
                 "-o", str(out), "-c", str(cfg), "--no-cache"],
            )

        assert result.exit_code == 0, result.output
        messages = [str(w.message) for w in caught]
        assert not any("Unknown token type: hr" in m for m in messages), messages
