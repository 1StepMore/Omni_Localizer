"""MCP tools for Omni-Localizer.

All tools are async functions that wrap existing OL infrastructure.
Each tool returns a dict with consistent success/warnings structure for
agent-friendly error handling.

Phase 1.4 rewrite: replaced ``mcp.server.fastmcp.FastMCP`` (which has a
stdin-handshake stdio bug in this environment) with the standard
``mcp.server.Server`` + ``stdio_server()`` pattern that the minimal
test (``tests/mcp/test_minimal_stdio.py``) verified works.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from typing import Any, Awaitable, Callable

_logger = logging.getLogger(__name__)

from mcp.server import Server
from mcp.types import Tool, TextContent
from pydantic import BaseModel, Field

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.metrics import (
    STATUS_AUTH_FAILED as _OL_STATUS_AUTH_FAILED,
    STATUS_ERROR as _OL_STATUS_ERROR,
    STATUS_RATE_LIMITED as _OL_STATUS_RATE_LIMITED,
    STATUS_SUCCESS as _OL_STATUS_SUCCESS,
    record_request_from_arguments,
    time_block as _ol_metrics_timer,
)
from ol_mcp.tracing import (
    set_span_status as _ol_tracing_set_status,
    start_call_tool_span as _ol_tracing_start_span,
    inject_traceparent as _ol_tracing_inject_traceparent,
)
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.task_tracker import InMemoryTaskTracker
from ol_mcp._errors import mcp_error_boundary  # noqa: F401  (re-export for submodules)


# ---------------------------------------------------------------------------
# Wave 0.2 (OL#13): Standardized MCP response helpers
# ---------------------------------------------------------------------------


def _error_response(code: str, message: str, **extra: Any) -> dict:
    """Standardized error response per cross-repo MCP response spec.

    Shape: ``{success: false, error: {code, message}}`` plus backward-compat
    top-level ``error_code`` and ``message`` fields.
    """
    resp: dict[str, Any] = {
        "success": False,
        "error": {"code": code, "message": message},
        "error_code": code,
        "message": message,
    }
    resp.update(extra)
    return resp


def _success_response(content: dict) -> dict:
    """Standardized success response wrapping payload under ``content``.

    Shape: ``{success: true, content: {…}}``
    """
    return {"success": True, "content": content}


# Module-level shared executor for _resolve_async to avoid thread leaks
# and deadlocks. Wave 4 (L-C5): one executor shared across all callers
# instead of creating a new ThreadPoolExecutor(max_workers=1) per coroutine.
import concurrent.futures as _concurrent_futures
_shared_executor = _concurrent_futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="ol_resolve_async",
)


def _resolve_async(result):
    """Resolve a potentially async result.

    ModelPool.translate is async in production but tests mock it with a sync
    function that returns a string. This helper handles both shapes.

    Wave 4 (L-C5): uses a module-level shared ThreadPoolExecutor instead of
    creating a new one per coroutine, preventing thread leaks and deadlocks.
    """
    if asyncio.iscoroutine(result):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            def _runner():
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(result)
                finally:
                    new_loop.close()
            return _shared_executor.submit(_runner).result()
        if loop is not None:
            return loop.run_until_complete(result)
        return asyncio.run(result)
    return result


# ---------------------------------------------------------------------------
# Wave 0.5 (OL#12): Async task tracker singleton
# ---------------------------------------------------------------------------

_task_tracker = InMemoryTaskTracker()


# ---------------------------------------------------------------------------
# Server instance + tool registry
# ---------------------------------------------------------------------------
#
# Phase 1.4: the SDK's ``mcp.server.fastmcp.FastMCP`` swallows the first
# JSON-RPC handshake on stdio in this environment. The minimal
# ``tests/mcp/test_minimal_stdio.py`` reference test confirmed the
# lower-level ``mcp.server.Server`` + ``stdio_server()`` pattern works
# correctly, so we use it instead. Tool implementations are unchanged;
# the dispatch happens in ``list_tools()`` / ``call_tool()`` below.
mcp = Server("omni-localizer")

# (callable, pydantic input model, description) — one entry per tool.
TOOL_REGISTRY: dict[str, tuple[Callable[..., Awaitable[str] | str], type[BaseModel], str]] = {}


def _register_tool(
    name: str,
    input_model: type[BaseModel],
    description: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: wrap a tool function and register it for MCP dispatch.

    The wrapped function still matches the underlying callable (so direct
    in-process callers like ``tests/test_ol_mcp.py`` work unchanged). MCP
    dispatch goes through the registry, which feeds the ``list_tools()``
    and ``call_tool()`` handlers below.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        TOOL_REGISTRY[name] = (fn, input_model, description)
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Input models (unchanged from Phase 1.3)
# ---------------------------------------------------------------------------


class TranslateInput(BaseModel):
    """Input for translate_md_text."""

    content: str = Field(description="Markdown text to translate")
    source_lang: str = Field(description="Source language code (e.g. en, zh, ja)")
    target_lang: str = Field(description="Target language code")
    glossary_path: str | None = Field(default=None, description="Path to JSON glossary file")
    config_path: str | None = Field(default=None, description="Path to LLM config")
    add_frontmatter: bool = Field(default=False, description="Add YAML frontmatter to output")
    glossary_max_terms: int = Field(
        default=5, ge=1, le=50,
        description="Max relevant glossary terms per unit (CLI: --glossary-max-terms)",
    )
    no_glossary: bool = Field(
        default=False,
        description="Disable glossary injection even if glossary_path is set (CLI: --no-glossary)",
    )
    no_restoration: bool = Field(
        default=False,
        description="Skip the A12.4 post-translation placeholder restoration (CLI: --no-restoration)",
    )
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")
    traceparent: str | None = Field(
        default=None,
        description="Optional W3C Trace Context traceparent header to make this OL span a child of an upstream trace (e.g. from OPP extract_document).",
    )
    async_mode: bool = Field(
        default=False,
        description="If True, return immediately with a request_id and run translation in background. Poll via get_translation_status.",
    )


class JudgeInput(BaseModel):
    """Input for judge_text."""

    source: str = Field(description="Original source text")
    target: str = Field(description="Translated target text")
    source_lang: str = Field(default="en", description="Source language code")
    target_lang: str = Field(default="en", description="Target language code")
    glossary: dict[str, Any] | None = Field(default=None, description="Inline glossary dict")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class LoadGlossaryInput(BaseModel):
    """Input for load_glossary."""

    path: str = Field(description="Path to JSON glossary file")
    config_dir: str | None = Field(default=None, description="Base dir for relative paths")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class GetRelevantTermsInput(BaseModel):
    """Input for get_relevant_terms."""

    text: str = Field(description="Source text to match against")
    glossary: dict[str, dict[str, Any]] = Field(description="Glossary dict from load_glossary")
    top_k: int = Field(default=5, description="Maximum terms to return")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class SearchTMInput(BaseModel):
    """Input for search_tm."""

    source_text: str = Field(description="Text to search for in TM")
    tmx_path: str = Field(description="Path to .tmx translation memory file")
    threshold: float = Field(default=0.85, description="Minimum similarity threshold (0-1)")
    source_lang: str = Field(default="en", description="Source language code (OL#8: required for language-pair filtering)")
    target_lang: str = Field(default="zh", description="Target language code (OL#8: required for language-pair filtering)")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class BatchTranslateInput(BaseModel):
    """Input for batch_translate_texts."""

    texts: list[str] = Field(description="List of markdown texts to translate")
    source_lang: str = Field(description="Source language code")
    target_lang: str = Field(description="Target language code")
    glossary_path: str | None = Field(default=None, description="Path to JSON glossary")
    concurrency: int = Field(default=5, description="Max parallel translations")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class TranslateXliffInput(BaseModel):
    """Input for translate_xliff."""

    input_path: str = Field(description="Path to input XLIFF file")
    output_path: str | None = Field(default=None, description="Path to output XLIFF file. None = overwrite source (with warning)")
    source_lang: str = Field(default="zh", description="Source language code")
    target_lang: str = Field(default="en", description="Target language code")
    glossary_path: str | None = Field(default=None, description="Path to JSON glossary file")
    config_path: str | None = Field(default=None, description="Path to LLM config")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")
    traceparent: str | None = Field(
        default=None,
        description="Optional W3C Trace Context traceparent header to make this OL span a child of an upstream trace (e.g. from OPP extract_document).",
    )
    async_mode: bool = Field(
        default=False,
        description="If True, return immediately with a request_id and run translation in background. Poll via get_translation_status.",
    )


class GetTranslationStatusInput(BaseModel):
    """Input for get_translation_status."""

    request_id: str = Field(description="The request_id returned by an async translation call")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


# ---------------------------------------------------------------------------
# Inputs for new tools (Tier 1 + Tier 2 expose plan)
# ---------------------------------------------------------------------------


class ExtractTermsInput(BaseModel):
    """Input for extract_terms."""

    texts: list[str] = Field(description="Source texts to extract terms from")
    top_n: int = Field(default=20, ge=1, le=100, description="Max terms to return")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class ExtractWarningsInput(BaseModel):
    """Input for extract_warnings."""

    file_path: str = Field(description="Path to file to scan for warning markers (MD or XLIFF)")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class TMEntry(BaseModel):
    """Single entry for add_tm_entries."""

    source: str = Field(description="Source text")
    target: str = Field(description="Target translation")
    source_lang: str = Field(description="Source language code (e.g. 'en')")
    target_lang: str = Field(description="Target language code (e.g. 'zh')")


class TMAddInput(BaseModel):
    """Input for add_tm_entries."""

    tmx_path: str = Field(description="Path to .tmx file (created if missing)")
    entries: list[TMEntry] = Field(description="List of translation entries to add")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class ShieldMdInput(BaseModel):
    """Input for shield_md_text."""

    content: str = Field(description="Markdown text to shield")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class UnshieldMdInput(BaseModel):
    """Input for unshield_md_text."""

    content: str = Field(description="Translated markdown containing [OL:...] markers")
    shield_map: dict[str, str] = Field(description="shield_map from prior shield_md_text call")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class WarningEntryDict(BaseModel):
    """Single warning entry for generate_report."""

    file_path: str = ""
    line_number: int = 0
    warning_type: str = ""
    severity: str = "medium"
    model: str = ""
    cost: float = 0.0
    source_text: str = ""
    target_text: str = ""
    reference: str = ""


class ModelCostEntryDict(BaseModel):
    """Single model cost entry for generate_report."""

    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_per_1k_tokens: float = 0.0


class GenerateReportInput(BaseModel):
    """Input for generate_report."""

    output_dir: str = Field(description="Directory to write report.html and report.csv into")
    job_id: str = Field(description="Job identifier (used in report filenames)")
    force: bool = Field(default=False, description="Overwrite existing report files")
    warnings: list[WarningEntryDict] = Field(default_factory=list, description="Warning entries")
    model_costs: list[ModelCostEntryDict] = Field(default_factory=list, description="Model cost entries")
    config_dir: str | None = Field(default=None, description="Base dir for relative paths")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class InspectConfigInput(BaseModel):
    """Input for inspect_config."""

    config_path: str | None = Field(default=None, description="Path to YAML config (defaults to OL_CONFIG_PATH or config/default.yaml)")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


class DisambiguateInput(BaseModel):
    """Input for disambiguate."""

    text: str = Field(description="Source text containing terms to disambiguate")
    glossary: dict[str, dict[str, Any]] = Field(description="Glossary dict from load_glossary")
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_config_path(config_path: str | None) -> str:
    """Resolve config path: explicit param > env var > default."""
    if config_path:
        return config_path
    return os.environ.get("OL_CONFIG_PATH", "config/default.yaml")


# ---------------------------------------------------------------------------
# ping — no Pydantic model, no @mcp_error_boundary
# ---------------------------------------------------------------------------
#
# The signature is positional-and-optional ``auth_token=None``; the MCP
# list_tools / call_tool dispatch below wraps it in a 0-arg schema and
# forwards ``auth_token`` from the JSON-RPC arguments.

async def _ping(auth_token: str | None = None) -> str:
    """Health check endpoint. Returns module name and version."""
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(auth_token)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    from ol_mcp import __version__ as _ol_version
    return json.dumps(
        _success_response({"module": "ol", "version": _ol_version}),
        ensure_ascii=False,
    )


# Register ping separately because it has no Pydantic input model.
TOOL_REGISTRY["ping"] = (
    _ping,
    None,
    "Health check endpoint.",
)


# Backwards-compatible alias for the in-process caller contract.
# (tests/test_ol_mcp.py, tests/observability/test_mcp_health.py)
async def ping(auth_token: str | None = None) -> str:
    return await _ping(auth_token)


# ---------------------------------------------------------------------------
# MCP dispatch handlers (list_tools / call_tool)
# ---------------------------------------------------------------------------


def _tool_input_schema(input_model: type[BaseModel] | None) -> dict[str, Any]:
    """Build a JSON Schema for an MCP tool.

    For Pydantic-typed tools, derive the schema from the model. For
    ping (no model), declare a 0-arg schema with an optional
    ``auth_token`` field.
    """
    if input_model is not None:
        return input_model.model_json_schema()
    return {
        "type": "object",
        "properties": {
            "auth_token": {
                "type": "string",
                "description": "Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)",
            },
        },
        "required": [],
    }


@mcp.list_tools()
async def _list_tools() -> list[Tool]:
    """Return the list of registered OL MCP tools."""
    tools: list[Tool] = []
    for name, (_fn, input_model, description) in TOOL_REGISTRY.items():
        tools.append(
            Tool(
                name=name,
                description=description,
                inputSchema=_tool_input_schema(input_model),
            )
        )
    return tools


async def _invoke_tool(fn: Callable[..., Any], arguments: dict[str, Any]) -> list[TextContent]:
    """Call a registered tool, validating arguments against its Pydantic model.

    The wrapped function may be sync (e.g. ``batch_translate_texts``) or
    async (all others). Always returns a single TextContent whose text
    is the JSON string the function produced, matching the OL tool
    contract (``str`` out).
    """
    _fn, input_model, _desc = TOOL_REGISTRY[fn.__name__] if fn.__name__ in TOOL_REGISTRY else (None, None, None)

    if input_model is not None:
        try:
            params_obj = input_model.model_validate(arguments or {})
        except Exception as e:  # expected — return error response for invalid input
            err = json.dumps(
                _error_response("OL_INVALID_INPUT", f"Invalid arguments: {e}"),
                ensure_ascii=False,
            )
            return [TextContent(type="text", text=err)]
        result = fn(params_obj)
    else:
        # ping: pass auth_token (may be absent) as a kwarg.
        result = fn(**(arguments or {}))

    if inspect.iscoroutine(result):
        result = await result

    # Tools return JSON strings; surface verbatim.
    return [TextContent(type="text", text=str(result))]


@mcp.call_tool()
async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch an MCP tool call by name."""
    if name not in TOOL_REGISTRY:
        record_request_from_arguments(
            name, arguments, _OL_STATUS_ERROR, 0.0,
        )
        with _ol_tracing_start_span(name, arguments) as _span:
            _ol_tracing_set_status(_span, "error", error_code="OL_UNKNOWN_TOOL")
        err = json.dumps(
            _error_response("OL_UNKNOWN_TOOL", f"Unknown tool: {name}"),
            ensure_ascii=False,
        )
        return [TextContent(type="text", text=err)]

    fn, _input_model, _desc = TOOL_REGISTRY[name]
    timer = _ol_metrics_timer()
    _traceparent_arg = (arguments or {}).get("traceparent")
    with _ol_tracing_start_span(name, arguments, traceparent=_traceparent_arg) as _span:
        result_blocks = await _invoke_tool(fn, arguments or {})
        try:
            payload = json.loads(result_blocks[0].text) if result_blocks else {}
        except Exception:  # expected — fallback payload on JSON parse failure
            payload = {}
        if name in ("translate_md_text", "translate_xliff") and isinstance(payload, dict):
            tp = _ol_tracing_inject_traceparent(_span)
            if tp is not None:
                payload["traceparent"] = tp
                result_blocks = [TextContent(
                    type="text", text=json.dumps(payload, ensure_ascii=False),
                )]
        status = _ol_classify_status(payload)
        record_request_from_arguments(
            name, arguments, status, timer.seconds(),
        )
        _ol_tracing_set_status(
            _span, status,
            error_code=payload.get("error_code") if isinstance(payload, dict) else None,
            duration_ms=timer.seconds() * 1000.0,
        )
        return result_blocks


