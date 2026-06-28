"""Regression tests for ol_mcp/tools.py split.

Verifies that all 8 MCP tools and their input models are importable
from ol_mcp.tools after the module was split into 7 files.
"""
from __future__ import annotations


class TestMCPToolsImportable:
    """All tool functions and models must be importable from ol_mcp.tools."""

    def test_import_tool_functions(self):
        """All 8 tool functions + ping are importable from ol_mcp.tools."""
        from ol_mcp.tools import (
            translate_md_text,
            translate_xliff,
            judge_text,
            load_glossary,
            get_relevant_terms,
            search_tm,
            batch_translate_texts,
            get_translation_status,
            ping,
        )
        assert callable(translate_md_text)
        assert callable(translate_xliff)
        assert callable(judge_text)
        assert callable(load_glossary)
        assert callable(get_relevant_terms)
        assert callable(search_tm)
        assert callable(batch_translate_texts)
        assert callable(get_translation_status)
        assert callable(ping)

    def test_import_input_models(self):
        """All input models are importable from ol_mcp.tools."""
        from ol_mcp.tools import (
            TranslateInput,
            JudgeInput,
            LoadGlossaryInput,
            GetRelevantTermsInput,
            SearchTMInput,
            BatchTranslateInput,
            TranslateXliffInput,
            GetTranslationStatusInput,
        )
        # Instantiate a minimal model to verify Pydantic works
        ti = TranslateInput(content="hello", source_lang="en", target_lang="zh")
        assert ti.content == "hello"
        assert ti.source_lang == "en"
        assert ti.target_lang == "zh"

    def test_import_mcp_server(self):
        """mcp Server object is importable."""
        from ol_mcp.tools import mcp, TOOL_REGISTRY, _task_tracker
        assert mcp is not None
        assert isinstance(TOOL_REGISTRY, dict)
        assert _task_tracker is not None

    def test_tool_registry_populated(self):
        """All tools are registered in TOOL_REGISTRY."""
        from ol_mcp.tools import TOOL_REGISTRY

        expected_tools = {
            "translate_md_text",
            "translate_xliff",
            "judge_text",
            "load_glossary",
            "get_relevant_terms",
            "search_tm",
            "batch_translate_texts",
            "get_translation_status",
            "ping",
        }
        registered = set(TOOL_REGISTRY.keys())
        assert expected_tools.issubset(registered), (
            f"Missing tools: {expected_tools - registered}"
        )

    def test_import_from_submodules_directly(self):
        """Tool functions can also be imported from their dedicated submodules."""
        from ol_mcp.translate_md import translate_md_text
        from ol_mcp.translate_xliff import translate_xliff, get_translation_status
        from ol_mcp.judge import judge_text
        from ol_mcp.glossary import load_glossary, get_relevant_terms
        from ol_mcp.tm import search_tm
        from ol_mcp.batch_translate import batch_translate_texts

        assert callable(translate_md_text)
        assert callable(translate_xliff)
        assert callable(get_translation_status)
        assert callable(judge_text)
        assert callable(load_glossary)
        assert callable(get_relevant_terms)
        assert callable(search_tm)
        assert callable(batch_translate_texts)

    def test_package_exports_mcp(self):
        """Package __init__ still exports mcp."""
        from ol_mcp import mcp as pkg_mcp
        assert pkg_mcp is not None


class TestMCPToolModuleContents:
    """Verify each split module contains expected internal symbols."""

    def test_translate_md_module_has_helpers(self):
        from ol_mcp.translate_md import (
            _translate_single,
            _dedup_b64_image_refs,
            _run_translate_md_async,
        )
        assert callable(_translate_single)
        assert callable(_dedup_b64_image_refs)
        assert callable(_run_translate_md_async)

    def test_translate_xliff_module_has_helpers(self):
        from ol_mcp.translate_xliff import _run_translate_xliff_async
        assert callable(_run_translate_xliff_async)

    def test_glossary_module_has_both_tools(self):
        from ol_mcp.glossary import load_glossary, get_relevant_terms
        assert load_glossary is not None
        assert get_relevant_terms is not None

    def test_tools_module_has_dispatch(self):
        from ol_mcp.tools import (
            _list_tools,
            _call_tool,
            _invoke_tool,
            _register_tool,
            _error_response,
            _success_response,
        )
        assert callable(_list_tools)
        assert callable(_call_tool)
