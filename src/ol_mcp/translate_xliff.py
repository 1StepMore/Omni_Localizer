"""translate_xliff and get_translation_status MCP tools for Omni-Localizer."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

from ol_mcp.tools import (
    _error_response,
    _get_config_path,
    _register_tool,
    _success_response,
    _task_tracker,
    TranslateXliffInput,
    GetTranslationStatusInput,
    mcp_error_boundary,
)
from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.security import get_default_validator
from ol_mcp.status import get_translation_status as _get_translation_status_impl
from ol_mcp.task_tracker import TaskStatus
from ol_pool.router import ModelPool
from ol_terminology.glossary import get_relevant_terms as _get_relevant_terms, load_glossary_from_path
from ol_terminology.rag_injector import build_translate_prompt
from ol_xliff.parser import XliffParser
from ol_xliff.pipeline import XLIFFRepairPipeline
from ol_buses.xliff_shield import restore_tags


async def _run_translate_xliff_async(
    request_id: str,
    input_path: str,
    output_path: str | None,
    source_lang: str,
    target_lang: str,
    glossary_path: str | None,
    config_path: str | None,
    styleguide_path: str | None = None,
    polish: bool = False,
) -> None:
    """Background coroutine for async translate_xliff. Updates task tracker."""
    try:
        _task_tracker.update_progress(request_id, TaskStatus.RUNNING, progress=0.0)

        resolved_config = _get_config_path(config_path)
        warnings: list[str] = []

        if output_path is None:
            input_p = Path(input_path)
            output_path = str(input_p.with_stem(f"{input_p.stem}_translated").with_suffix(".xlf"))

        _validator = get_default_validator()
        _iv = _validator.validate_path(input_path)
        if not _iv.success:
            _task_tracker.update_progress(
                request_id, TaskStatus.FAILED,
                error={"code": "OL_INVALID_INPUT", "message": f"OL_PATH_NOT_ALLOWED: {_iv.error}"},
            )
            return
        _ov = _validator.validate_path(output_path, allow_missing=True)
        if not _ov.success:
            _task_tracker.update_progress(
                request_id, TaskStatus.FAILED,
                error={"code": "OL_INVALID_INPUT", "message": f"OL_PATH_NOT_ALLOWED: {_ov.error}"},
            )
            return

        glossary: dict[str, dict[str, Any]] | None = None
        if glossary_path:
            _gv = _validator.validate_path(glossary_path)
            if _gv.success:
                try:
                    glossary = load_glossary_from_path(
                        glossary_path,
                        config_dir=Path(glossary_path).parent if not Path(glossary_path).is_absolute() else None,
                    )
                except Exception as e:  # expected — glossary load is best-effort
                    warnings.append(f"Glossary load failed: {e}")
                    glossary = None
            else:
                warnings.append(f"OL_PATH_NOT_ALLOWED: {_gv.error}")
                glossary = None

        styleguide_section: str | None = None
        if styleguide_path:
            from ol_style.schema import StyleGuide
            _sg_v = _validator.validate_path(styleguide_path)
            if _sg_v.success:
                try:
                    sg = StyleGuide.from_json_file(styleguide_path)
                    styleguide_section = sg.to_prompt_section()
                except Exception as e:
                    warnings.append(f"StyleGuide load failed: {e}")
                    styleguide_section = None
            else:
                warnings.append(f"OL_PATH_NOT_ALLOWED: {_sg_v.error}")
                styleguide_section = None

        parser = XliffParser()
        units = parser.parse(input_path)
        units_processed = len(units)

        if units_processed == 0:
            _task_tracker.update_progress(
                request_id, TaskStatus.FAILED,
                error={"code": "OL_INVALID_INPUT", "message": "No translation units found in XLIFF file"},
            )
            return

        pool = ModelPool.get_instance(resolved_config)
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
                        src_lang=source_lang, tgt_lang=target_lang,
                        tm_matches=None, glossary_terms=terms,
                        style_guide=styleguide_section,
                    )
            elif styleguide_section:
                context = build_translate_prompt(
                    text=unit.source_text,
                    src_lang=source_lang, tgt_lang=target_lang,
                    style_guide=styleguide_section,
                )
            translated = await pool.translate(unit.source_text, source_lang, target_lang, context)

            if unit_shield_map:
                unshielded = restore_tags(translated, unit_shield_map)
                repaired, unit_warnings = repair_pipeline.repair(unshielded, unit.source_text, unit_shield_map)
                if unit_warnings:
                    warnings_per_unit[unit.unit_id] = unit_warnings
            else:
                repaired = translated
            unit.target_text = repaired

        if polish:
            from ol_xliff.polish import polish_translated_units
            polish_warnings = await polish_translated_units(
                units, source_lang, target_lang, pool,
            )
            for uid, pw in polish_warnings.items():
                warnings_per_unit.setdefault(uid, []).extend(pw)

        from ol_buses.xliff_bus import write_target_back, _ensure_target_tags
        from ol_core.dataclass import TranslationContext, ChannelType

        original_text = Path(input_path).read_text(encoding='utf-8')
        original_text = _ensure_target_tags(original_text)

        ctx = TranslationContext(
            file_path=input_path, channel_type=ChannelType.XLIFF,
            original_full_text=original_text, units=units,
            glossary=glossary or {}, config={},
            warnings_per_unit=warnings_per_unit,
        )
        write_target_back(ctx, output_path, warnings_per_unit=warnings_per_unit)

        payload = {
            "output_path": output_path,
            "units_processed": units_processed,
            "warnings": warnings,
        }
        _task_tracker.update_progress(request_id, TaskStatus.COMPLETED, progress=1.0, result=payload)
    except Exception as e:  # expected — background task failure, update tracker
        _task_tracker.update_progress(
            request_id, TaskStatus.FAILED,
            error={"code": "OL_INTERNAL_ERROR", "message": str(e)},
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
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    if params.async_mode:
        request_id = _task_tracker.create_task()
        asyncio.create_task(_run_translate_xliff_async(
            request_id=request_id,
            input_path=params.input_path,
            output_path=params.output_path,
            source_lang=params.source_lang,
            target_lang=params.target_lang,
            glossary_path=params.glossary_path,
            config_path=params.config_path,
            styleguide_path=params.styleguide_path,
            polish=params.polish,
        ))
        return json.dumps(
            _success_response({"request_id": request_id, "status": "pending"}),
            ensure_ascii=False,
        )

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
            _error_response("OL_INVALID_INPUT", f"OL_PATH_NOT_ALLOWED: {_iv.error}"),
            ensure_ascii=False,
        )
    _ov = _validator.validate_path(output_path, allow_missing=True)
    if not _ov.success:
        return json.dumps(
            _error_response("OL_INVALID_INPUT", f"OL_PATH_NOT_ALLOWED: {_ov.error}"),
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
                except Exception as e:  # expected — glossary load is best-effort
                    warnings.append(f"Glossary load failed: {e}")
                    glossary = None
            else:
                warnings.append(f"OL_PATH_NOT_ALLOWED: {_gv.error}")
                glossary = None

        styleguide_section: str | None = None
        if params.styleguide_path:
            from ol_style.schema import StyleGuide
            _sg_v = _validator.validate_path(params.styleguide_path)
            if _sg_v.success:
                try:
                    sg = StyleGuide.from_json_file(params.styleguide_path)
                    styleguide_section = sg.to_prompt_section()
                except Exception as e:
                    warnings.append(f"StyleGuide load failed: {e}")
                    styleguide_section = None
            else:
                warnings.append(f"OL_PATH_NOT_ALLOWED: {_sg_v.error}")
                styleguide_section = None

        parser = XliffParser()
        units = parser.parse(params.input_path)
        units_processed = len(units)

        if units_processed == 0:
            return json.dumps(
                _error_response("OL_INVALID_INPUT", "No translation units found in XLIFF file"),
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
                        style_guide=styleguide_section,
                    )
            elif styleguide_section:
                context = build_translate_prompt(
                    text=unit.source_text,
                    src_lang=params.source_lang,
                    tgt_lang=params.target_lang,
                    style_guide=styleguide_section,
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

        if params.polish:
            from ol_xliff.polish import polish_translated_units
            polish_warnings = await polish_translated_units(
                units, params.source_lang, params.target_lang, pool,
            )
            for uid, pw in polish_warnings.items():
                warnings_per_unit.setdefault(uid, []).extend(pw)

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

        content = {
            "output_path": output_path,
            "units_processed": units_processed,
            "warnings": warnings,
        }
        return json.dumps(_success_response(content), ensure_ascii=False)

    except FileNotFoundError as e:
        return json.dumps(
            _error_response("OL_FILE_NOT_FOUND", f"File not found: {e}"),
            ensure_ascii=False,
        )
    except Exception as e:  # expected — return error response for sync translate failures
        return json.dumps(
            _error_response("OL_INTERNAL_ERROR", str(e)),
            ensure_ascii=False,
        )


@_register_tool(
    "get_translation_status",
    GetTranslationStatusInput,
    "Poll the status of an async translation task by request_id.",
)
@mcp_error_boundary
async def get_translation_status(params: GetTranslationStatusInput) -> str:
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)
    return _get_translation_status_impl(params.request_id, _task_tracker)
