"""translate-xliff CLI command and XLIFF translation helpers."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import typer

if TYPE_CHECKING:
    from ol_lqa.judge import JudgeService
    from ol_pool.router import ModelPool
    from ol_retry.retry import RetryManager
    from ol_terminology import Glossary

from cli.cache import (
    _cache_key,
    _cache_root,
    _check_cache,
    _clear_ol_cache,
    _write_cache,
)
from cli.frontmatter import (
    _build_xliff_header_note,
    _extract_opp_metadata,
    _extract_request_id,
    _get_ol_version,
    _inject_xliff_header,
    _validate_lang_code,
)
from cli.translate_md import (
    _UnitTranslationResult,
    _apply_glossary_max_terms,
    _apply_post_translate_restoration,
    _build_restoration_pool,
    _consume_glossary_for_translation,
    _consume_glossary_max_terms_for_translation,
    _consume_restoration_for_translation,
    _load_env_for_cli,
    _load_glossary_or_none,
    _set_glossary_for_next_translation,
    _set_glossary_max_terms_for_next_translation,
    _set_restoration_for_next_translation,
    _translate_one_unit,
    _translate_units_concurrent,
)
from cli._shared import (
    ExitCode,
    _enforce_file_size,
    ensure_output_dir,
    output_json,
    validate_input_file,
)
from ol_logging.core import get_logger
from ol_xliff.pipeline import XLIFFRepairPipeline

logger = get_logger("cli")


async def _translate_xliff_pipelined(
    units: list,
    pool: 'ModelPool',
    judge: 'JudgeService | None',
    retry_mgr: 'RetryManager | None',
    src_lang: str,
    tgt_lang: str,
    sem: asyncio.Semaphore,
    repair_pipeline: 'XLIFFRepairPipeline | None' = None,
    glossary: 'Glossary | None' = None,
) -> list[_UnitTranslationResult]:
    """A4: pipelined translate + LQA judge.

    Splits each unit's work into two phases:

    1. **Translate phase** — calls ``pool.translate()`` while holding ``sem``.
       This is the LLM call that actually needs to be concurrency-bounded.

    2. **Judge phase** — calls ``judge.judge()`` for the translated unit,
       WITHOUT holding ``sem``. The judge LLM call can overlap with the
       next unit's translate, so the sem is freed up earlier.

    The two phases are gathered with ``asyncio.gather``: the translate
    phase for all units fires first, then the judge phase for all units
    fires (in parallel with each other, and the test demonstrates overlap
    with the last batch of translates). See slim-pipeline-hardening.md §A4
    for the speedup rationale.

    **Retry decisions are batched at the end**, not interleaved. If a
    unit's first-pass score is below the retry threshold, the re-translate
    happens AFTER the first-pass judge batch completes. This is a
    deliberate ordering change from the A2 helper (where retries happen
    inline within ``RetryManager.execute_with_retry``).

    Falls back to ``_translate_units_concurrent`` if either ``judge`` or
    ``retry_mgr`` is None (i.e. LQA disabled); in that case there is no
    judge phase to pipeline and the A2 helper is functionally equivalent.

    Returns one :class:`_UnitTranslationResult` per input unit, in input
    order. Per-unit transport errors and exceptions are caught inside
    the helpers and reflected in the result's ``status``/``warning``
    fields; this coroutine itself does not raise.
    """
    from ol_xliff.pipeline import XLIFFRepairPipeline

    if repair_pipeline is None:
        repair_pipeline = XLIFFRepairPipeline()

    # Without LQA there is nothing to pipeline; delegate to A2 helper.
    if judge is None or retry_mgr is None:
        return await _translate_units_concurrent(
            units, pool, judge, retry_mgr,
            src_lang, tgt_lang,
            sem=sem, repair_pipeline=repair_pipeline, glossary=glossary,
        )

    threshold = retry_mgr._pass_threshold
    n = len(units)

    # Per-unit shared state — filled by the per-unit pipeline task.
    first_pass_translations: list[str | None] = [None] * n
    first_pass_results: list[Any] = [None] * n
    first_pass_translate_excs: list[BaseException | None] = [None] * n
    first_pass_judge_excs: list[BaseException | None] = [None] * n

    # Progress tracking (shared across concurrent unit_pipeline tasks).
    _fp_count = [0]
    _fp_lock = asyncio.Lock()
    PROGRESS_LOG_INTERVAL = 50

    async def _log_progress(done: int, total: int, phase: str) -> None:
        if done % PROGRESS_LOG_INTERVAL == 0 or done == total:
            pct = done / total * 100
            logger.info(
                f"XLIFF {phase}: {done}/{total} ({pct:.0f}%)"
            )
            for h in logger.handlers:
                h.flush()

    async def unit_pipeline(idx: int, unit: TranslationUnit) -> None:
        """Translate then judge, both for one unit. Translate holds ``sem``;
        judge runs WITHOUT the sem so it can overlap with the next unit's
        translate (this is the A4 pipelining speedup)."""
        try:
            async with sem:
                first_pass_translations[idx] = await pool.translate(
                    unit.source_text, src_lang, tgt_lang,
                    context=None, glossary=glossary,
                )
        except Exception as exc:
            first_pass_translate_excs[idx] = exc
            async with _fp_lock:
                _fp_count[0] += 1
                await _log_progress(_fp_count[0], n, "first-pass")
            return
        try:
            first_pass_results[idx] = await judge.judge(
                unit.source_text, first_pass_translations[idx], unit.unit_id,
                source_lang=src_lang, target_lang=tgt_lang,
            )
        except Exception as exc:
            first_pass_judge_excs[idx] = exc
        async with _fp_lock:
            _fp_count[0] += 1
            await _log_progress(_fp_count[0], n, "first-pass")

    # === Phase 1+2 (interleaved): translate phase holds sem, judge phase
    # runs after translate returns, freeing the sem. The next unit's
    # translate can start as soon as the previous translate returns, so
    # judges overlap with the next unit's translate. ===
    await asyncio.gather(*[unit_pipeline(i, u) for i, u in enumerate(units)])

    # === Phase 3: identify retry units from first-pass scores ===
    needs_retry: list[int] = []
    for i, unit in enumerate(units):
        if first_pass_translate_excs[i] is not None:
            continue
        if first_pass_judge_excs[i] is not None:
            continue
        result = first_pass_results[i]
        score = getattr(result, "judge_overall_score", 0.0)
        if score < threshold:
            needs_retry.append(i)

    # === Phase 4: re-translate + re-judge retry units AT THE END ===
    # Retries are scheduled AFTER all first-pass translates are done.
    # This is the A4 ordering guarantee: "re-translate happens at the
    # end (not while other units are still translating)."
    retry_translations: list[str | None] = [None] * n
    retry_results: list[Any] = [None] * n

    if needs_retry:
        _rt_count = [0]
        _rt_lock = asyncio.Lock()
        retry_n = len(needs_retry)
        logger.info(f"Retry phase: re-translating {retry_n} low-scoring units")

        async def _retry_unit_pipeline(idx: int) -> None:
            try:
                async with sem:
                    retry_translations[idx] = await pool.translate(
                        units[idx].source_text, src_lang, tgt_lang,
                        context=None, glossary=glossary,
                    )
            except Exception as exc:
                return
            try:
                retry_results[idx] = await judge.judge(
                    units[idx].source_text, retry_translations[idx],
                    units[idx].unit_id,
                    source_lang=src_lang, target_lang=tgt_lang,
                )
            except Exception as exc:
                retry_results[idx] = None
            async with _rt_lock:
                _rt_count[0] += 1
                await _log_progress(_rt_count[0], retry_n, "retry")

        await asyncio.gather(*[_retry_unit_pipeline(i) for i in needs_retry])

    # === Phase 5: build final results with repair and warnings ===
    final: list[_UnitTranslationResult] = []
    for i, unit in enumerate(units):
        if first_pass_translate_excs[i] is not None:
            exc = first_pass_translate_excs[i]
            warning = (
                f"OL_WARN: TRANSLATION_FAILED "
                f"({type(exc).__name__}: {str(exc)[:200]})"
            )
            translated = unit.source_text
            status = "transport_error"
            attempts = 1
            error_msg = f"{type(exc).__name__}: {str(exc)[:200]}"
        elif first_pass_judge_excs[i] is not None:
            exc = first_pass_judge_excs[i]
            warning = (
                f"OL_WARN: LQA_SKIPPED "
                f"({type(exc).__name__}: {str(exc)[:200]})"
            )
            translated = first_pass_translations[i] or unit.source_text
            status = "ok"
            attempts = 1
            error_msg = None
        else:
            first_translation = first_pass_translations[i]
            final_translation = first_translation
            attempts = 1
            warning = None
            if i in needs_retry and retry_results[i] is not None:
                # A retry translate was actually issued — bump attempts
                # to reflect the call count, regardless of whether the
                # retry produced a better score.
                attempts = 2
                first_score = first_pass_results[i].judge_overall_score
                retry_score = retry_results[i].judge_overall_score
                if retry_score > first_score:
                    final_translation = retry_translations[i]
                if retry_score < threshold:
                    warning = "OL_WARN: Low_Score"
            status = "ok"
            error_msg = None

        if unit.shield_map:
            from ol_buses.xliff_shield import restore_tags

            unshielded = restore_tags(final_translation, unit.shield_map)
            repaired, repair_warnings = repair_pipeline.repair(
                unshielded, unit.source_text, unit.shield_map,
            )
        else:
            repaired = final_translation
            repair_warnings = []

        final.append(_UnitTranslationResult(
            unit_id=unit.unit_id,
            translated=repaired,
            warning=warning,
            repair_warnings=repair_warnings,
            attempts=attempts,
            latency_ms=0.0,
            status=status,
            error=error_msg,
        ))

    return final


async def _translate_xliff_async(
    input_path: Path,
    output_path: Path,
    config_path: str | None,
    src_lang: str,
    tgt_lang: str,
) -> str:
    # A12.3: read the glossary from module state (set by the typer command
    # before asyncio.run). We intentionally keep this function's POSITIONAL
    # signature unchanged so the pre-existing test_ol_cache.py fakes
    # (which mock this function with a fixed 5-arg signature) still work.
    glossary = _consume_glossary_for_translation()
    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        import sys
        from pathlib import Path as _SeamPath
        _suite_root = _SeamPath(__file__).resolve().parents[3]
        if str(_suite_root) not in sys.path:
            sys.path.insert(0, str(_suite_root))
        from tests.test_e2e_pipeline_fixtures import _FakeModelPool
        # B1: Avoid importing ol_pool.router here — it transitively loads
        # litellm → pydantic → importlib.metadata.entry_points() which blocks
        # on filesystem I/O over slow mounts (e.g. WSL2 /mnt/ drives).
        pool = cast(object, _FakeModelPool())
    else:
        from ol_pool.router import ModelPool
        pool = ModelPool.get_instance(config_path) if config_path else ModelPool.get_instance()

    from ol_config.loader import load_config
    from ol_xliff.parser import XliffParser
    from ol_buses.xliff_bus import write_target_back, _ensure_target_tags
    from ol_core.dataclass import TranslationContext, ChannelType

    cfg, _ = load_config(config_path or os.environ.get("OL_CONFIG_PATH", "config/default.yaml"))
    src_lang = src_lang or cfg.source_lang
    tgt_lang = tgt_lang or cfg.target_lang

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
        logger.info(
            f"LQA enabled for XLIFF: threshold={cfg.lqa_threshold}, "
            f"max_retries={cfg.lqa_max_retries}"
        )

    parser = XliffParser()
    units = parser.parse(str(input_path))

    if len(units) == 0:
        raise RuntimeError("No translation units found in XLIFF file")

    repair_pipeline = XLIFFRepairPipeline()

    # Pydantic v2 silently drops unknown YAML fields, so getattr() with a
    # default is the safe read for an opt-in knob that has no schema entry.
    max_xliff_concurrent = getattr(cfg, "max_xliff_concurrent", 20) or 20
    if not isinstance(max_xliff_concurrent, int) or max_xliff_concurrent < 1:
        max_xliff_concurrent = 20
    logger.info(
        f"Translating XLIFF {input_path.name}: {len(units)} units, "
        f"max_xliff_concurrent={max_xliff_concurrent}, "
        f"lqa={'on' if judge is not None else 'off'}"
    )

    warnings_per_unit: dict[str, list[str]] = {}

    from ol_concurrency.scheduler import ConcurrencyLimiter
    limiter = ConcurrencyLimiter(max_xliff_concurrent=max_xliff_concurrent)
    # A4: prefer the pipelined helper when LQA is enabled. It overlaps the
    # judge phase with the next unit's translate, freeing the sem earlier
    # and saving ~judge_time per unit on the slim. With LQA disabled, the
    # pipelined helper delegates to _translate_units_concurrent (no-op).
    if judge is not None and retry_mgr is not None:
        results = await _translate_xliff_pipelined(
            units, pool, judge, retry_mgr,
            src_lang, tgt_lang,
            sem=limiter.xliff_semaphore,
            repair_pipeline=repair_pipeline,
            glossary=glossary,
        )
    else:
        results = await _translate_units_concurrent(
            units, pool, judge, retry_mgr,
            src_lang, tgt_lang,
            sem=limiter.xliff_semaphore,
            repair_pipeline=repair_pipeline,
            glossary=glossary,
        )

    for unit, r in zip(units, results):
        unit.target_text = r.translated
        if r.warning:
            warnings_per_unit.setdefault(r.unit_id, []).append(r.warning)
        if r.repair_warnings:
            # Repair warnings replace the per-unit list (pre-existing
            # contract relied on by warnings extraction downstream).
            warnings_per_unit[unit.unit_id] = r.repair_warnings

    logger.info(f"Translation complete: {len(units)} units")

    original_text = input_path.read_text(encoding="utf-8")
    original_text = _ensure_target_tags(original_text)

    ctx = TranslationContext(
        file_path=str(input_path),
        channel_type=ChannelType.XLIFF,
        original_full_text=original_text,
        units=units,
        glossary={},
        config={},
        warnings_per_unit=warnings_per_unit,
    )
    output_file = str(output_path / input_path.name)
    write_target_back(ctx, output_file, warnings_per_unit=warnings_per_unit)

    output_path_obj = Path(output_file)
    translated_text = output_path_obj.read_text(encoding="utf-8")
    # 2026-06-18 round 16 Phase B2: propagate request_id from OPP.
    rid = _extract_request_id(input_path)
    header_note = _build_xliff_header_note(src_lang, tgt_lang, request_id=rid)
    translated_text = _inject_xliff_header(translated_text, header_note)
    output_path_obj.write_text(translated_text, encoding="utf-8")

    return output_file


# ---------------------------------------------------------------------------
# translate-xliff command (plain function, registered by ol_cli.py)
# ---------------------------------------------------------------------------

def translate_xliff(
    input: str = typer.Argument(..., help="Input XLIFF file path"),
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
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Skip the .omni_cache/ cache check (force a fresh translation)"
    ),
    clear_cache: bool = typer.Option(
        False, "--clear-cache", help="Remove all cached OL outputs and exit"
    ),
    glossary: str | None = typer.Option(
        None, "--glossary",
        help="Path to a glossary JSON/YAML file. Top-5 matching source terms "
             "are injected into each trans-unit's translation prompt.",
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
    except Exception as e:
        typer.echo(f"Error: Cannot create output directory: {e}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    logger.info(f"Command: translate_xliff {input}")
    try:
        if clear_cache:
            n = _clear_ol_cache()
            logger.info(f"Cleared {n} cached file(s) from {_cache_root()}")
            typer.echo(f"Cleared {n} cached file(s) from {_cache_root()}")
            raise typer.Exit(code=ExitCode.SUCCESS)

        src_lang = source_lang
        tgt_lang = target_lang
        config_path = config

        if config:
            from ol_config.loader import load_config

            cfg, _ = load_config(config)
            src_lang = src_lang or cfg.source_lang
            tgt_lang = tgt_lang or cfg.target_lang
            _enforce_file_size(input_path, cfg.max_input_size_mb)
            typer.echo(f"Using config: {cfg.project_id} ({src_lang} -> {tgt_lang})")
        else:
            src_lang = src_lang or "en"
            tgt_lang = tgt_lang or "zh"

        # A6: cache check before any expensive LLM work.
        if _check_cache(
            input_path, output_path, config_path, no_cache=no_cache,
            no_restoration=no_restoration,
            no_glossary=no_glossary,
            glossary=glossary,
            glossary_max_terms=glossary_max_terms,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
        ):
            cached_output = output_path / input_path.name
            if json_output:
                output_json(True, str(input_path), str(cached_output), src_lang, tgt_lang)
            else:
                typer.echo(
                    f"Translated (cached): {input_path.name} -> {cached_output} ({src_lang} -> {tgt_lang})"
                )
            logger.info(f"Completed: translate_xliff {input} (cache hit)")
            raise typer.Exit(code=ExitCode.SUCCESS)

        # A12.1: --glossary CLI flag (PR12). Same precedence as translate-md.
        loaded_glossary = _load_glossary_or_none(glossary, tgt_lang=tgt_lang)
        if no_glossary:
            loaded_glossary = None
        _apply_glossary_max_terms(loaded_glossary, glossary_max_terms)
        _set_glossary_for_next_translation(loaded_glossary)
        _set_restoration_for_next_translation(enabled=not no_restoration)

        # Load .env to get MINIMAX_API_KEY etc. before calling LLM
        _load_env_for_cli()

        asyncio.run(_translate_xliff_async(
            Path(input), output_path, config_path, src_lang, tgt_lang,
        ))

        # A12.4: post-translate restoration runs after asyncio.run so
        # test fakes for ``_translate_xliff_async`` still observe it.
        if not no_restoration:
            try:
                _original_text = input_path.read_text(encoding="utf-8")
            except OSError:
                _original_text = ""
            _restoration_pool = _build_restoration_pool(config_path)
            _apply_post_translate_restoration(
                output_path / Path(input).name, _original_text, _restoration_pool,
            )

        # A6: cache the produced output so the next run is a cache hit.
        _write_cache(
            input_path, output_path, config_path, no_cache=no_cache,
            no_restoration=no_restoration,
            no_glossary=no_glossary,
            glossary=glossary,
            glossary_max_terms=glossary_max_terms,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
        )

        output_file = output_path / Path(input).name
        if json_output:
            output_json(True, str(input_path), str(output_file), src_lang, tgt_lang)
        else:
            typer.echo(f"Translated: {input_path.name} -> {output_file} ({src_lang} -> {tgt_lang})")
        logger.info(f"Completed: translate_xliff {input}")
        raise typer.Exit(code=ExitCode.SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            output_json(False, str(input_path), error=str(e))
        else:
            typer.echo(f"Pipeline error: {e}", err=True)
        logger.error(f"Failed: translate_xliff {input} - {e}")
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)