def _ol_classify_status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return _OL_STATUS_ERROR
    if payload.get("success") is True:
        return _OL_STATUS_SUCCESS
    code = payload.get("error_code")
    if code == "OL_RATE_LIMITED" or code == "RATE_LIMITED":
        return _OL_STATUS_RATE_LIMITED
    if code == "AUTH_FAILED":
        return _OL_STATUS_AUTH_FAILED
    return _OL_STATUS_ERROR


# ---------------------------------------------------------------------------
# Import tool implementations — triggers @_register_tool decorators
# ---------------------------------------------------------------------------
from ol_mcp.translate_md import translate_md_text  # noqa: E402, F401
from ol_mcp.judge import judge_text  # noqa: E402, F401
from ol_mcp.glossary import load_glossary, get_relevant_terms  # noqa: E402, F401
from ol_mcp.tm import search_tm  # noqa: E402, F401
from ol_mcp.extract_terms import extract_terms  # noqa: E402, F401
from ol_mcp.tm_add import add_tm_entries  # noqa: E402, F401
from ol_mcp.shield_text import shield_md_text, unshield_md_text  # noqa: E402, F401
from ol_mcp.generate_report import generate_report  # noqa: E402, F401
from ol_mcp.inspect_config import inspect_config  # noqa: E402, F401
from ol_mcp.disambiguate import disambiguate  # noqa: E402, F401
from ol_mcp.get_capabilities import get_capabilities  # noqa: E402, F401
from ol_mcp.extract_warnings import extract_warnings  # noqa: E402, F401
from ol_mcp.batch_translate import batch_translate_texts  # noqa: E402, F401
from ol_mcp.translate_xliff import translate_xliff, get_translation_status  # noqa: E402, F401

