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
import base64
import inspect
import json
import logging
import os
import re
from pathlib import Path
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
from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_pool.router import ModelPool
from ol_terminology.glossary import get_relevant_terms as _get_relevant_terms, load_glossary_from_path
from ol_terminology.rag_injector import build_translate_prompt
from ol_tm.service import TMService
from ol_xliff.parser import XliffParser
from ol_xliff.pipeline import XLIFFRepairPipeline
from ol_buses.xliff_shield import restore_tags
from ol_mcp._errors import mcp_error_boundary
from ol_mcp.security import get_default_validator
from ol_mcp.auth import check_auth, auth_failure_response
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response


def _resolve_async(result):
    """Resolve a potentially async result.

    ModelPool.translate is async in production but tests mock it with a sync
    function that returns a string. This helper handles both shapes.
    """
    if asyncio.iscoroutine(result):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            import concurrent.futures
            def _runner():
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(result)
                finally:
                    new_loop.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(_runner).result()
        if loop is not None:
            return loop.run_until_complete(result)
        return asyncio.run(result)
    return result


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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_config_path(config_path: str | None) -> str:
    """Resolve config path: explicit param > env var > default."""
    if config_path:
        return config_path
    return os.environ.get("OL_CONFIG_PATH", "config/default.yaml")


async def _translate_single(
    content: str,
    source_lang: str,
    target_lang: str,
    glossary: dict[str, dict[str, Any]] | None,
    config_path: str,
    glossary_max_terms: int = 5,
    no_glossary: bool = False,
    no_restoration: bool = False,
) -> tuple[str, list[str]]:
    """Translate a single text through shield → translate → repair → unshield."""
    warnings: list[str] = []

    try:
        shielded, shield_map = shield_markdown(content)

        context = None
        if glossary and not no_glossary:
            terms = _get_relevant_terms(shielded, glossary=glossary, top_k=glossary_max_terms)
            if terms:
                context = build_translate_prompt(
                    text=shielded,
                    src_lang=source_lang,
                    tgt_lang=target_lang,
                    tm_matches=None,
                    glossary_terms=terms,
                )

        pool = ModelPool.get_instance(config_path)
        translated = await pool.translate(shielded, source_lang, target_lang, context)

        if shield_map:
            unshielded = unshield_markdown(translated, shield_map)
            repaired = MDRepairPipeline().repair(unshielded, content, shield_map)
        else:
            repaired = translated

        # E2E-14 residual fix: deduplicate base64-encoded image refs.
        # OPP may emit base64 data URIs for images; the LLM can re-encode
        # already-unshielded image refs as fresh base64 lines. These decode
        # to the same standard refs already present in the text and must be
        # dropped to avoid polluting the output.
        repaired = _dedup_b64_image_refs(repaired)

        return repaired, warnings
    except Exception as e:
        _logger.exception("translate_md_text failed: %s", e)
        raise


# Pattern matches base64-encoded image references: "![Image N](base64encoded)"
_BASE64_IMG_PATTERN = re.compile(
    r'!\[Image (\d+)\]\(([A-Za-z0-9+/=]{20,})\.(png|jpg|jpeg|gif)\)'
)
_IMG_REF_PATTERN = re.compile(r'!\[Image (\d+)\]\(([^)]+)\)')


def _try_decode_b64_image(s: str) -> str:
    """Try to decode a string as base64; return original if it decodes to an image ref."""
    try:
        decoded = base64.b64decode(s.encode('ascii')).decode('utf-8', errors='strict')
        if decoded.startswith('![Image ') and '](' in decoded:
            return decoded
    except Exception:
        pass
    return s


def _dedup_b64_image_refs(text: str) -> str:
    """Remove base64 image lines whose decoded content is already in text as a standard ref."""
    existing_refs = set(_IMG_REF_PATTERN.findall(text))
    def replacer(m: re.Match) -> str:
        img_num, b64_data, ext = m.group(1), m.group(2), m.group(3)
        decoded = _try_decode_b64_image(b64_data)
        key = (img_num, decoded.split('](', 1)[1].rstrip(')'))
        already_exists = key in existing_refs or any(
            n == img_num and decoded.split('](', 1)[1].rstrip(')') in ref
            for n, ref in existing_refs
        )
        return '' if already_exists else m.group(0)
    return _BASE64_IMG_PATTERN.sub(replacer, text)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


