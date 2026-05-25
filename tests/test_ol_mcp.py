"""Tests for OL MCP server and tools."""
import json
import pytest

from ol_mcp.tools import (
    TranslateInput,
    JudgeInput,
    LoadGlossaryInput,
    GetRelevantTermsInput,
    SearchTMInput,
    BatchTranslateInput,
)


class TestTranslateInput:
    """Test TranslateInput Pydantic model."""

    def test_required_fields(self):
        input = TranslateInput(
            content="# Hello World",
            source_lang="en",
            target_lang="zh",
        )
        assert input.content == "# Hello World"
        assert input.source_lang == "en"
        assert input.target_lang == "zh"
        assert input.glossary_path is None
        assert input.config_path is None
        assert input.add_frontmatter is False

    def test_optional_fields(self):
        input = TranslateInput(
            content="# Hello",
            source_lang="en",
            target_lang="ja",
            glossary_path="/path/glossary.json",
            config_path="/path/config.yaml",
            add_frontmatter=True,
        )
        assert input.glossary_path == "/path/glossary.json"
        assert input.config_path == "/path/config.yaml"
        assert input.add_frontmatter is True


class TestJudgeInput:
    """Test JudgeInput Pydantic model."""

    def test_required_fields(self):
        input = JudgeInput(
            source="Hello world",
            target="こんにちは世界",
        )
        assert input.source == "Hello world"
        assert input.target == "こんにちは世界"
        assert input.source_lang == "en"
        assert input.target_lang == "en"
        assert input.glossary is None

    def test_with_glossary(self):
        input = JudgeInput(
            source="API endpoint",
            target="API 端点",
            source_lang="en",
            target_lang="zh",
            glossary={"endpoint": {"translation": "端点"}},
        )
        assert input.glossary == {"endpoint": {"translation": "端点"}}


class TestLoadGlossaryInput:
    """Test LoadGlossaryInput Pydantic model."""

    def test_required_path(self):
        input = LoadGlossaryInput(path="/path/to/glossary.json")
        assert input.path == "/path/to/glossary.json"
        assert input.config_dir is None

    def test_with_config_dir(self):
        input = LoadGlossaryInput(
            path="glossary.json",
            config_dir="/path/to/config",
        )
        assert input.config_dir == "/path/to/config"


class TestGetRelevantTermsInput:
    """Test GetRelevantTermsInput Pydantic model."""

    def test_required_fields(self):
        input = GetRelevantTermsInput(
            text="Click the API endpoint",
            glossary={"API": {"translation": "接口"}},
        )
        assert input.text == "Click the API endpoint"
        assert input.top_k == 5

    def test_custom_top_k(self):
        input = GetRelevantTermsInput(
            text="test text",
            glossary={},
            top_k=10,
        )
        assert input.top_k == 10


class TestSearchTMInput:
    """Test SearchTMInput Pydantic model."""

    def test_required_fields(self):
        input = SearchTMInput(
            source_text="Hello world",
            tmx_path="/path/to/memory.tmx",
        )
        assert input.source_text == "Hello world"
        assert input.tmx_path == "/path/to/memory.tmx"
        assert input.threshold == 0.85

    def test_custom_threshold(self):
        input = SearchTMInput(
            source_text="test",
            tmx_path="/path.tmx",
            threshold=0.75,
        )
        assert input.threshold == 0.75


class TestBatchTranslateInput:
    """Test BatchTranslateInput Pydantic model."""

    def test_required_fields(self):
        input = BatchTranslateInput(
            texts=["Chapter 1", "Chapter 2"],
            source_lang="en",
            target_lang="zh",
        )
        assert len(input.texts) == 2
        assert input.source_lang == "en"
        assert input.target_lang == "zh"
        assert input.glossary_path is None
        assert input.concurrency == 5

    def test_with_glossary_and_concurrency(self):
        input = BatchTranslateInput(
            texts=["text1", "text2"],
            source_lang="en",
            target_lang="zh",
            glossary_path="/path/glossary.json",
            concurrency=10,
        )
        assert input.glossary_path == "/path/glossary.json"
        assert input.concurrency == 10


class TestToolInputValidation:
    """Test input validation edge cases."""

    def test_empty_content_allowed(self):
        """Empty content string is valid (agent may want to check behavior)."""
        input = TranslateInput(content="", source_lang="en", target_lang="zh")
        assert input.content == ""

    def test_unicode_content(self):
        """Unicode content is valid."""
        input = TranslateInput(
            content="# 标题\n这是中文内容",
            source_lang="zh",
            target_lang="en",
        )
        assert input.content == "# 标题\n这是中文内容"

    def test_multiline_content(self):
        """Multiline markdown content is valid."""
        content = "# Heading\n\nSome `code` and [link](url).\n\n## Subheading"
        input = TranslateInput(content=content, source_lang="en", target_lang="zh")
        assert input.content == content


class TestMcpServerModule:
    """Test that the MCP server module imports correctly."""

    def test_tools_module_imports(self):
        """Verify all tool classes and MCP server import successfully."""
        from ol_mcp.tools import (
            mcp,
            translate_md_text,  # noqa: F401 - imported to verify existence
            judge_text,  # noqa: F401 - imported to verify existence
            load_glossary,  # noqa: F401 - imported to verify existence
            get_relevant_terms,  # noqa: F401 - imported to verify existence
            search_tm,  # noqa: F401 - imported to verify existence
            batch_translate_texts,  # noqa: F401 - imported to verify existence
        )
        assert mcp is not None

    def test_package_exports(self):
        """Verify package __init__ exports mcp."""
        from ol_mcp import mcp as pkg_mcp
        assert pkg_mcp is not None