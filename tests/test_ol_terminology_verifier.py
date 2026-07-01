"""Tests for ol_terminology.verifier.

Verifies the post-translation terminology checker (no LLM, no network).
Uses FAKE_LLM via conftest.py — no real LLM needed.
"""
from __future__ import annotations

import json
from pathlib import Path


FIXTURES_DIR = Path(__file__).parent / "fixtures"
LEGACY_GLOSSARY = FIXTURES_DIR / "glossary.json"


class TestVerifyTranslationWithGlossary:
    """With-glossary mode: check verified translation appears in target."""

    def test_all_terms_verified(self):
        from ol_terminology.verifier import verify_translation
        glossary = {
            "API": {"translation": "API 端点", "variants": {}, "confidence": 0.95},
        }
        report = verify_translation(
            "Click the API endpoint.",
            "点击 API 端点。",
            glossary=glossary,
        )
        assert len(report.verified) == 1
        assert len(report.mismatches) == 0
        assert len(report.absent) == 0
        assert report.total_terms_checked == 1

    def test_detects_mismatch(self):
        from ol_terminology.verifier import verify_translation
        glossary = {
            "API": {"translation": "API 端点", "variants": {}, "confidence": 0.95},
        }
        report = verify_translation(
            "Click the API endpoint.",
            "点击 应用程序接口。",  # wrong translation
            glossary=glossary,
        )
        assert len(report.mismatches) == 1
        assert report.mismatches[0].term == "API"
        assert report.mismatches[0].expected == "API 端点"
        assert report.mismatches[0].found == "应用程序接口"

    def test_detects_absent_term(self):
        from ol_terminology.verifier import verify_translation
        glossary = {
            "API": {"translation": "API 端点", "variants": {}, "confidence": 0.95},
        }
        report = verify_translation(
            "Click the API endpoint.",
            "点击按钮。",  # term absent from target
            glossary=glossary,
        )
        assert len(report.absent) == 1
        assert report.absent[0].term == "API"

    def test_low_confidence_excluded_above_threshold(self):
        from ol_terminology.verifier import verify_translation
        glossary = {
            "low_conf_term": {"translation": "低置信术语", "variants": {}, "confidence": 0.5},
        }
        report = verify_translation(
            "The low_conf_term is here.",
            "这个低置信术语在这里。",
            glossary=glossary,
            confidence_threshold=0.7,  # 0.5 < 0.7, exclude
        )
        assert len(report.low_confidence) == 1
        assert report.low_confidence[0].term == "low_conf_term"
        assert len(report.verified) == 0

    def test_low_confidence_included_below_threshold(self):
        from ol_terminology.verifier import verify_translation
        glossary = {
            "low_conf_term": {"translation": "低置信术语", "variants": {}, "confidence": 0.5},
        }
        report = verify_translation(
            "The low_conf_term is here.",
            "这个低置信术语在这里。",
            glossary=glossary,
            confidence_threshold=0.3,  # 0.5 > 0.3, include
        )
        assert len(report.verified) == 1


class TestVerifyTranslationWithoutGlossary:
    """No-glossary mode: detect inconsistent translations across segments."""

    def test_detects_inconsistency(self):
        from ol_terminology.verifier import verify_translation
        # Source uses "button" twice; target translates it as both "按钮" and "按键"
        source = "Click the button. Press the button to continue."
        target = "点击按钮。按下按键继续。"
        report = verify_translation(source, target, glossary=None)
        # Should detect the inconsistency
        assert len(report.inconsistencies) > 0
        inconsistency = report.inconsistencies[0]
        assert "button" in inconsistency["source_term"]
        assert "按钮" in inconsistency["translations"] or "按键" in inconsistency["translations"]

    def test_no_inconsistency_when_consistent(self):
        from ol_terminology.verifier import verify_translation
        source = "Click the button. Press the button to continue."
        target = "点击按钮。按下按钮继续。"
        report = verify_translation(source, target, glossary=None)
        assert len(report.inconsistencies) == 0


class TestVerifyTranslationGlossaryFormats:
    """Both legacy dict and new Glossary dataclass formats must work."""

    def test_accepts_legacy_dict_format(self):
        from ol_terminology.verifier import verify_translation
        legacy = {
            "API": {"translation": "API 端点", "variants": {}, "confidence": 0.95},
        }
        report = verify_translation("Use the API.", "使用 API 端点。", glossary=legacy)
        assert len(report.verified) == 1

    def test_accepts_new_glossary_dataclass(self):
        from ol_terminology.verifier import verify_translation
        from ol_terminology.glossary_class import Glossary
        g = Glossary(terms={"API": ["API 端点"]})
        report = verify_translation("Use the API.", "使用 API 端点。", glossary=g)
        assert len(report.verified) == 1


class TestVerifyTranslationEdgeCases:
    """Edge cases: empty input, missing data."""

    def test_empty_source_and_target(self):
        from ol_terminology.verifier import verify_translation
        report = verify_translation("", "", glossary=None)
        assert report.total_terms_checked == 0
        assert len(report.verified) == 0
        assert len(report.mismatches) == 0

    def test_empty_glossary(self):
        from ol_terminology.verifier import verify_translation
        report = verify_translation("Hello world.", "你好世界。", glossary={})
        assert report.total_terms_checked == 0

    def test_report_to_dict_serializable(self):
        from ol_terminology.verifier import verify_translation
        glossary = {
            "API": {"translation": "API 端点", "variants": {}, "confidence": 0.95},
        }
        report = verify_translation("Use the API.", "使用 API 端点。", glossary=glossary)
        d = report.to_dict()
        json.dumps(d)  # must be JSON-serializable
        assert "verified" in d
        assert "mismatches" in d
        assert "absent" in d
        assert "inconsistencies" in d
        assert "low_confidence" in d