@_register_tool(
    "translate_md_text",
    TranslateInput,
    "Translate markdown text directly without file I/O.",
)
@mcp_error_boundary
async def translate_md_text(params: TranslateInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps({**rate_limit_failure_response(), "error": rate_err}, ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Translate markdown text using OL's translation pipeline.

    Handles code blocks, links, images automatically (preserved, not translated).
    Runs through shield → translate → repair → unshield pipeline.

    Returns a JSON string with: success, translated, warnings, source_lang, target_lang
    """

    warnings: list[str] = []
    config_path = _get_config_path(params.config_path)

    try:
        glossary: dict[str, dict[str, Any]] | None = None
        if params.glossary_path and not params.no_glossary:
            try:
                glossary = load_glossary_from_path(
                    params.glossary_path,
                    config_dir=Path(params.glossary_path).parent if not Path(params.glossary_path).is_absolute() else None,
                )
            except Exception as e:
                warnings.append(f"Glossary load failed: {e}")

        result, _ = await _translate_single(
            params.content,
            params.source_lang,
            params.target_lang,
            glossary,
            config_path,
            glossary_max_terms=params.glossary_max_terms,
            no_glossary=params.no_glossary,
            no_restoration=params.no_restoration,
        )

        from ol_cli import _generate_frontmatter, _validate_lang_code, _get_ol_version

        if params.add_frontmatter:
            safe_src = _validate_lang_code(params.source_lang)
            safe_tgt = _validate_lang_code(params.target_lang)
            frontmatter = _generate_frontmatter(
                source_lang=safe_src,
                target_lang=safe_tgt,
                original_filename="input.md",
                ol_version=_get_ol_version(),
            )
            result = frontmatter + result

        return json.dumps(
            {
                "success": True,
                "translated": result,
                "warnings": warnings,
                "source_lang": params.source_lang,
                "target_lang": params.target_lang,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        error_msg = str(e) if str(e) else type(e).__name__
        _logger.error("translate_md_text failed: error=%s", error_msg, exc_info=True)
        return json.dumps(
            {
                "success": False,
                "translated": "",
                "warnings": warnings + [error_msg],
                "source_lang": params.source_lang,
                "target_lang": params.target_lang,
            },
            ensure_ascii=False,
        )


@_register_tool(
    "judge_text",
    JudgeInput,
    "Evaluate translation quality using LLM judge.",
)
@mcp_error_boundary
async def judge_text(params: JudgeInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps({**rate_limit_failure_response(), "error": rate_err}, ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Evaluate translation quality with rubric scores.

    Returns: success, score (0-100), reason, judge_scores breakdown, warnings
    """

    warnings: list[str] = []

    try:
        config_path = _get_config_path(None)
        pool = ModelPool.get_instance(config_path)
        result = await pool.judge(
            params.source,
            params.target,
            params.source_lang,
            params.target_lang,
            params.glossary,
        )

        return json.dumps(
            {
                "success": True,
                "score": result.get("score", 50),
                "reason": result.get("reason", ""),
                "judge_scores": {
                    "adequacy": result.get("adequacy", 50),
                    "fluency": result.get("fluency", 50),
                    "terminology_consistency": result.get("terminology_consistency", 50),
                    "format_preservation": result.get("format_preservation", 50),
                },
                "warnings": warnings,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "score": 0,
                "reason": "",
                "judge_scores": {},
                "warnings": warnings + [str(e)],
            },
            ensure_ascii=False,
        )


@_register_tool(
    "load_glossary",
    LoadGlossaryInput,
    "Load a JSON glossary file for use in translation.",
)
@mcp_error_boundary
async def load_glossary(params: LoadGlossaryInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps({**rate_limit_failure_response(), "error": rate_err}, ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Load a JSON glossary file.

    Returns: success, glossary dict, term_count, warnings
    """

    warnings: list[str] = []

    vresult = get_default_validator().validate_path(params.path)
    if not vresult.success:
        return json.dumps(
            {
                "success": False,
                "glossary": {},
                "term_count": 0,
                "warnings": warnings + [f"OL_PATH_NOT_ALLOWED: {vresult.error}"],
            },
            ensure_ascii=False,
        )

    try:
        glossary = load_glossary_from_path(
            params.path,
            config_dir=Path(params.config_dir) if params.config_dir else None,
        )
        return json.dumps(
            {
                "success": True,
                "glossary": glossary,
                "term_count": len(glossary),
                "warnings": warnings,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "glossary": {},
                "term_count": 0,
                "warnings": warnings + [str(e)],
            },
            ensure_ascii=False,
        )


@_register_tool(
    "get_relevant_terms",
    GetRelevantTermsInput,
    "Extract relevant glossary terms for a given text.",
)
@mcp_error_boundary
async def get_relevant_terms(params: GetRelevantTermsInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps({**rate_limit_failure_response(), "error": rate_err}, ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Select top-k terms from glossary relevant to the given text.

    Matching is based on exact/partial substring + confidence scoring.

    Returns: success, terms list, count
    """

    try:
        terms = _get_relevant_terms(params.text, params.glossary, top_k=params.top_k)
        return json.dumps(
            {
                "success": True,
                "terms": terms,
                "count": len(terms),
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "terms": [],
                "count": 0,
                "warnings": [str(e)],
            },
            ensure_ascii=False,
        )


@_register_tool(
    "search_tm",
    SearchTMInput,
    "Search translation memory for similar past translations.",
)
@mcp_error_boundary
async def search_tm(params: SearchTMInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps({**rate_limit_failure_response(), "error": rate_err}, ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Search TMX file for similar past translations.

    Uses embedding-based similarity search with configurable threshold.

    Returns: success, matches list, count
    """

    warnings: list[str] = []

    vresult = get_default_validator().validate_path(params.tmx_path)
    if not vresult.success:
        return json.dumps(
            {
                "success": False,
                "matches": [],
                "count": 0,
                "warnings": warnings + [f"OL_PATH_NOT_ALLOWED: {vresult.error}"],
            },
            ensure_ascii=False,
        )

    try:
        svc = TMService(params.tmx_path)
        matches = svc.search(params.source_text, threshold=params.threshold, src_lang=params.source_lang, tgt_lang=params.target_lang)
        return json.dumps(
            {
                "success": True,
                "matches": [
                    {
                        "source": m.source,
                        "target": m.target,
                        "similarity": m.similarity,
                        "language_pair": m.language_pair,
                    }
                    for m in matches
                ],
                "count": len(matches),
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "matches": [],
                "count": 0,
                "warnings": warnings + [str(e)],
            },
            ensure_ascii=False,
        )


@_register_tool(
    "batch_translate_texts",
    BatchTranslateInput,
    "Translate multiple texts in parallel.",
)
@mcp_error_boundary
def batch_translate_texts(params: BatchTranslateInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps({**rate_limit_failure_response(), "error": rate_err}, ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Translate multiple markdown texts through the shield → translate → repair → unshield pipeline.

    Returns: success, results list with per-item success/translated/warnings, total, succeeded, failed
    """

    warnings: list[str] = []
    config_path = _get_config_path(None)

    glossary: dict[str, dict[str, Any]] | None = None
    if params.glossary_path:
        try:
            glossary = load_glossary_from_path(params.glossary_path)
        except Exception as e:
            warnings.append(f"Glossary load failed: {e}")

    pool = ModelPool.get_instance(config_path)
    repair_pipeline = MDRepairPipeline()

    processed: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    for i, text in enumerate(params.texts):
        try:
            shielded, shield_map = shield_markdown(text)

            context = None
            if glossary:
                terms = _get_relevant_terms(shielded, glossary=glossary, top_k=5)
                if terms:
                    context = build_translate_prompt(
                        text=shielded,
                        src_lang=params.source_lang,
                        tgt_lang=params.target_lang,
                        tm_matches=None,
                        glossary_terms=terms,
                    )

            translated_raw = _resolve_async(
                pool.translate(shielded, params.source_lang, params.target_lang, context),
            )
            if isinstance(translated_raw, tuple):
                translated = str(translated_raw[0]) if translated_raw else ""
            else:
                translated = str(translated_raw) if translated_raw else ""

            if shield_map:
                translated = unshield_markdown(translated, shield_map)
            repaired = repair_pipeline.repair(translated, text, shield_map)
            repair_warnings = []

            processed.append({"index": i, "success": True, "translated": repaired, "warnings": repair_warnings})
            succeeded += 1
        except Exception as e:
            processed.append({"index": i, "success": False, "translated": "", "warnings": [str(e)]})
            failed += 1

    return json.dumps(
        {
            "success": failed == 0,
            "results": processed,
            "total": len(params.texts),
            "succeeded": succeeded,
            "failed": failed,
            "warnings": warnings,
            "assembled_document": "---".join([r["translated"] for r in processed]),
        },
        ensure_ascii=False,
    )


@_register_tool(
    "translate_xliff",
    TranslateXliffInput,
    "Translate an XLIFF file (writes <target> elements to the output file).",
)
@mcp_error_boundary
async def translate_xliff(params: TranslateXliffInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps({**rate_limit_failure_response(), "error": rate_err}, ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    # 2026-06-17 round 9: was sync, used _resolve_async(asyncio.run) — failed
    # inside running event loop. Now async to match translate_md_text.

    warnings: list[str] = []
    config_path = _get_config_path(params.config_path)

    if params.output_path is None:
        input_p = Path(params.input_path)
        output_path = str(input_p.with_stem(f"{input_p.stem}_translated").with_suffix(".xlf"))
    else:
        output_path = params.output_path

    _validator = get_default_validator()
    _iv = _validator.validate_path(params.input_path)
    if not _iv.success:
        return json.dumps(
            {
                "success": False,
                "output_path": output_path,
                "units_processed": 0,
                "warnings": warnings + [f"OL_PATH_NOT_ALLOWED: {_iv.error}"],
            },
            ensure_ascii=False,
        )
    _ov = _validator.validate_path(output_path, allow_missing=True)
    if not _ov.success:
        return json.dumps(
            {
                "success": False,
                "output_path": output_path,
                "units_processed": 0,
                "warnings": warnings + [f"OL_PATH_NOT_ALLOWED: {_ov.error}"],
            },
            ensure_ascii=False,
        )

    try:
        glossary: dict[str, dict[str, Any]] | None = None
        if params.glossary_path:
            _gv = _validator.validate_path(params.glossary_path)
            if _gv.success:
                try:
                    glossary = load_glossary_from_path(
                        params.glossary_path,
                        config_dir=Path(params.glossary_path).parent if not Path(params.glossary_path).is_absolute() else None,
                    )
                except Exception as e:
                    warnings.append(f"Glossary load failed: {e}")
                    glossary = None
            else:
                warnings.append(f"OL_PATH_NOT_ALLOWED: {_gv.error}")
                glossary = None

        parser = XliffParser()
        units = parser.parse(params.input_path)
        units_processed = len(units)

        if units_processed == 0:
            return json.dumps(
                {
                    "success": False,
                    "output_path": output_path,
                    "units_processed": 0,
                    "warnings": warnings + ["No translation units found in XLIFF file"],
                },
                ensure_ascii=False,
            )

        pool = ModelPool.get_instance(config_path)
        repair_pipeline = XLIFFRepairPipeline()

        warnings_per_unit: dict[str, list[str]] = {}

        for unit in units:
            unit_shield_map = unit.shield_map

            context = None
            if glossary:
                terms = _get_relevant_terms(unit.source_text, glossary=glossary, top_k=5)
                if terms:
                    context = build_translate_prompt(
                        text=unit.source_text,
                        src_lang=params.source_lang,
                        tgt_lang=params.target_lang,
                        tm_matches=None,
                        glossary_terms=terms,
                    )

            translated = await pool.translate(
                unit.source_text, params.source_lang, params.target_lang, context,
            )

            if unit_shield_map:
                unshielded = restore_tags(translated, unit_shield_map)
                repaired, unit_warnings = repair_pipeline.repair(
                    unshielded, unit.source_text, unit_shield_map
                )
                if unit_warnings:
                    warnings_per_unit[unit.unit_id] = unit_warnings
            else:
                repaired = translated

            unit.target_text = repaired

        from ol_buses.xliff_bus import write_target_back, _ensure_target_tags
        from ol_core.dataclass import TranslationContext, ChannelType

        original_text = Path(params.input_path).read_text(encoding='utf-8')
        original_text = _ensure_target_tags(original_text)

        ctx = TranslationContext(
            file_path=params.input_path,
            channel_type=ChannelType.XLIFF,
            original_full_text=original_text,
            units=units,
            glossary=glossary or {},
            config={},
            warnings_per_unit=warnings_per_unit,
        )
        write_target_back(ctx, output_path, warnings_per_unit=warnings_per_unit)

        return json.dumps(
            {
                "success": True,
                "output_path": output_path,
                "units_processed": units_processed,
                "warnings": warnings,
            },
            ensure_ascii=False,
        )

    except FileNotFoundError as e:
        return json.dumps(
            {
                "success": False,
                "output_path": output_path,
                "units_processed": 0,
                "warnings": warnings + [f"File not found: {e}"],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "output_path": output_path,
                "units_processed": 0,
                "warnings": warnings + [str(e)],
            },
            ensure_ascii=False,
        )


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
        return json.dumps({**rate_limit_failure_response(), "error": rate_err}, ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(auth_token)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    from ol_mcp import __version__ as _ol_version
    return json.dumps(
        {"success": True, "module": "ol", "version": _ol_version},
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
        except Exception as e:
            err = json.dumps(
                {
                    "success": False,
                    "error_code": "OL_INVALID_INPUT",
                    "message": f"Invalid arguments: {e}",
                },
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
            {
                "success": False,
                "error_code": "OL_UNKNOWN_TOOL",
                "message": f"Unknown tool: {name}",
            },
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
        except Exception:
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


__all__ = [
    "mcp",
    "TOOL_REGISTRY",
    "TranslateInput",
    "JudgeInput",
    "LoadGlossaryInput",
    "GetRelevantTermsInput",
    "SearchTMInput",
    "BatchTranslateInput",
    "TranslateXliffInput",
    "translate_md_text",
    "judge_text",
    "load_glossary",
    "get_relevant_terms",
    "search_tm",
    "batch_translate_texts",
    "translate_xliff",
    "ping",
]
