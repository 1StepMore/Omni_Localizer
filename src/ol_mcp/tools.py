"""MCP tools for Omni-Localizer.

All tools are async functions that wrap existing OL infrastructure.
Each tool returns a dict with consistent success/warnings structure for agent-friendly error handling.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_pool.router import ModelPool
from ol_terminology.glossary import get_relevant_terms as _get_relevant_terms, load_glossary_from_path
from ol_terminology.rag_injector import build_translate_prompt
from ol_tm.service import TMService
from ol_xliff.parser import XliffParser
from ol_xliff.pipeline import XLIFFRepairPipeline
from ol_buses.xliff_shield import restore_tags
# C12 fix: shared error boundary replaces 6+ try/except str(e) copies.
from ol_mcp._errors import mcp_error_boundary
# 2026-06-18 round 16 Phase A1: PathValidator for file-path
# inputs. Closes the OL MCP path-traversal gap (round-15 audit).
from ol_mcp.security import get_default_validator
# 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
from ol_mcp.auth import check_auth, auth_failure_response


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
            # 2026-06-18 round 14: pytest-asyncio runs the test inside a
            # running loop, so asyncio.run() would hang. Run the coroutine
            # to completion in a fresh thread that owns its own loop.
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

# Create the MCP server
mcp = FastMCP("omni-localizer")

# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class TranslateInput(BaseModel):
    """Input for translate_md_text."""

    content: str = Field(description="Markdown text to translate")
    source_lang: str = Field(description="Source language code (e.g. en, zh, ja)")
    target_lang: str = Field(description="Target language code")
    glossary_path: str | None = Field(default=None, description="Path to JSON glossary file")
    config_path: str | None = Field(default=None, description="Path to LLM config")
    add_frontmatter: bool = Field(default=False, description="Add YAML frontmatter to output")
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth. Required
    # only when MCP_SHARED_SECRET env var is set (dev mode: ignored).
    shared_secret: str | None = Field(default=None, description="Shared secret for MCP auth (required if MCP_SHARED_SECRET env var is set)")


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
) -> tuple[str, list[str]]:
    """Translate a single text through shield → translate → repair → unshield."""
    warnings: list[str] = []

    try:
        shielded, shield_map = shield_markdown(content)

        context = None
        if glossary:
            terms = _get_relevant_terms(shielded, glossary=glossary, top_k=5)
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

        return repaired, warnings
    except Exception as e:
        _logger.exception("translate_md_text failed: %s", e)
        raise


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


@mcp.tool(description="Translate markdown text directly without file I/O.")
@mcp_error_boundary
async def translate_md_text(params: TranslateInput) -> str:
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        import json as _json
        return _json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Translate markdown text using OL's translation pipeline.

    Handles code blocks, links, images automatically (preserved, not translated).
    Runs through shield → translate → repair → unshield pipeline.

    Returns a JSON string with: success, translated, warnings, source_lang, target_lang
    """
    import json

    warnings: list[str] = []
    config_path = _get_config_path(params.config_path)

    try:
        glossary: dict[str, dict[str, Any]] | None = None
        if params.glossary_path:
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


@mcp.tool(description="Evaluate translation quality using LLM judge.")
@mcp_error_boundary
async def judge_text(params: JudgeInput) -> str:
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        import json as _json
        return _json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Evaluate translation quality with rubric scores.

    Returns: success, score (0-100), reason, judge_scores breakdown, warnings
    """
    import json

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


@mcp.tool(description="Load a JSON glossary file for use in translation.")
@mcp_error_boundary
async def load_glossary(params: LoadGlossaryInput) -> str:
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        import json as _json
        return _json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Load a JSON glossary file.

    Returns: success, glossary dict, term_count, warnings
    """
    import json

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


@mcp.tool(description="Extract relevant glossary terms for a given text.")
@mcp_error_boundary
async def get_relevant_terms(params: GetRelevantTermsInput) -> str:
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        import json as _json
        return _json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Select top-k terms from glossary relevant to the given text.

    Matching is based on exact/partial substring + confidence scoring.

    Returns: success, terms list, count
    """
    import json

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


@mcp.tool(description="Search translation memory for similar past translations.")
@mcp_error_boundary
async def search_tm(params: SearchTMInput) -> str:
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        import json as _json
        return _json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Search TMX file for similar past translations.

    Uses embedding-based similarity search with configurable threshold.

    Returns: success, matches list, count
    """
    import json

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
        matches = svc.search(params.source_text, threshold=params.threshold)
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


@mcp.tool(description="Translate multiple texts in parallel.")
@mcp_error_boundary
def batch_translate_texts(params: BatchTranslateInput) -> str:
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        import json as _json
        return _json.dumps(auth_failure_response(), ensure_ascii=False)
    """
    Translate multiple markdown texts through the shield → translate → repair → unshield pipeline.

    Returns: success, results list with per-item success/translated/warnings, total, succeeded, failed
    """
    import json

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

            translated = _resolve_async(
                pool.translate(shielded, params.source_lang, params.target_lang, context),
            )

            if shield_map:
                translated = unshield_markdown(translated, shield_map)
            repaired, repair_warnings = repair_pipeline.repair(translated, text, shield_map)

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


@mcp.tool()
@mcp_error_boundary
async def translate_xliff(params: TranslateXliffInput) -> str:
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        import json as _json
        return _json.dumps(auth_failure_response(), ensure_ascii=False)
    # 2026-06-17 round 9: was sync, used _resolve_async(asyncio.run) — failed
    # inside running event loop. Now async to match translate_md_text.
    import json

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