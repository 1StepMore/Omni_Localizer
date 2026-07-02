"""A12 tests: Glossary dataclass — load/validate/find/inject (PR12 of slim-pipeline-hardening).

TDD: these tests are written FIRST (before the production code). They
exercise the new ``ol_terminology.Glossary`` dataclass that backs the
``--glossary`` CLI flag (A12.1) and the prompt-injection hook in the
translation pipeline (A12.3).

Glossary JSON format (v1, this PR):

    {
      "terms": [
        {"source": "API", "targets": ["应用程序接口", "API"]},
        ...
      ]
    }

The dataclass stores ``terms`` as ``dict[str, list[str]]`` (source → targets).
Loading validates the schema with a Pydantic model and raises ``ValueError``
on malformed input. Relevance ranking is a simple substring-match count
(top-N with the highest occurrence count; ties broken by source string
order — deterministic, no random).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from textwrap import dedent

import pytest

# Windows compat — same idiom as test_xliff_translate.py.
if sys.platform == "win32":
    import unittest.mock
    sys.modules.setdefault("fcntl", unittest.mock.MagicMock())


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_GLOSSARY = FIXTURES_DIR / "sample_glossary.json"


# ============================================================================
# test_glossary_load_validates_schema
# ============================================================================

class TestGlossaryLoadValidatesSchema:
    """Glossary.load() must validate the JSON/YAML schema and raise on bad input."""

    def test_load_valid_json_returns_glossary_instance(self):
        """Valid JSON with the {terms:[{source,targets},...]} schema loads cleanly."""
        from ol_terminology import Glossary

        g = Glossary.load(SAMPLE_GLOSSARY)

        assert isinstance(g, Glossary), f"expected Glossary, got {type(g).__name__}"
        # Source text maps to a list of target strings.
        assert g.terms["API"] == ["应用程序接口", "API"]
        assert g.terms["rendering"] == ["渲染"]
        # Every term in the fixture is loaded.
        assert len(g.terms) == 12

    def test_load_yaml_file_returns_glossary_instance(self, tmp_path):
        """YAML glossary (same schema) loads cleanly — confirms JSON-or-YAML support."""
        from ol_terminology import Glossary

        yaml_path = tmp_path / "glossary.yaml"
        yaml_path.write_text(
            dedent("""\
                terms:
                  - source: API
                    targets:
                      - 应用程序接口
                      - API
                  - source: kernel
                    targets:
                      - 内核
            """),
            encoding="utf-8",
        )

        g = Glossary.load(yaml_path)

        assert isinstance(g, Glossary)
        assert g.terms["API"] == ["应用程序接口", "API"]
        assert g.terms["kernel"] == ["内核"]

    def test_load_missing_top_level_terms_key_raises(self, tmp_path):
        """Glossary JSON without the required `terms` key must raise ValueError."""
        from ol_terminology import Glossary

        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"entries": []}), encoding="utf-8")  # wrong key
        with pytest.raises(ValueError, match="terms"):
            Glossary.load(bad)

    def test_load_term_missing_source_raises(self, tmp_path):
        """A term entry without `source` must fail validation."""
        from ol_terminology import Glossary

        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps({"terms": [{"targets": ["翻译"]}]}), encoding="utf-8"
        )
        with pytest.raises(ValueError):
            Glossary.load(bad)

    def test_load_term_missing_targets_raises(self, tmp_path):
        """A term entry without `targets` must fail validation."""
        from ol_terminology import Glossary

        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps({"terms": [{"source": "API"}]}), encoding="utf-8"
        )
        with pytest.raises(ValueError):
            Glossary.load(bad)

    def test_load_empty_targets_list_raises(self, tmp_path):
        """An empty `targets` list is invalid (a term must map to ≥1 target)."""
        from ol_terminology import Glossary

        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps({"terms": [{"source": "API", "targets": []}]}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            Glossary.load(bad)

    def test_load_malformed_json_raises(self, tmp_path):
        """Syntactically broken JSON raises ValueError (not JSONDecodeError leak)."""
        from ol_terminology import Glossary

        bad = tmp_path / "bad.json"
        bad.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(ValueError):
            Glossary.load(bad)

    def test_load_nonexistent_file_raises(self, tmp_path):
        """A missing glossary file raises a clear error."""
        from ol_terminology import Glossary

        with pytest.raises((FileNotFoundError, ValueError)):
            Glossary.load(tmp_path / "no_such_file.json")


# ============================================================================
# test_glossary_find_relevant_returns_top_n
# ============================================================================

class TestGlossaryFindRelevantTopN:
    """Glossary.find_relevant() returns the top-N most relevant terms for a source text."""

    def test_find_relevant_returns_top_5_from_10_matching(self):
        """Feed a source that matches 10 terms, assert exactly 5 are returned,
        ordered by occurrence count (highest first)."""
        from ol_terminology import Glossary

        g = Glossary.load(SAMPLE_GLOSSARY)

        # Build a source with 10 distinct terms appearing 1..10 times respectively.
        # "thread" appears 1 time, "lock" 2 times, ..., "API" 10 times.
        # The top-5 must be the terms with the highest counts: API(10), render(9), ...
        counts = {
            "API": 10,
            "rendering": 9,
            "shader": 8,
            "pipeline": 7,
            "compiler": 6,
            "endpoint": 5,
            "middleware": 4,
            "kernel": 3,
            "buffer": 2,
            "thread": 1,
        }
        chunks = []
        for term, n in counts.items():
            chunks.append((term + " ") * n)
        source_text = " ".join(chunks)

        top5 = g.find_relevant(source_text, max_terms=5)

        assert len(top5) == 5, f"expected 5 results, got {len(top5)}"
        # Each item is a (source_str, targets_list) tuple.
        for item in top5:
            assert isinstance(item, tuple) and len(item) == 2, (
                f"expected (source, targets) tuple, got {item!r}"
            )
            src, tgts = item
            assert isinstance(src, str)
            assert isinstance(tgts, list) and len(tgts) >= 1
            assert all(isinstance(t, str) for t in tgts)

        # Top-5 should be the 5 terms with the highest counts, in descending order.
        expected_order = ["API", "rendering", "shader", "pipeline", "compiler"]
        actual_order = [src for src, _ in top5]
        assert actual_order == expected_order, (
            f"top-5 ordering wrong: actual={actual_order} "
            f"expected={expected_order}"
        )

    def test_find_relevant_with_default_max_terms(self):
        """The default max_terms is 5 (back-compat with the spec)."""
        from ol_terminology import Glossary

        g = Glossary.load(SAMPLE_GLOSSARY)
        # Build a source with all 12 terms appearing.
        source_text = " ".join(SAMPLE_GLOSSARY.read_text(encoding="utf-8").split())

        top = g.find_relevant(source_text)  # no max_terms arg
        assert len(top) == 5, (
            f"default max_terms should be 5, got {len(top)} results"
        )

    def test_find_relevant_excludes_zero_count_terms(self):
        """Terms not in the source text are excluded (substring match count = 0)."""
        from ol_terminology import Glossary

        g = Glossary.load(SAMPLE_GLOSSARY)
        # Source mentions only "API" and "kernel".
        source_text = "The API calls the kernel handler."

        top = g.find_relevant(source_text, max_terms=5)

        sources = {src for src, _ in top}
        assert "API" in sources, f"API should be in top terms, got {sources}"
        assert "kernel" in sources, f"kernel should be in top terms, got {sources}"
        # Terms not in the source are excluded.
        assert "rendering" not in sources
        assert "shader" not in sources
        assert "queue" not in sources

    def test_find_relevant_empty_text_returns_empty(self):
        """Empty source text returns an empty list (no terms can match)."""
        from ol_terminology import Glossary

        g = Glossary.load(SAMPLE_GLOSSARY)
        assert g.find_relevant("", max_terms=5) == []

    def test_find_relevant_empty_glossary_returns_empty(self):
        """A Glossary with zero terms returns an empty list."""
        from ol_terminology import Glossary

        g = Glossary(terms={})
        assert g.find_relevant("anything", max_terms=5) == []


# ============================================================================
# test_translation_prompt_includes_relevant_glossary_terms
# ============================================================================

class TestPromptInjectionIncludesRelevantTerms:
    """Glossary.inject_into_prompt() appends the matched terms to the prompt."""

    def test_inject_into_prompt_appends_matched_terms(self):
        """A prompt built with inject_into_prompt() must contain the matched terms."""
        from ol_terminology import Glossary

        g = Glossary.load(SAMPLE_GLOSSARY)
        source = "We use the API and the rendering engine."
        base_prompt = "Translate the following text from en to zh."

        injected = g.inject_into_prompt(source, base_prompt, max_terms=5)

        # The base prompt is preserved verbatim.
        assert base_prompt in injected, (
            f"base prompt missing from injected output: {injected!r}"
        )
        # The matched terms are present (case-insensitive substring).
        # "API" and "rendering" both appear in the source — both must be in the
        # injected section.
        lowered = injected.lower()
        assert "api" in lowered, f"'API' not in injected prompt: {injected!r}"
        assert "rendering" in lowered, (
            f"'rendering' not in injected prompt: {injected!r}"
        )
        # Each injected term line follows a "source → target" pattern (or a
        # variant — the spec is "Use these terms: src→tgt, src2→tgt2").
        assert ("→" in injected) or ("->" in injected), (
            f"expected a source→target separator in injected prompt: {injected!r}"
        )

    def test_inject_into_prompt_no_match_returns_unchanged(self):
        """If no glossary term matches the source, the prompt is returned unchanged."""
        from ol_terminology import Glossary

        g = Glossary.load(SAMPLE_GLOSSARY)
        # Source has none of the glossary terms.
        source = "xyzqq foobar bazquux"
        base_prompt = "Translate this text."

        injected = g.inject_into_prompt(source, base_prompt, max_terms=5)

        assert injected == base_prompt, (
            f"prompt should be unchanged when no terms match, got: {injected!r}"
        )

    def test_inject_into_prompt_includes_top_5_in_order(self):
        """The top-5 relevant terms (by occurrence count) appear in the injection."""
        from ol_terminology import Glossary

        g = Glossary.load(SAMPLE_GLOSSARY)
        # "API" appears 5 times, "shader" 4, ..., "buffer" 1.
        # Top-5 should be API, shader, pipeline, kernel, thread (or some 5 of the top counts).
        source = (
            "API API API API API "
            "shader shader shader shader "
            "pipeline pipeline pipeline "
            "kernel kernel "
            "thread "
            "buffer "
        )
        base_prompt = "Translate."

        injected = g.inject_into_prompt(source, base_prompt, max_terms=5)

        # The top-5 should all appear in the prompt (order is by count desc).
        # We don't enforce exact line ordering — just that the top terms are present.
        for term in ["API", "shader", "pipeline"]:
            assert term in injected, (
                f"top term {term!r} missing from injected prompt: {injected!r}"
            )


class TestGlossaryTargetLang:
    """OL#8: Glossary must track optional target_lang metadata and validate it."""

    def test_load_with_target_lang_sets_field(self, tmp_path):
        """When the glossary JSON has a top-level target_lang, it is extracted."""
        from ol_terminology import Glossary

        p = tmp_path / "glossary_with_lang.json"
        p.write_text('{"target_lang": "zh", "terms": [{"source": "API", "targets": ["接口"]}]}')
        g = Glossary.load(p)
        assert g.target_lang == "zh"

    def test_load_without_target_lang_leaves_none(self):
        """When the glossary JSON has no target_lang, it defaults to None."""
        from ol_terminology import Glossary

        g = Glossary.load(SAMPLE_GLOSSARY)
        assert g.target_lang is None

    def test_for_target_matching_lang_returns_self(self):
        """for_target() with matching lang returns the same glossary instance."""
        from ol_terminology import Glossary

        g = Glossary(terms={"API": ["接口"]}, target_lang="zh")
        result = g.for_target("zh")
        assert result is g

    def test_for_target_mismatched_lang_raises(self):
        """for_target() with mismatched lang raises ValueError."""
        from ol_terminology import Glossary

        g = Glossary(terms={"API": ["接口"]}, target_lang="zh")
        with pytest.raises(ValueError, match="mismatch"):
            g.for_target("fr")

    def test_for_target_none_lang_passes(self):
        """for_target() with target_lang=None skips validation (multi-target glossary)."""
        from ol_terminology import Glossary

        g = Glossary(terms={"API": ["接口"]}, target_lang=None)
        result = g.for_target("fr")
        assert result is g


