"""Tests for the verify_terms MCP tool."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestVerifyTermsInputModel:
    """VerifyTermsInput Pydantic model validation."""

    def test_minimal_input(self):
        from ol_mcp.tools import VerifyTermsInput
        i = VerifyTermsInput(
            source="Click the API.",
            target="点击 API。",
        )
        assert i.source == "Click the API."
        assert i.target == "点击 API。"
        assert i.glossary is None
        assert i.glossary_path is None
        assert i.confidence_threshold == 0.7
        assert i.source_lang == "en"
        assert i.target_lang == "zh"
        assert i.shared_secret is None

    def test_with_inline_glossary(self):
        from ol_mcp.tools import VerifyTermsInput
        glossary = {
            "API": {"translation": "API 端点", "variants": {}, "confidence": 0.95},
        }
        i = VerifyTermsInput(
            source="Click the API.",
            target="点击 API 端点。",
            glossary=glossary,
        )
        assert i.glossary == glossary

    def test_with_glossary_path(self, tmp_path):
        from ol_mcp.tools import VerifyTermsInput
        gpath = tmp_path / "g.json"
        gpath.write_text(json.dumps({
            "API": {"translation": "API 端点", "variants": {}, "confidence": 0.95}
        }), encoding="utf-8")
        i = VerifyTermsInput(
            source="Click the API.",
            target="点击 API 端点。",
            glossary_path=str(gpath),
        )
        assert i.glossary_path == str(gpath)

    def test_confidence_threshold_bounds(self):
        from ol_mcp.tools import VerifyTermsInput
        i = VerifyTermsInput(source="x", target="y", confidence_threshold=0.5)
        assert i.confidence_threshold == 0.5
        # Out of range should be rejected by Pydantic
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            VerifyTermsInput(source="x", target="y", confidence_threshold=1.5)
        with pytest.raises(ValidationError):
            VerifyTermsInput(source="x", target="y", confidence_threshold=-0.1)


class TestVerifyTermsMCPTool:
    """verify_terms MCP tool functional tests."""

    def test_tool_registered(self):
        from ol_mcp.tools import TOOL_REGISTRY
        assert "verify_terms" in TOOL_REGISTRY
        fn, input_model, description = TOOL_REGISTRY["verify_terms"]
        assert fn is not None
        assert input_model is not None
        assert "verify" in description.lower() or "term" in description.lower()

    def test_tool_in_all(self):
        from ol_mcp import tools as tools_mod
        assert "verify_terms" in tools_mod.__all__

    def test_tool_basic_invocation(self):
        """Functional test: invoke verify_terms with simple input."""
        from ol_mcp.tools import VerifyTermsInput
        from ol_mcp.verify_terms import verify_terms
        params = VerifyTermsInput(
            source="Click the API.",
            target="点击 API 端点。",
            glossary={
                "API": {"translation": "API 端点", "variants": {}, "confidence": 0.95},
            },
        )
        result = asyncio.run(verify_terms(params))
        data = json.loads(result)
        assert data["success"] is True
        assert "content" in data
        report = data["content"]
        assert report["total_terms_checked"] == 1
        assert len(report["verified"]) == 1

    def test_tool_with_glossary_path(self, tmp_path):
        from ol_mcp.tools import VerifyTermsInput
        from ol_mcp.verify_terms import verify_terms
        gpath = tmp_path / "g.json"
        gpath.write_text(json.dumps({
            "API": {"translation": "API 端点", "variants": {}, "confidence": 0.95}
        }), encoding="utf-8")
        params = VerifyTermsInput(
            source="Click the API.",
            target="点击 API 端点。",
            glossary_path=str(gpath),
        )
        result = asyncio.run(verify_terms(params))
        data = json.loads(result)
        assert data["success"] is True
        report = data["content"]
        assert report["total_terms_checked"] == 1

    def test_tool_consistency_only_mode(self):
        """Without glossary, tool runs consistency check."""
        from ol_mcp.tools import VerifyTermsInput
        from ol_mcp.verify_terms import verify_terms
        params = VerifyTermsInput(
            source="Click the button. Press the button.",
            target="点击按钮。按下按钮。",
            glossary=None,
        )
        result = asyncio.run(verify_terms(params))
        data = json.loads(result)
        assert data["success"] is True
        report = data["content"]
        assert report["total_terms_checked"] == 0
        assert len(report["inconsistencies"]) == 0
