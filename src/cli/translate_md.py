"""translate-md CLI command and MD translation helpers."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import typer

if TYPE_CHECKING:
    from ol_lqa.judge import JudgeService
    from ol_pool.router import ModelPool
    from ol_retry.retry import RetryManager
    from ol_terminology import Glossary

from cli.cache import (
    _cache_root,
    _check_cache,
    _clear_ol_cache,
    _write_cache,
    _glossary_logger,
)
from cli.frontmatter import (
    _extract_opp_metadata,
    _generate_frontmatter,
    _get_ol_version,
    _validate_lang_code,
)
from cli._shared import (
    ExitCode,
    _apply_fake_llm_seam,
    _enforce_file_size,
    ensure_output_dir,
    output_json,
    precheck_api_keys,
    validate_input_file,
    warn_fake_llm_mode,
)
from ol_logging.core import get_logger
from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_xliff.pipeline import XLIFFRepairPipeline
from ol_core.dataclass import TranslationUnit

logger = get_logger("cli")


# ========== A12: Glossary settings — passed as function args, not globals ==========
# Wave 4 (L-C1): removed concurrency-unsafe module-level globals
# (_pending_glossary, _pending_restoration_enabled, _pending_glossary_max_terms).
# Glossary params are now passed directly as function arguments to
# _translate_md_async and _translate_xliff_async. The set/consume helpers
# are removed.


def _apply_glossary_max_terms(
    glossary: 'Glossary | None', max_terms: int,
) -> 'Glossary | None':
    """Bind ``max_terms`` as the default for ``glossary.inject_into_prompt``.

    Replaces the bound method on the specific instance so the pool's call
    ``glossary.inject_into_prompt(text, prompt)`` picks up the CLI override.
    An explicit ``max_terms`` argument to the patched call wins (forward
    compat for future callers). No-op if glossary is None, missing the
    method, or max_terms is the default 5.
    """
    if glossary is None or max_terms == 5:
        return glossary
    if not hasattr(glossary, "inject_into_prompt"):
        return glossary

    original = glossary.inject_into_prompt
    default = max_terms

    def _patched(source_text: str, prompt: str, max_terms: int | None = None) -> str:
        return original(source_text, prompt, max_terms=max_terms or default)

    glossary.inject_into_prompt = _patched
    return glossary


# ========== A12.4: Post-translate restoration helper ==========

def _apply_post_translate_restoration(
    output_file: Path,
    original_text: str,
    pool: 'ModelPool | None',
) -> bool:
    """Run the A12.4 Restorer on the just-written ``output_file``.

    Reads the file, extracts ``{{_OL_*_*}}`` placeholders from
    ``original_text``, and asks the Restorer to fill any missing ones.
    Returns True if the file was rewritten. Lives outside the async
    translate functions so pre-existing tests mocking them still
    observe the restoration step (it runs after ``asyncio.run``).
    """
    from ol_restoration import Restorer, extract_placeholders

    if not output_file.exists():
        return False
    try:
        text = output_file.read_text(encoding="utf-8")
    except OSError:
        return False

    placeholders = extract_placeholders(original_text or "")
    restorer = Restorer(model_pool=pool)
    restored = restorer.restore(text, original_text or "", placeholders)
    if restored != text:
        output_file.write_text(restored, encoding="utf-8")
        return True
    return False


def _build_restoration_pool(config_path: str | None) -> 'ModelPool | None':
    """Build a ModelPool for the restoration step; returns ``None`` on failure."""
    try:
        from ol_pool.router import ModelPool
        return ModelPool.get_instance(
            config_path if config_path else "config/default.yaml",
        )
    except Exception:
        logger = get_logger("cli")
        logger.exception("ModelPool init failed")
        logger.warning("ModelPool init failed (likely test env without API keys)")
        return None


def _load_glossary_or_none(path: str | None, tgt_lang: str = "") -> 'Glossary | None':
    """Load a glossary file, or return None if ``path`` is None.

    ``--glossary`` is OPTIONAL — when the flag is not passed we return
    ``None`` and the translation pipeline runs without glossary
    injection (existing behavior, no regression).

    On load failure (malformed JSON/YAML, schema error, missing file),
    we exit with a clear error message — never silently fall back, the
    user passed the flag intentionally and wants to know.

    When ``tgt_lang`` is set and the glossary has a ``target_lang``
    metadata field that doesn't match, a WARNING is logged (not an error)
    — the user may know what they're doing with a multi-target glossary.
    """
    if path is None:
        return None
    from ol_terminology import Glossary

    p = Path(path)
    if not p.exists():
        typer.echo(f"Error: glossary file not found: {path}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)
    try:
        g = Glossary.load(p)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"Error: failed to load glossary {path}: {e}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)
    if g.target_lang and tgt_lang and g.target_lang != tgt_lang:
        _glossary_logger.warning(
            f"Glossary target_lang '{g.target_lang}' does not match "
            f"translation target '{tgt_lang}' — using anyway"
        )
    return g


def _load_env_for_cli() -> None:
    """Load .env file for CLI commands that call LLM APIs.

    Search order:
      1. $OL_DOTENV env var (explicit override)
      2. ./.env (current working directory)
      3. Walk up parent directories looking for .env
      4. ~/.config/ol/.env (user-level fallback)

    If no .env is found, the function returns silently. The LLM call
    downstream will fail loudly at the auth layer if required keys are
    missing — no silent fallback.
    """
    from pathlib import Path

    search_paths: list[Path] = []
    explicit = os.environ.get("OL_DOTENV")
    if explicit:
        search_paths.append(Path(explicit))
    search_paths.append(Path.cwd() / ".env")
    for parent in Path.cwd().resolve().parents:
        candidate = parent / ".env"
        if candidate not in search_paths:
            search_paths.append(candidate)
    search_paths.append(Path.home() / ".config" / "ol" / ".env")

    for env_path in search_paths:
        if env_path.exists() and env_path.is_file():
            _load_dotenv(env_path)
            return


def _load_dotenv(env_path: Path) -> None:
    """Parse and export .env file without blocking on missing keys."""
    try:
        content = env_path.read_text()
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                os.environ.setdefault(key, value)
    except Exception as exc:
        logger.warning("Failed to load .env file %s: %s", env_path, exc)


@dataclass
class _UnitTranslationResult:
    """Pure-data result of translating a single trans-unit.

    Produced by :func:`_translate_units_concurrent`; the caller applies
    the ``translated`` field to the ``TranslationUnit.target_text`` and
    merges the warnings into ``warnings_per_unit``. Decoupling the
    per-unit work from the side-effect (mutating the unit) keeps the
    helper testable.
    """

    unit_id: str
    translated: str
    warning: str | None = None
    repair_warnings: list[str] = field(default_factory=list)
    attempts: int = 0
    latency_ms: float = 0.0
    status: str = "ok"
    error: str | None = None


async def _translate_one_unit(
    unit: TranslationUnit,
    pool: 'ModelPool',
    judge: 'JudgeService | None',
    retry_mgr: 'RetryManager | None',
    src_lang: str,
    tgt_lang: str,
    sem: asyncio.Semaphore,
    repair_pipeline: 'MDRepairPipeline | XLIFFRepairPipeline',
    glossary: 'Glossary | None' = None,
) -> _UnitTranslationResult:
    """Translate one trans-unit, gated by ``sem``.

    Per-unit error handling: A8's retry wrap (in ``ol_retry/retry.py``)
    converts transport errors from ``translate_fn`` into a
    ``RetryResult(transport_error=True)``, which we surface as
    ``status="transport_error"`` with the OPP source as the fallback
    translation. As a defense in depth, an unexpected exception is also
    caught here and reported as ``status="exception"`` — the gather
    itself never raises.
    """
    start = time.monotonic()
    warning: str | None = None
    translated = unit.source_text
    attempts = 0
    status = "ok"
    error_msg: str | None = None

    try:
        async with sem:
            if judge is not None and retry_mgr is not None:
                async def translate_fn():
                    return await pool.translate(
                        unit.source_text, src_lang, tgt_lang,
                        context=None, glossary=glossary,
                    )

                async def judge_fn(source, translation, unit_id):
                    return await judge.judge(
                        source, translation, unit_id,
                        source_lang=src_lang, target_lang=tgt_lang,
                    )

                retry_result = await retry_mgr.execute_with_retry(
                    f"xliff_unit_{unit.unit_id}",
                    unit.source_text,
                    translate_fn,
                    judge_fn,
                )
                translated = retry_result.best_translation
                attempts = retry_result.attempts
                if retry_result.warning:
                    warning = retry_result.warning
                    logger.warning(
                        f"LQA unit {unit.unit_id}: {retry_result.warning}"
                    )
                if retry_result.transport_error:
                    status = "transport_error"
            else:
                translated = await pool.translate(
                    unit.source_text, src_lang, tgt_lang,
                    context=None, glossary=glossary,
                )
                attempts = 1
    except Exception as translate_err:
        # Defense in depth: even with the A8 retry wrap, judge_fn can
        # raise before the wrap catches it. Fall back to OPP source so
        # the chunk process never dies.
        warning = (
            f"OL_WARN: TRANSLATION_FAILED ({type(translate_err).__name__}: "
            f"{str(translate_err)[:100]})"
        )
        translated = unit.source_text
        status = "exception"
        error_msg = f"{type(translate_err).__name__}: {str(translate_err)[:200]}"
        logger.warning(
            f"Unit {unit.unit_id} translation failed: "
            f"{type(translate_err).__name__}. Using OPP source as fallback."
        )

    if isinstance(translated, str) and not translated.strip() and unit.source_text and unit.source_text.strip():
        warning = warning or "OL_WARN: EMPTY_LLM_OUTPUT (LLM returned whitespace; using OPP source)"
        logger.warning(
            f"Unit {unit.unit_id} LLM returned whitespace-only output "
            f"({translated!r}); falling back to OPP source for this unit."
        )
        translated = unit.source_text

    latency_ms = (time.monotonic() - start) * 1000.0
    # Structured per-unit log so concurrent output stays correlatable
    # (unit_id is the join key for grep).
    logger.info(
        f"xliff_unit_done unit_id={unit.unit_id} "
        f"attempt={attempts} latency_ms={latency_ms:.1f} status={status}"
    )

    if unit.shield_map:
        from ol_buses.xliff_shield import restore_tags

        unshielded = restore_tags(translated, unit.shield_map)
        repaired, repair_warnings = repair_pipeline.repair(
            unshielded, unit.source_text, unit.shield_map,
        )
    else:
        repaired = translated
        repair_warnings = []

    return _UnitTranslationResult(
        unit_id=unit.unit_id,
        translated=repaired,
        warning=warning,
        repair_warnings=repair_warnings,
        attempts=attempts,
        latency_ms=latency_ms,
        status=status,
        error=error_msg,
    )


async def _translate_units_concurrent(
    units: list,
    pool: 'ModelPool',
    judge: 'JudgeService | None',
    retry_mgr: 'RetryManager | None',
    src_lang: str,
    tgt_lang: str,
    sem: asyncio.Semaphore,
    repair_pipeline: 'MDRepairPipeline | XLIFFRepairPipeline | None' = None,
    glossary: 'Glossary | None' = None,
) -> list[_UnitTranslationResult]:
    """Translate all trans-units concurrently, capped by ``sem``.

    Replaces the serial ``for unit in units: await translate_one(unit)``
    loop with ``asyncio.gather(*tasks, return_exceptions=True)`` to fire
    multiple LLM calls at once. The caller supplies the bounded
    ``asyncio.Semaphore`` so the concurrency cap lives in
    :class:`ol_concurrency.scheduler.ConcurrencyLimiter` (single owner
    of all concurrency knobs).

    Returns one :class:`_UnitTranslationResult` per input unit, in
    **input order** (gather preserves order, not ``as_completed``). The
    gather itself only raises on a programming error; per-unit transport
    errors and exceptions are caught inside ``_translate_one_unit`` and
    reflected in the result's ``status``/``warning`` fields.
    """
    from ol_xliff.pipeline import XLIFFRepairPipeline

    if repair_pipeline is None:
        repair_pipeline = XLIFFRepairPipeline()

    _cu_count = [0]
    _cu_lock = asyncio.Lock()
    cu_n = len(units)
    PROGRESS_LOG_INTERVAL = 50

    async def _tracked_translate(u: TranslationUnit) -> _UnitTranslationResult:
        result = await _translate_one_unit(
            u, pool, judge, retry_mgr,
            src_lang, tgt_lang, sem, repair_pipeline, glossary,
        )
        async with _cu_lock:
            _cu_count[0] += 1
            done = _cu_count[0]
            if done % PROGRESS_LOG_INTERVAL == 0 or done == cu_n:
                pct = done / cu_n * 100
                logger.info(
                    f"XLIFF concurrent: {done}/{cu_n} ({pct:.0f}%)"
                )
                for h in logger.handlers:
                    h.flush()
        return result

    tasks = [
        asyncio.create_task(_tracked_translate(u))
        for u in units
    ]
    gather_results = await asyncio.gather(*tasks, return_exceptions=True)

    final: list[_UnitTranslationResult] = []
    for unit, result in zip(units, gather_results):
        if isinstance(result, BaseException):
            # Should be unreachable because _translate_one_unit catches
            # everything, but record defensively so a future refactor
            # cannot silently drop a unit.
            warning = (
                f"OL_WARN: TRANSLATION_FAILED ({type(result).__name__}: "
                f"{str(result)[:100]})"
            )
            final.append(_UnitTranslationResult(
                unit_id=unit.unit_id,
                translated=unit.source_text,
                warning=warning,
                status="exception",
                error=f"{type(result).__name__}: {str(result)[:200]}",
            ))
            logger.error(
                f"Unit {unit.unit_id} unexpected exception in gather: {result}"
            )
            continue
        final.append(result)
    return final


async def _translate_md_async(
    input_path: Path,
    output_path: Path,
    config_path: str | None,
    src_lang: str,
    tgt_lang: str,
    add_frontmatter: bool = True,
    glossary: 'Glossary | None' = None,
    restoration_enabled: bool = True,
    glossary_max_terms: int = 5,
) -> str:
    # Wave 4 (L-C1): glossary is now passed as a direct function argument,
    # not via concurrency-unsafe module-level globals.
    # The glossary param may be None (no glossary configured).
    warn_fake_llm_mode()

    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        # B1: Import from ol_pool.fake (not ol_pool.router) to avoid
        # triggering litellm's heavy import chain.
        from ol_pool.fake import _FakeModelPool  # noqa: PLC0415
        pool = cast(object, _FakeModelPool())
        _apply_fake_llm_seam()
    else:
        from ol_pool.router import ModelPool
        pool = ModelPool.get_instance(config_path) if config_path else ModelPool.get_instance()

    from ol_config.loader import load_config
    cfg, _ = load_config(config_path or os.environ.get("OL_CONFIG_PATH", "config/default.yaml"))
    src_lang = src_lang or cfg.source_lang
    tgt_lang = tgt_lang or cfg.target_lang

    max_concurrent = getattr(cfg, "max_md_concurrent", 5) or 5
    if not isinstance(max_concurrent, int) or max_concurrent < 1:
        max_concurrent = 5

    original_text = input_path.read_text(encoding="utf-8")

    judge = None
    retry_mgr = None
    if cfg.enable_lqa:
        from ol_lqa.judge import JudgeService
        from ol_retry.retry import RetryManager
        judge = JudgeService(pass_threshold=cfg.lqa_threshold, model_pool=pool)
        retry_mgr = RetryManager(
            max_retries=cfg.lqa_max_retries,
            pass_threshold=cfg.lqa_threshold,
        )

    if max_concurrent > 1:
        from ol_concurrency.scheduler import ConcurrencyLimiter
        limiter = ConcurrencyLimiter(max_translation=max_concurrent)
        repaired = await _translate_md_units_concurrent(
            original_text, pool, judge, retry_mgr,
            src_lang, tgt_lang, limiter.md_semaphore, cfg,
            glossary=glossary,
        )
    else:
        shielded, shield_map = shield_markdown(original_text)

        if cfg.enable_lqa:

            async def translate_fn():
                return await pool.translate(
                    shielded, src_lang, tgt_lang, glossary=glossary,
                )

            async def judge_fn(source, translation, unit_id):
                return await judge.judge(
                    source, translation, unit_id,
                    source_lang=src_lang, target_lang=tgt_lang,
                )

            try:
                retry_result = await retry_mgr.execute_with_retry(
                    "md_main", shielded, translate_fn, judge_fn,
                )
                translated = retry_result.best_translation
                if retry_result.warning:
                    logger.warning(f"LQA auto-retry: {retry_result.warning}")
            except Exception as translate_err:
                # Defense in depth: mirror the XLIFF path's fallback so transient
                # LLM failures don't kill the whole MD translation.
                logger.warning(
                    f"MD translation error: {type(translate_err).__name__}: {translate_err}. "
                    f"Falling back to source text."
                )
                translated = original_text
        else:
            try:
                translated = await pool.translate(
                    shielded, src_lang, tgt_lang, glossary=glossary,
                )
            except Exception as translate_err:
                logger.warning(
                    f"MD translation error: {type(translate_err).__name__}: {translate_err}. "
                    f"Falling back to source text."
                )
                translated = original_text

        if shield_map:
            repaired = MDRepairPipeline().repair(translated, original_text, shield_map)
            repaired = unshield_markdown(repaired, shield_map)
        else:
            repaired = translated

    if add_frontmatter and not repaired.strip().startswith("---"):
        safe_src_lang = _validate_lang_code(src_lang)
        safe_tgt_lang = _validate_lang_code(tgt_lang)
        opp_meta = _extract_opp_metadata(input_path)
        rid = opp_meta["request_id"]
        email_headers = opp_meta["email_headers"]
        extra_fm = {"email_headers": email_headers} if email_headers else None

        frontmatter = _generate_frontmatter(
            source_lang=safe_src_lang,
            target_lang=safe_tgt_lang,
            original_filename=input_path.name,
            ol_version=_get_ol_version(),
            request_id=rid,
            extra_frontmatter=extra_fm,
        )
        output_content = frontmatter + repaired
    else:
        output_content = repaired

    from ol_post.punctuation import normalize
    import re as _re
    _fm_match = _re.match(r'^(---\s*\n.*?\n---\s*\n)', output_content, _re.DOTALL)
    if _fm_match:
        _fm = _fm_match.group(1)
        _body = output_content[len(_fm):]
        if tgt_lang.startswith("en"):
            _body = normalize(_body, "zh", "en")
        elif tgt_lang.startswith("zh"):
            _body = normalize(_body, "en", "zh")
        elif tgt_lang.startswith("ja"):
            _body = normalize(_body, "en", "ja")
        # Other languages: no normalization (fr/de/ru/ko etc use ASCII punctuation)
        output_content = _fm + _body
    elif tgt_lang.startswith("en"):
        output_content = normalize(output_content, "zh", "en")
    elif tgt_lang.startswith("zh"):
        output_content = normalize(output_content, "en", "zh")
    elif tgt_lang.startswith("ja"):
        output_content = normalize(output_content, "en", "ja")
    # Other languages: no normalization (fr/de/ru/ko etc use ASCII punctuation)

    output_file = output_path / input_path.name
    output_file.write_text(output_content, encoding="utf-8")

    return str(output_file)


async def _translate_md_units_concurrent(
    md_text: str, pool, judge, retry_mgr,
    src_lang, tgt_lang, sem: asyncio.Semaphore,
    cfg, glossary=None,
) -> str:
    """Translate MD by extracting trans-units and translating them concurrently.

    Extracts translatable units from the full markdown text, translates
    them in parallel via :func:`_translate_units_concurrent`, then
    unshields and reassembles the markdown document.

    Args:
        glossary: Optional glossary for terminology injection. Passed through
                  to ``_translate_units_concurrent`` for parity with the serial
                  MD path.
    """
    from ol_md.extractor import extract_and_shield_md_units
    units = extract_and_shield_md_units(md_text)

    results = await _translate_units_concurrent(
        units, pool, judge, retry_mgr,
        src_lang, tgt_lang, sem, MDRepairPipeline(),
        glossary=glossary,
    )

    for i, result in enumerate(results):
        if result.status not in ("ok", "transport_error"):
            logger.warning(
                f"Unit {units[i].unit_id} status={result.status}: {result.error}"
            )
        unshielded = unshield_markdown(result.translated, units[i].shield_map)
        units[i].target_text = unshielded

    from ol_buses.md_bus import parse_md_to_tokens
    from ol_md.token_stream import TokenPositionTracker
    tokens = parse_md_to_tokens(md_text)
    tracker = TokenPositionTracker(tokens)
    return tracker.rebuild(tokens, units)


async def _translate_md_by_paragraph(
    input_path: Path,
    output_path: Path,
    config: str | None,
    src: str,
    tgt: str,
    add_frontmatter: bool,
    glossary: 'Glossary | None' = None,
) -> str:
    # Issue #35: Bypass the MCP tool (translate_md_text) to avoid
    # import-lock deadlock when concurrent=5 — the MCP handler imports
    # `from ol_cli import ...` on every call, which deadlocks with the
    # already-importing `cli.translate_md`. Directly use the low-level
    # shield → pool.translate → unshield → repair pipeline instead.
    from ol_md.shield import shield_markdown, unshield_markdown
    from ol_md.pipeline import MDRepairPipeline
    from ol_pool.router import ModelPool

    raw = input_path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    body = parts[2].strip() if len(parts) >= 3 and parts[0].strip() == "" else raw
    body = re.sub(r"^#+\s.*$", "", body, flags=re.MULTILINE)
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

    _CHUNK_CONCURRENCY = 5
    sem = asyncio.Semaphore(_CHUNK_CONCURRENCY)
    pool = ModelPool.get_instance(config) if config else ModelPool.get_instance()

    async def _translate_one_para(idx: int, p: str) -> tuple[int, str]:
        async with sem:
            try:
                shielded, shield_map = shield_markdown(p)
                translated = await pool.translate(shielded, src, tgt)
                if shield_map:
                    unshielded = unshield_markdown(translated, shield_map)
                    repaired = MDRepairPipeline().repair(unshielded, p, shield_map)
                else:
                    repaired = translated
                return idx, repaired
            except Exception as e:
                logger.warning(f"Para {idx} translation failed: {str(e)[:80]}")
                return idx, p

    tasks = [_translate_one_para(i, p) for i, p in enumerate(paragraphs)]
    results = await asyncio.gather(*tasks)
    translated = [t for _, t in sorted(results, key=lambda x: x[0])]

    full = "\n\n".join(translated)

    if add_frontmatter:
        rid = hashlib.md5(f"{input_path}{datetime.now(UTC)}".encode()).hexdigest()[:12]
        header = (
            f"---\nsource_lang: {src}\ntarget_lang: {tgt}\n"
            f"original_file: {input_path.name}\nprocessor: \"OL\"\n"
            f"version: \"0.2.6\"\n"
            f"translated_at: {datetime.now(UTC).isoformat()}\n"
            f"request_id: {rid}\n---\n"
        )
        full = header + full

    output_file = output_path / input_path.name
    output_file.write_text(full, encoding="utf-8")
    return str(output_file)


# ---------------------------------------------------------------------------
# translate-md command (plain function, registered by ol_cli.py)
# ---------------------------------------------------------------------------

def translate_md(
    input: str = typer.Argument(..., help="Input markdown file path"),
    output_dir: str = typer.Option("--output-dir", "-o", help="Output directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    source_lang: str | None = typer.Option(
        None, "--source-lang", "-s", help="Source language (overrides config)"
    ),
    target_lang: str | None = typer.Option(
        None, "--target-lang", "-t", help="Target language (overrides config)"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output JSON instead of human-readable text"
    ),
    add_frontmatter: bool = typer.Option(
        True, "--frontmatter/--no-frontmatter", help="Add YAML frontmatter to output file"
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Skip the .omni_cache/ cache check (force a fresh translation)"
    ),
    clear_cache: bool = typer.Option(
        False, "--clear-cache", help="Remove all cached OL outputs and exit"
    ),
    glossary: str | None = typer.Option(
        None, "--glossary",
        help="Path to a glossary JSON/YAML file. When provided, the top-5 "
             "matching source terms are injected into the translation prompt "
             "to bias the LLM toward your terminology.",
    ),
    no_glossary: bool = typer.Option(
        False, "--no-glossary",
        help="Skip glossary injection even if --glossary is set or "
             "the config declares one.",
    ),
    no_restoration: bool = typer.Option(
        False, "--no-restoration",
        help="Skip the post-translate placeholder restoration step (A12.4). "
             "The CLI will not ask the LLM to recover any {{_OL_*_*}} "
             "placeholders the translator stripped.",
    ),
    chunk_by_paragraph: bool = typer.Option(
        False, "--chunk-by-paragraph",
        help="Split the input by blank-line paragraph boundaries and translate "
             "each paragraph as a separate LLM call, then stitch the results "
             "back together. Improves quality for literary text with hard line "
             "breaks (e.g., Project Gutenberg); the whole-document path can "
             "leave English remnants in the output for such inputs. Slower "
             "(one LLM call per paragraph).",
    ),
    glossary_max_terms: int = typer.Option(
        5, "--glossary-max-terms",
        min=1,
        help="How many top glossary terms to inject per trans-unit "
             "(default 5). Applies to --glossary / config glossary "
             "injection; ignored when --no-glossary is set.",
    ),
    log_format: str | None = typer.Option(
        None, "--log-format",
        help="Log output format: 'console' (default) or 'json'. "
             "Also via OMNI_LOG_FORMAT env var. JSON includes request_id, "
             "timestamp, level, module fields.",
    ),
) -> int:
    try:
        if log_format:
            os.environ["OMNI_LOG_FORMAT"] = log_format
        input_path = validate_input_file(input)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)


    if not output_dir:
        typer.echo("Error: --output-dir is required", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    try:
        output_path = ensure_output_dir(output_dir)
    except Exception as e:  # expected — CLI error, echoes then exits
        typer.echo(f"Error: Cannot create output directory: {e}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    precheck_api_keys(config)

    logger.info(f"Command: translate_md {input}")
    try:
        if clear_cache:
            n = _clear_ol_cache()
            logger.info(f"Cleared {n} cached file(s) from {_cache_root()}")
            typer.echo(f"Cleared {n} cached file(s) from {_cache_root()}")
            raise typer.Exit(code=ExitCode.SUCCESS)

        src = source_lang or "en"
        tgt = target_lang or "zh"
        cfg_glossary: dict[str, Any] | None = None

        if config:
            from ol_config.loader import load_config

            cfg, cfg_glossary = load_config(config)
            src = src or cfg.source_lang
            tgt = tgt or cfg.target_lang
            _enforce_file_size(input_path, cfg.max_input_size_mb)
            typer.echo(f"Using config: {cfg.project_id} ({src} -> {tgt})")
        else:
            src = src or "en"
            tgt = tgt or "zh"

        # A12.1: --glossary CLI flag (PR12). When set, it takes precedence
        # over any glossary path declared in the config file.
        loaded_glossary = _load_glossary_or_none(glossary, tgt_lang=tgt)
        # A12.5: --no-glossary overrides both --glossary and the config glossary.
        if no_glossary:
            loaded_glossary = None
        _apply_glossary_max_terms(loaded_glossary, glossary_max_terms)
        # Wave 4 (L-C1): glossary and restoration_enabled are now passed
        # directly as function arguments (not module-level globals).

        # A6: cache check before any expensive LLM work.
        if _check_cache(
            input_path, output_path, config, no_cache=no_cache,
            add_frontmatter=add_frontmatter,
            no_restoration=no_restoration,
            no_glossary=no_glossary,
            glossary=glossary,
            glossary_max_terms=glossary_max_terms,
            src_lang=src,
            tgt_lang=tgt,
        ):
            cached_output = output_path / input_path.name
            if json_output:
                output_json(True, str(input_path), str(cached_output), src, tgt)
            else:
                typer.echo(
                    f"Translated (cached): {input_path.name} -> {cached_output} ({src} -> {tgt})"
                )
            logger.info(f"Completed: translate_md {input} (cache hit)")
            raise typer.Exit(code=ExitCode.SUCCESS)

        if chunk_by_paragraph:
            output_file = asyncio.run(
                _translate_md_by_paragraph(
                    input_path, output_path, config, src, tgt, add_frontmatter,
                    glossary=loaded_glossary,
                ),
            )
        else:
            output_file = asyncio.run(
                _translate_md_async(
                    input_path, output_path, config, src, tgt, add_frontmatter,
                    glossary=loaded_glossary,
                    restoration_enabled=not no_restoration,
                ),
            )

        # A12.4: post-translate restoration runs after the async pipeline
        # so pre-existing test fakes for ``_translate_md_async`` still
        # observe this step.
        if not no_restoration:
            try:
                _original_text = input_path.read_text(encoding="utf-8")
            except OSError:
                _original_text = ""
            _restoration_pool = _build_restoration_pool(config)
            _apply_post_translate_restoration(
                Path(output_file), _original_text, _restoration_pool,
            )

        # A6: cache the produced output so the next run is a cache hit.
        _write_cache(
            input_path, output_path, config, no_cache=no_cache,
            add_frontmatter=add_frontmatter,
            no_restoration=no_restoration,
            no_glossary=no_glossary,
            glossary=glossary,
            glossary_max_terms=glossary_max_terms,
            src_lang=src,
            tgt_lang=tgt,
        )

        if json_output:
            actual_output = output_path / input_path.name
            output_json(True, str(input_path), str(actual_output), src, tgt)
        else:
            typer.echo(f"Translated: {input_path.name} -> {output_file} ({src} -> {tgt})")
        logger.info(f"Completed: translate_md {input}")
        raise typer.Exit(code=ExitCode.SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            output_json(False, str(input_path), error=str(e))
        else:
            typer.echo(f"Pipeline error: {e}", err=True)
        logger.error(f"Failed: translate_md {input} - {e}")
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)