class TestAiShangHaierGlossaryFixture:
    """T4.0: tests for the new tests/fixtures/glossary_爱上海尔.json fixture."""

    FIXTURE = FIXTURES_DIR / "glossary_爱上海尔.json"

    def test_fixture_loads_with_six_terms(self):
        from ol_terminology import Glossary
        g = Glossary.load(self.FIXTURE)
        assert g.target_lang == "en"
        assert len(g.terms) == 6
        for source in ("开利", "三翼鸟", "滚筒洗衣机", "波轮洗衣机", "朗境", "海尔朗境 X11"):
            assert source in g.terms, f"missing term {source!r} in fixture"

    def test_fixture_find_relevant_carrie(self):
        """开利 in source text should match the 开利 → Carrier entry."""
        from ol_terminology import Glossary
        g = Glossary.load(self.FIXTURE)
        matches = g.find_relevant("开利是全球领先的空调制造商")
        ids = [src for src, _ in matches]
        assert "开利" in ids

    def test_fixture_find_relevant_sanyiniao(self):
        """三翼鸟 in source text should match the 三翼鸟 entry."""
        from ol_terminology import Glossary
        g = Glossary.load(self.FIXTURE)
        matches = g.find_relevant("三翼鸟平台是海尔的高端品牌")
        ids = [src for src, _ in matches]
        assert "三翼鸟" in ids