# Register get_capabilities (no Pydantic model — static info tool).
# Done after the import above so the symbol is bound.
TOOL_REGISTRY["get_capabilities"] = (
    get_capabilities,
    None,
    "Return OL module capabilities: roles, language pairs, available tools. "
    "Use this to discover what the server can do at runtime.",
)

# The TOOL_REGISTRY is now populated with all tools.

__all__ = [
    "mcp",
    "TOOL_REGISTRY",
    "_task_tracker",
    "TranslateInput",
    "JudgeInput",
    "LoadGlossaryInput",
    "GetRelevantTermsInput",
    "SearchTMInput",
    "BatchTranslateInput",
    "TranslateXliffInput",
    "GetTranslationStatusInput",
    "ExtractTermsInput",
    "TMAddInput",
    "TMEntry",
    "ShieldMdInput",
    "UnshieldMdInput",
    "GenerateReportInput",
    "InspectConfigInput",
    "DisambiguateInput",
    "translate_md_text",
    "judge_text",
    "load_glossary",
    "get_relevant_terms",
    "search_tm",
    "batch_translate_texts",
    "translate_xliff",
    "get_translation_status",
    "extract_terms",
    "add_tm_entries",
    "shield_md_text",
    "unshield_md_text",
    "generate_report",
    "inspect_config",
    "disambiguate",
    "ping",
    "get_capabilities",
    "extract_warnings",
]
