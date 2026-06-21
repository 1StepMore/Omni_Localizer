"""T3 regression tests: OL MCP translate_md_text CLI parity params.

Locks in the audit T3 (2026-06-21) additions:
- glossary_max_terms (default 5, range 1-50)
- no_glossary (default False)
- no_restoration (default False)

These are CLI parity params that allow agents to control the same
features the CLI exposes via --glossary-max-terms / --no-glossary /
--no-restoration.
"""
from __future__ import annotations

import pytest

from ol_mcp.tools import TranslateInput


class TestTranslateInputParityParams:
    def test_default_glossary_max_terms_is_5(self):
        ti = TranslateInput(content="x", source_lang="en", target_lang="zh")
        assert ti.glossary_max_terms == 5

    def test_glossary_max_terms_accepted(self):
        ti = TranslateInput(
            content="x", source_lang="en", target_lang="zh", glossary_max_terms=15
        )
        assert ti.glossary_max_terms == 15

    def test_glossary_max_terms_lower_bound(self):
        with pytest.raises(Exception):
            TranslateInput(
                content="x", source_lang="en", target_lang="zh", glossary_max_terms=0
            )

    def test_glossary_max_terms_upper_bound(self):
        with pytest.raises(Exception):
            TranslateInput(
                content="x", source_lang="en", target_lang="zh", glossary_max_terms=51
            )

    def test_no_glossary_default_false(self):
        ti = TranslateInput(content="x", source_lang="en", target_lang="zh")
        assert ti.no_glossary is False

    def test_no_glossary_accepted(self):
        ti = TranslateInput(
            content="x", source_lang="en", target_lang="zh", no_glossary=True
        )
        assert ti.no_glossary is True

    def test_no_restoration_default_false(self):
        ti = TranslateInput(content="x", source_lang="en", target_lang="zh")
        assert ti.no_restoration is False

    def test_no_restoration_accepted(self):
        ti = TranslateInput(
            content="x", source_lang="en", target_lang="zh", no_restoration=True
        )
        assert ti.no_restoration is True
