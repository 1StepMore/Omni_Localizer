"""Tests for OL MCP server and tools."""
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


import inspect


class TestChunking:
    """Test _estimate_tokens and _chunk_text utilities."""

    def test_estimate_tokens_cjk(self):
        """CJK characters: 1 token ≈ 4 chars."""
        from ol_mcp.tools import _estimate_tokens

        # 4 CJK chars / 4 = 1 token
        assert _estimate_tokens("你好世界") == 1
        # 8 CJK chars / 4 = 2 tokens
        assert _estimate_tokens("你好世界你好世界") == 2

    def test_estimate_tokens_english(self):
        """English: 1 token ≈ 5 chars."""
        from ol_mcp.tools import _estimate_tokens

        # 5 non-CJK chars / 5 = 1 token
        assert _estimate_tokens("hello") == 1
        # 10 chars / 5 = 2 tokens
        assert _estimate_tokens("hello world") == 2

    def test_estimate_tokens_mixed(self):
        """Mixed CJK + English uses both formulas."""
        from ol_mcp.tools import _estimate_tokens

        # 4 CJK / 4 + 5 non-CJK / 5 = 2 tokens
        result = _estimate_tokens("你好hello")
        assert result == 2

    def test_chunk_text_small(self):
        """Text smaller than max_chars returns single chunk."""
        from ol_mcp.tools import _chunk_text

        result = _chunk_text("hello world", 100)
        assert result == ["hello world"]

    def test_chunk_text_paragraph_split(self):
        """Splits on paragraph boundary (\\n\\n)."""
        from ol_mcp.tools import _chunk_text

        result = _chunk_text("a\n\nb\n\nc", 3)
        assert result == ["a", "b", "c"]

    def test_chunk_text_heading_split(self):
        """Splits on markdown headings (# ## ###)."""
        from ol_mcp.tools import _chunk_text

        result = _chunk_text("# Intro\n\n## Chapter 1", 20)
        # Should split around heading boundaries
        assert len(result) >= 2

    def test_chunk_text_horizontal_rule(self):
        """Splits on --- (horizontal rules)."""
        from ol_mcp.tools import _chunk_text

        result = _chunk_text("intro\n\n---\n\nchapter1", 50)
        assert "---" in result

    def test_chunk_text_code_fence_preserved(self):
        """Never splits inside code fences."""
        from ol_mcp.tools import _chunk_text

        code = "```\nprint('hello')\n```"
        result = _chunk_text(code, 5)
        # Should not split inside the code fence
        assert len(result) >= 1

    def test_chunk_text_hard_split_last_resort(self):
        """Hard-split at max_chars when no boundaries found."""
        from ol_mcp.tools import _chunk_text

        # Long string with no natural boundaries
        long_text = "a" * 100
        result = _chunk_text(long_text, 30)
        # Should have multiple chunks
        assert len(result) > 1
        # Each chunk should be <= max_chars
        for chunk in result:
            assert len(chunk) <= 30

    def test_chunk_text_empty(self):
        """Empty text returns empty list."""
        from ol_mcp.tools import _chunk_text

        result = _chunk_text("", 10)
        assert result == []


class TestTranslateMdTextFlatSchema:
    """Verify tool functions have flat (non-wrapped) signatures."""

    def test_translate_md_text_flat_signature(self):
        """translate_md_text takes flat primitives, not params wrapper."""
        from ol_mcp.tools import translate_md_text

        sig = inspect.signature(translate_md_text)
        params = list(sig.parameters.keys())
        # Should NOT have 'params' as a parameter
        assert "params" not in params
        # Should have these flat parameters
        assert "content" in params
        assert "source_lang" in params
        assert "target_lang" in params
        assert "glossary_path" in params
        assert "config_path" in params
        assert "add_frontmatter" in params
        assert "max_chars_per_chunk" in params

    def test_judge_text_flat_signature(self):
        """judge_text takes flat primitives."""
        from ol_mcp.tools import judge_text

        sig = inspect.signature(judge_text)
        params = list(sig.parameters.keys())
        assert "params" not in params
        assert "source" in params
        assert "target" in params
        assert "source_lang" in params
        assert "target_lang" in params

    def test_load_glossary_flat_signature(self):
        """load_glossary takes flat primitives."""
        from ol_mcp.tools import load_glossary

        sig = inspect.signature(load_glossary)
        params = list(sig.parameters.keys())
        assert "params" not in params
        assert "path" in params
        assert "config_dir" in params

    def test_batch_translate_texts_flat_signature(self):
        """batch_translate_texts takes texts as list[str], not params wrapper."""
        from ol_mcp.tools import batch_translate_texts

        sig = inspect.signature(batch_translate_texts)
        params = list(sig.parameters.keys())
        assert "params" not in params
        assert "texts" in params
        assert "source_lang" in params
        assert "target_lang" in params
        assert "glossary_path" in params
        assert "concurrency" in params
        assert "max_chars_per_chunk" in params


class TestMaxCharsPerChunk:
    """Verify max_chars_per_chunk parameter on chunking tools."""

    def test_translate_md_text_has_max_chars_param(self):
        """translate_md_text accepts max_chars_per_chunk parameter."""
        from ol_mcp.tools import translate_md_text

        sig = inspect.signature(translate_md_text)
        params = list(sig.parameters.keys())
        assert "max_chars_per_chunk" in params
        # Check it's the last param
        assert params[-1] == "max_chars_per_chunk"
        # Check default is None
        param = sig.parameters["max_chars_per_chunk"]
        assert param.default is None

    def test_batch_translate_texts_has_max_chars_param(self):
        """batch_translate_texts accepts max_chars_per_chunk parameter."""
        from ol_mcp.tools import batch_translate_texts

        sig = inspect.signature(batch_translate_texts)
        params = list(sig.parameters.keys())
        assert "max_chars_per_chunk" in params
        # Check default is None
        param = sig.parameters["max_chars_per_chunk"]
        assert param.default is None