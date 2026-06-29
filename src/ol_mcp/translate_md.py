"""translate_md_text MCP tool for Omni-Localizer."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

from ol_mcp.tools import (
    _error_response,
    _get_config_path,
    _register_tool,
    _success_response,
    _task_tracker,
    TranslateInput,
    mcp_error_boundary,
)
from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.task_tracker import TaskStatus
from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_pool.router import ModelPool
from ol_terminology.glossary import get_relevant_terms as _get_relevant_terms, load_glossary_from_path
from ol_terminology.rag_injector import build_translate_prompt


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
    except Exception:  # expected — best-effort base64 decode
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


async def _run_translate_md_async(
    request_id: str,
    content: str,
    source_lang: str,
    target_lang: str,
    glossary_path: str | None,
    config_path: str | None,
    glossary_max_terms: int,
    no_glossary: bool,
    no_restoration: bool,
    add_frontmatter: bool,
) -> None:
    """Background coroutine for async translate_md_text. Updates task tracker."""
    try:
        _task_tracker.update_progress(request_id, TaskStatus.RUNNING, progress=0.0)

        resolved_config = _get_config_path(config_path)
        warnings: list[str] = []
        glossary: dict[str, dict[str, Any]] | None = None
        if glossary_path and not no_glossary:
            try:
                glossary = load_glossary_from_path(
                    glossary_path,
                    config_dir=Path(glossary_path).parent if not Path(glossary_path).is_absolute() else None,
                )
            except Exception as e:  # expected — glossary load is best-effort
                warnings.append(f"Glossary load failed: {e}")

        result, _ = await _translate_single(
            content, source_lang, target_lang,
            glossary, resolved_config,
            glossary_max_terms=glossary_max_terms,
            no_glossary=no_glossary,
            no_restoration=no_restoration,
        )

        if add_frontmatter:
            from ol_cli import _generate_frontmatter, _validate_lang_code, _get_ol_version
            safe_src = _validate_lang_code(source_lang)
            safe_tgt = _validate_lang_code(target_lang)
            frontmatter = _generate_frontmatter(
                source_lang=safe_src, target_lang=safe_tgt,
                original_filename="input.md", ol_version=_get_ol_version(),
            )
            result = frontmatter + result

        payload = {
            "translated": result,
            "warnings": warnings,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }
        _task_tracker.update_progress(request_id, TaskStatus.COMPLETED, progress=1.0, result=payload)
    except Exception as e:  # expected — background task failure, update tracker
        _task_tracker.update_progress(
            request_id, TaskStatus.FAILED,
            error={"code": "OL_TRANSLATE_FAILED", "message": str(e)},
        )


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
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # 2026-06-18 round 16 Phase A4: MCP shared-secret auth.
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    if params.async_mode:
        request_id = _task_tracker.create_task()
        asyncio.create_task(_run_translate_md_async(
            request_id=request_id,
            content=params.content,
            source_lang=params.source_lang,
            target_lang=params.target_lang,
            glossary_path=params.glossary_path,
            config_path=params.config_path,
            glossary_max_terms=params.glossary_max_terms,
            no_glossary=params.no_glossary,
            no_restoration=params.no_restoration,
            add_frontmatter=params.add_frontmatter,
        ))
        return json.dumps(
            _success_response({"request_id": request_id, "status": "pending"}),
            ensure_ascii=False,
        )

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
            except Exception as e:  # expected — glossary load is best-effort
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

        content = {
            "translated": result,
            "warnings": warnings,
            "source_lang": params.source_lang,
            "target_lang": params.target_lang,
        }
        resp = _success_response(content)
        resp["translated"] = result  # backward-compat alias (1 release)
        return json.dumps(resp, ensure_ascii=False)

    except Exception as e:
        error_msg = str(e) if str(e) else type(e).__name__
        _logger.error("translate_md_text failed: error=%s", error_msg, exc_info=True)
        return json.dumps(
            _error_response("OL_TRANSLATE_FAILED", error_msg),
            ensure_ascii=False,
        )
