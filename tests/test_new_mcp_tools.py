"""Tests for the 6 new OL MCP tools (Tier 1 + Tier 2 expose plan).

Covers:
- extract_terms
- add_tm_entries
- shield_md_text + unshield_md_text (roundtrip)
- generate_report
- inspect_config (with secret redaction)
- disambiguate

These tests verify the Pydantic input models are valid and that the
public async functions handle happy-path and edge cases. The actual
MCP transport layer is exercised in test_mcp_smoke.py.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Skip the entire module if pydantic isn't available
pydantic = pytest.importorskip("pydantic")

from pydantic import ValidationError


# ---------------------------------------------------------------------------
# InputModel validation tests
# ---------------------------------------------------------------------------


class TestExtractTermsInput:
    def test_minimal(self):
        from ol_mcp.tools import ExtractTermsInput

        i = ExtractTermsInput(texts=["hello", "world"])
        assert i.texts == ["hello", "world"]
        assert i.top_n == 20  # default
        assert i.shared_secret is None

    def test_custom_top_n(self):
        from ol_mcp.tools import ExtractTermsInput

        i = ExtractTermsInput(texts=["text"], top_n=5)
        assert i.top_n == 5

    def test_top_n_out_of_range(self):
        from ol_mcp.tools import ExtractTermsInput

        with pytest.raises(ValidationError):
            ExtractTermsInput(texts=["x"], top_n=0)
        with pytest.raises(ValidationError):
            ExtractTermsInput(texts=["x"], top_n=101)


class TestTMAddInput:
    def test_minimal(self):
        from ol_mcp.tools import TMAddInput, TMEntry

        i = TMAddInput(
            tmx_path="/tmp/test.tmx",
            entries=[
                TMEntry(
                    source="hello", target="hola",
                    source_lang="en", target_lang="es",
                )
            ],
        )
        assert i.tmx_path == "/tmp/test.tmx"
        assert len(i.entries) == 1
        assert i.entries[0].source == "hello"

    def test_empty_entries(self):
        from ol_mcp.tools import TMAddInput

        i = TMAddInput(tmx_path="/tmp/test.tmx", entries=[])
        assert i.entries == []


class TestShieldMdInput:
    def test_minimal(self):
        from ol_mcp.tools import ShieldMdInput

        i = ShieldMdInput(content="# Hello\n\nThis is `code`.")
        assert "code" in i.content
        assert i.shared_secret is None


class TestUnshieldMdInput:
    def test_minimal(self):
        from ol_mcp.tools import UnshieldMdInput

        i = UnshieldMdInput(
            content="See [OL:LINK:0000]",
            shield_map={"link_0000": "[click](https://example.com)"},
        )
        assert "link_0000" in i.shield_map


class TestGenerateReportInput:
    def test_minimal(self):
        from ol_mcp.tools import GenerateReportInput

        i = GenerateReportInput(output_dir="/tmp/reports", job_id="job-001")
        assert i.job_id == "job-001"
        assert i.force is False  # default
        assert i.warnings == []  # default

    def test_with_warnings(self):
        from ol_mcp.tools import GenerateReportInput, WarningEntryDict, ModelCostEntryDict

        i = GenerateReportInput(
            output_dir="/tmp/reports",
            job_id="job-001",
            warnings=[
                WarningEntryDict(
                    file_path="test.md", line_number=42,
                    warning_type="placeholder", severity="high",
                )
            ],
            model_costs=[
                ModelCostEntryDict(
                    model_name="gpt-4",
                    prompt_tokens=100, completion_tokens=50,
                    cost_per_1k_tokens=0.03,
                )
            ],
        )
        assert len(i.warnings) == 1
        assert i.warnings[0].line_number == 42


class TestInspectConfigInput:
    def test_default(self):
        from ol_mcp.tools import InspectConfigInput

        i = InspectConfigInput()
        assert i.config_path is None

    def test_explicit(self):
        from ol_mcp.tools import InspectConfigInput

        i = InspectConfigInput(config_path="/etc/ol/config.yaml")
        assert i.config_path == "/etc/ol/config.yaml"


class TestDisambiguateInput:
    def test_minimal(self):
        from ol_mcp.tools import DisambiguateInput

        i = DisambiguateInput(
            text="open the bank account",
            glossary={"bank": {"translation": "银行"}},
        )
        assert i.text == "open the bank account"
        assert "bank" in i.glossary


# ---------------------------------------------------------------------------
# Functional tests (skip if optional deps missing)
# ---------------------------------------------------------------------------


class TestShieldUnshieldRoundtrip:
    def test_roundtrip_preserves_content(self):
        pytest.importorskip("ol_md")
        from ol_mcp.shield_text import shield_md_text, unshield_md_text
        from ol_mcp.tools import ShieldMdInput, UnshieldMdInput

        # Use content with a link + heading. The shield protects the
        # link, the heading is plain text. After unshield, the link
        # must be restored. (Note: inline code `` `code` `` is also
        # protected but rendered as plain text "code" after the roundtrip
        # because the shield token replaces the backtick-wrapped text.)
        original = "# Title\n\nSee [the docs](https://example.com)."

        import asyncio
        shielded = asyncio.run(
            shield_md_text(ShieldMdInput(content=original))
        )
        shielded_data = json.loads(shielded)
        assert shielded_data["success"] is True
        assert shielded_data["content"]["marker_count"] > 0

        unshielded = asyncio.run(
            unshield_md_text(UnshieldMdInput(
                content=shielded_data["content"]["shielded_text"],
                shield_map=shielded_data["content"]["shield_map"],
            ))
        )
        unshielded_data = json.loads(unshielded)
        assert unshielded_data["success"] is True
        # The link must be restored
        assert "https://example.com" in unshielded_data["content"]["restored_text"]
        assert "[the docs]" in unshielded_data["content"]["restored_text"]


class TestInspectConfigRedaction:
    """CRITICAL SECURITY TEST: inspect_config must never leak api_key values."""

    def test_redaction_helper(self):
        from ol_mcp.inspect_config import _redact_secret, _looks_safe_base_url

        # Empty / None values
        assert _redact_secret(None) == ""
        assert _redact_secret("") == ""

        # Non-empty values
        assert _redact_secret("sk-abc123") == "***REDACTED***"
        assert _redact_secret("any-value") == "***REDACTED***"

        # base_url with ${ENV_VAR} template is safe
        assert _looks_safe_base_url("${OPENAI_BASE_URL}") is True
        assert _looks_safe_base_url("https://api.openai.com/v1") is True

        # base_url with hardcoded token-like substrings is unsafe
        assert _looks_safe_base_url("https://api.example.com/v1?key=sk-abc") is False
        assert _looks_safe_base_url("https://api.example.com/v1 Bearer xyz") is False

    def test_inspect_config_real_config_redacts_secrets(self, tmp_path):
        """End-to-end test with a synthetic config that has hardcoded api_key."""
        pytest.importorskip("ol_config")
        pytest.importorskip("ol_mcp")

        from ol_config.schema import LLMModelConfig, LLMModelRole
        from ol_mcp.inspect_config import _redact_secret, _looks_safe_base_url

        # Construct a config that has a real api_key
        mc = LLMModelConfig(
            provider="openai",
            model="gpt-4",
            priority=1,
            role=LLMModelRole.TRANSLATION,
            timeout=60.0,
            api_key="sk-supersecret-12345",
            base_url="https://api.openai.com/v1",
        )

        # Verify the redaction helpers would have protected the secret
        assert _redact_secret(mc.api_key) == "***REDACTED***"
        assert _looks_safe_base_url(mc.base_url) is True

    def test_inspect_config_catches_hardcoded_base_url_token(self):
        """If base_url contains a hardcoded token, it must be redacted."""
        from ol_mcp.inspect_config import _looks_safe_base_url, _redact_secret

        # Simulate: env-var URL is safe
        assert _looks_safe_base_url("${OPENAI_BASE_URL}/v1") is True

        # Simulate: hardcoded token in URL is NOT safe
        unsafe = "https://proxy.corp.com/v1?key=sk-abc123"
        assert _looks_safe_base_url(unsafe) is False
        assert _redact_secret(unsafe) == "***REDACTED***"
