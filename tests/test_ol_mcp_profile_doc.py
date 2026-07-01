"""Tests for the profile_doc MCP tool."""
from __future__ import annotations

import asyncio
import json

import pytest


class TestProfileDocInputModel:
    """ProfileDocInput Pydantic model validation."""

    def test_minimal_input(self):
        from ol_mcp.tools import ProfileDocInput
        i = ProfileDocInput(content="Hello world.")
        assert i.content == "Hello world."
        assert i.source_lang == "en"
        assert i.config_path is None
        assert i.use_cache is True
        assert i.shared_secret is None

    def test_with_source_lang(self):
        from ol_mcp.tools import ProfileDocInput
        i = ProfileDocInput(content="你好", source_lang="zh")
        assert i.source_lang == "zh"

    def test_with_config_path(self):
        from ol_mcp.tools import ProfileDocInput
        i = ProfileDocInput(content="x", config_path="/path/to/config.yaml")
        assert i.config_path == "/path/to/config.yaml"

    def test_use_cache_default_true(self):
        from ol_mcp.tools import ProfileDocInput
        i = ProfileDocInput(content="x")
        assert i.use_cache is True

    def test_use_cache_false(self):
        from ol_mcp.tools import ProfileDocInput
        i = ProfileDocInput(content="x", use_cache=False)
        assert i.use_cache is False


class TestProfileDocMCPTool:
    """profile_doc MCP tool functional tests."""

    def test_tool_registered(self):
        from ol_mcp.tools import TOOL_REGISTRY
        assert "profile_doc" in TOOL_REGISTRY
        fn, input_model, description = TOOL_REGISTRY["profile_doc"]
        assert fn is not None
        assert input_model is not None
        assert "profile" in description.lower() or "document" in description.lower()

    def test_tool_in_all(self):
        from ol_mcp import tools as tools_mod
        assert "profile_doc" in tools_mod.__all__

    def test_tool_basic_invocation(self):
        """Functional test: invoke profile_doc with simple content."""
        from ol_mcp.tools import ProfileDocInput
        from ol_mcp.profile_doc import profile_doc
        params = ProfileDocInput(content="A test document about engineering.")
        result = asyncio.run(profile_doc(params))
        data = json.loads(result)
        assert data["success"] is True
        assert "content" in data
        profile = data["content"]["profile"]
        # StyleGuide fields
        assert "tone" in profile
        assert "register" in profile
        assert "summary" in profile

    def test_tool_with_cjk_content(self):
        from ol_mcp.tools import ProfileDocInput
        from ol_mcp.profile_doc import profile_doc
        params = ProfileDocInput(content="这是一个测试文档。", source_lang="zh")
        result = asyncio.run(profile_doc(params))
        data = json.loads(result)
        assert data["success"] is True
        # In FAKE_LLM mode, _source_lang is included
        profile = data["content"]["profile"]
        assert profile.get("_source_lang") == "zh"

    def test_tool_use_cache_false(self):
        from ol_mcp.tools import ProfileDocInput
        from ol_mcp.profile_doc import profile_doc
        params = ProfileDocInput(content="Test content.", use_cache=False)
        result = asyncio.run(profile_doc(params))
        data = json.loads(result)
        assert data["success"] is True

    def test_tool_with_config_path(self, tmp_path):
        """profile_doc with explicit config should respect the config."""
        from ol_mcp.tools import ProfileDocInput
        from ol_mcp.profile_doc import profile_doc
        config_path = tmp_path / "config.yaml"
        config_path.write_text("""
project_id: "test"
source_lang: "en"
target_lang: "zh"
llm_pool:
  translation:
    - provider: "openai"
      model: "test-model"
      priority: 1
      role: "translation"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
    - provider: "openai"
      model: "test-model-2"
      priority: 2
      role: "translation"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
  judging:
    - provider: "openai"
      model: "test-model"
      priority: 1
      role: "judging"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
    - provider: "openai"
      model: "test-model-2"
      priority: 2
      role: "judging"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
  restoration:
    - provider: "openai"
      model: "test-model"
      priority: 1
      role: "restoration"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
    - provider: "openai"
      model: "test-model-2"
      priority: 2
      role: "restoration"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
  profiling:
    - provider: "openai"
      model: "test-model"
      priority: 1
      role: "profiling"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
""", encoding="utf-8")
        params = ProfileDocInput(content="Test content.", config_path=str(config_path))
        result = asyncio.run(profile_doc(params))
        data = json.loads(result)
        assert data["success"] is True
