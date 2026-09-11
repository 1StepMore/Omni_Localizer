"""Tests for Phase 2 MCP consistency in OL (P2-T1, T2, T3, T4, T5).

These tests verify the unified MCP configuration across the Omni Suite.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# P2-T1: MCP_ALLOWED_DIRECTORIES env var should be the primary
# ---------------------------------------------------------------------------


class TestP2T1UnifiedEnvVar:
    """P2-T1: Read MCP_ALLOWED_DIRECTORIES as primary, with OL_MCP_ALLOWED_DIRS
    and OL_ALLOWED_DIRECTORIES as fallbacks."""

    def test_mcp_allowed_directories_is_primary(self, tmp_path):
        """Setting MCP_ALLOWED_DIRECTORIES should configure the validator."""
        from ol_mcp.security import get_default_validator

        target = str(tmp_path / "unified_dir")
        with patch.dict(os.environ, {
            "MCP_ALLOWED_DIRECTORIES": target,
            "OL_MCP_ALLOWED_DIRS": "",
            "OL_ALLOWED_DIRECTORIES": "",
        }, clear=False):
            validator = get_default_validator()
            resolved = Path(target).resolve()
            assert resolved in validator.allowed_directories, (
                f"MCP_ALLOWED_DIRECTORIES={target} not picked up. "
                f"Got: {validator.allowed_directories}"
            )

    def test_ol_mcp_allowed_dirs_fallback(self, tmp_path):
        """OL_MCP_ALLOWED_DIRS should still work as fallback."""
        from ol_mcp.security import get_default_validator

        target = str(tmp_path / "fallback_dir")
        with patch.dict(os.environ, {
            "MCP_ALLOWED_DIRECTORIES": "",
            "OL_MCP_ALLOWED_DIRS": target,
            "OL_ALLOWED_DIRECTORIES": "",
        }, clear=False):
            validator = get_default_validator()
            resolved = Path(target).resolve()
            assert resolved in validator.allowed_directories, (
                f"OL_MCP_ALLOWED_DIRS={target} not picked up as fallback. "
                f"Got: {validator.allowed_directories}"
            )

    def test_mcp_allowed_directories_takes_precedence(self, tmp_path):
        """MCP_ALLOWED_DIRECTORIES should override OL_MCP_ALLOWED_DIRS."""
        from ol_mcp.security import get_default_validator

        primary = str(tmp_path / "primary")
        fallback = str(tmp_path / "fallback")
        with patch.dict(os.environ, {
            "MCP_ALLOWED_DIRECTORIES": primary,
            "OL_MCP_ALLOWED_DIRS": fallback,
            "OL_ALLOWED_DIRECTORIES": "",
        }, clear=False):
            validator = get_default_validator()
            primary_resolved = Path(primary).resolve()
            fallback_resolved = Path(fallback).resolve()
            assert primary_resolved in validator.allowed_directories
            # Fallback should NOT be in the list when primary is set
            assert fallback_resolved not in validator.allowed_directories, (
                "MCP_ALLOWED_DIRECTORIES should take precedence over OL_MCP_ALLOWED_DIRS"
            )


# ---------------------------------------------------------------------------
# P2-T2: Server name should be 'ol-mcp'
# ---------------------------------------------------------------------------


class TestP2T2ServerName:
    """P2-T2: OL MCP server should be named 'ol-mcp'."""

    def test_server_name_is_ol_mcp(self):
        from ol_mcp.tools import mcp
        assert mcp.name == "ol-mcp", (
            f"Server name is '{mcp.name}', expected 'ol-mcp'"
        )


# ---------------------------------------------------------------------------
# P2-T3: MCP_TOOL_TIMEOUT env var
# ---------------------------------------------------------------------------


class TestP2T3Timeout:
    """P2-T3: Read MCP_TOOL_TIMEOUT env var, default 120s."""

    def test_default_timeout_is_120(self):
        """Default timeout should be 120 seconds."""
        from ol_mcp.config import ServerConfig
        cfg = ServerConfig()
        assert cfg.timeout == 120.0, (
            f"Default timeout is {cfg.timeout}, expected 120.0"
        )

    def test_mcp_tool_timeout_env_var(self):
        """MCP_TOOL_TIMEOUT env var should override the default."""
        from ol_mcp.config import ServerConfig
        with patch.dict(os.environ, {"MCP_TOOL_TIMEOUT": "60"}):
            cfg = ServerConfig()
            assert cfg.timeout == 60.0, (
                f"MCP_TOOL_TIMEOUT=60 not picked up. Got {cfg.timeout}"
            )


# ---------------------------------------------------------------------------
# P2-T4: MCP_ALLOWED_EXTENSIONS env var
# ---------------------------------------------------------------------------


class TestP2T4AllowedExtensions:
    """P2-T4: Read MCP_ALLOWED_EXTENSIONS env var to override default set."""

    def test_default_extensions_include_md_and_json(self):
        """Default extensions should include .md and .json."""
        from ol_mcp.security import PathValidator
        assert ".md" in PathValidator.ALLOWED_EXTENSIONS
        assert ".json" in PathValidator.ALLOWED_EXTENSIONS

    def test_mcp_allowed_extensions_env_var(self):
        """MCP_ALLOWED_EXTENSIONS env var should override the default set."""
        from ol_mcp.security import PathValidator
        custom = {".txt", ".csv", ".yaml"}
        with patch.dict(os.environ, {"MCP_ALLOWED_EXTENSIONS": ".txt,.csv,.yaml"}):
            extensions = PathValidator.get_allowed_extensions()
            assert extensions == custom, (
                f"Expected {custom}, got {extensions}"
            )

    def test_mcp_allowed_extensions_empty_uses_default(self):
        """Empty MCP_ALLOWED_EXTENSIONS should fall back to default."""
        from ol_mcp.security import PathValidator
        with patch.dict(os.environ, {"MCP_ALLOWED_EXTENSIONS": ""}):
            extensions = PathValidator.get_allowed_extensions()
            assert extensions == PathValidator.ALLOWED_EXTENSIONS, (
                "Empty MCP_ALLOWED_EXTENSIONS should use default"
            )


# ---------------------------------------------------------------------------
# P2-T5: PathValidator wired into all MCP tools that accept file paths
# ---------------------------------------------------------------------------


class TestP2T5PathValidatorWired:
    """P2-T5: MCP tools should reject paths outside allowed directories."""

    @pytest.mark.asyncio
    async def test_extract_warnings_rejects_etc_passwd(self, tmp_path):
        """extract_warnings should reject /etc/passwd via PathValidator."""
        from ol_mcp.extract_warnings import extract_warnings
        from ol_mcp.tools import ExtractWarningsInput

        with patch.dict(os.environ, {
            "MCP_ALLOWED_DIRECTORIES": str(tmp_path),
            "OL_MCP_ALLOWED_DIRS": "",
            "OL_ALLOWED_DIRECTORIES": "",
        }):
            params = ExtractWarningsInput(
                file_path="/etc/passwd",
            )
            result_raw = await extract_warnings(params)
            result = json.loads(result_raw)
            assert result.get("success") is False, (
                f"extract_warnings should reject /etc/passwd but got: {result}"
            )
            # Should be a path validation error, not a file-not-found
            error_msg = result.get("error", {}).get("message", "") if isinstance(result.get("error"), dict) else str(result.get("message", ""))
            assert "PATH_NOT_ALLOWED" in error_msg or "path" in error_msg.lower() or "not within allowed" in error_msg.lower(), (
                f"Expected path validation error, got: {error_msg}"
            )

    @pytest.mark.asyncio
    async def test_translate_file_rejects_etc_passwd(self, tmp_path):
        """translate_file should reject /etc/passwd via PathValidator."""
        from ol_mcp.translate_file import translate_file
        from ol_mcp.tools import TranslateFileInput

        with patch.dict(os.environ, {
            "MCP_ALLOWED_DIRECTORIES": str(tmp_path),
            "OL_MCP_ALLOWED_DIRS": "",
            "OL_ALLOWED_DIRECTORIES": "",
        }):
            params = TranslateFileInput(
                file_path="/etc/passwd",
                source_lang="en",
                target_lang="zh",
                output_format="docx",
            )
            result_raw = await translate_file(params)
            result = json.loads(result_raw)
            assert result.get("success") is False, (
                f"translate_file should reject /etc/passwd but got: {result}"
            )

    @pytest.mark.asyncio
    async def test_batch_translate_rejects_glossary_outside_allowed(self, tmp_path):
        """batch_translate_texts should reject glossary_path outside allowed dirs."""
        from ol_mcp.batch_translate import batch_translate_texts
        from ol_mcp.tools import BatchTranslateInput

        with patch.dict(os.environ, {
            "MCP_ALLOWED_DIRECTORIES": str(tmp_path),
            "OL_MCP_ALLOWED_DIRS": "",
            "OL_ALLOWED_DIRECTORIES": "",
            "OMNI_TEST_FAKE_LLM": "1",
        }):
            params = BatchTranslateInput(
                texts=["hello world"],
                source_lang="en",
                target_lang="zh",
                glossary_path="/etc/passwd",
            )
            result_raw = await batch_translate_texts(params)
            result = json.loads(result_raw)
            # The tool should either reject the glossary path or produce a warning
            warnings = result.get("content", {}).get("warnings", []) if result.get("content") else []
            glossary_warning = any("OL_PATH_DENIED" in w or "not within allowed" in w.lower() for w in warnings)
            assert glossary_warning or result.get("success") is False, (
                f"batch_translate should warn about glossary path outside allowed dirs. "
                f"Got: {result}"
            )
