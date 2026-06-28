"""batch_translate_texts MCP tool for Omni-Localizer."""

from __future__ import annotations

import json
import logging
from typing import Any

_logger = logging.getLogger(__name__)

from ol_mcp.tools import (
    _error_response,
    _get_config_path,
    _register_tool,
    _resolve_async,
    _success_response,
    BatchTranslateInput,
    mcp_error_boundary,
)
from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_pool.router import ModelPool
from ol_terminology.glossary import get_relevant_terms as _get_relevant_terms, load_glossary_from_path
from ol_terminology.rag_injector import build_translate_prompt


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
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
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

    content = {
        "results": processed,
        "total": len(params.texts),
        "succeeded": succeeded,
        "failed": failed,
        "warnings": warnings,
        "assembled_document": "---".join([r["translated"] for r in processed]),
    }
    if failed == 0:
        resp = _success_response(content)
    else:
        resp = _error_response(
            "OL_BATCH_PARTIAL_FAILURE",
            f"{failed} of {len(params.texts)} translations failed",
        )
        resp["content"] = content
    return json.dumps(resp, ensure_ascii=False)
