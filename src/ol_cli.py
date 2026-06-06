"""Omni-Localizer CLI - Typer-based command line interface."""

import asyncio
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any

# ========== OL Frontmatter Support ==========
from datetime import UTC, datetime
from pathlib import Path

import typer

from ol_logging.core import get_logger, init_logger
from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_xliff.pipeline import XLIFFRepairPipeline


def _escape_yaml_value(value: str) -> str:
    """Escape special characters in YAML string values to prevent injection."""
    if any(c in value for c in ":#\n"):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _validate_lang_code(code: str) -> str:
    """Validate ISO 639-1 language code."""
    if not re.match(r"^[a-z]{2}(-[A-Z]{2})?$", code):
        raise ValueError(f"Invalid language code: {code}")
    return code


def _escape_xml(value: str) -> str:
    """Escape special characters in XML using single-pass character-by-character approach.

    This prevents double-encoding issues that occur with naive sequential .replace() calls.
    For example: '&lt;' would become '&amp;lt;' with sequential replacement.
    """
    result = []
    for c in value:
        if c == "&":
            result.append("&amp;")
        elif c == "<":
            result.append("&lt;")
        elif c == ">":
            result.append("&gt;")
        elif c == '"':
            result.append("&quot;")
        elif c == "'":
            result.append("&apos;")
        else:
            result.append(c)
    return "".join(result)


def _generate_frontmatter(
    source_lang: str,
    target_lang: str,
    original_filename: str,
    ol_version: str | None = None,
) -> str:
    if ol_version is None:
        ol_version = _get_ol_version()
    """Generate YAML frontmatter header with translation metadata.

    Args:
        source_lang: Source language code (ISO 639-1)
        target_lang: Target language code (ISO 639-1)
        original_filename: Original input filename
        ol_version: OL version number

    Returns:
        YAML frontmatter string with leading and trailing ---

    Raises:
        ValueError: If language codes are invalid

    """
    # Validate inputs to prevent injection
    source_lang = _validate_lang_code(source_lang)
    target_lang = _validate_lang_code(target_lang)
    escaped_filename = _escape_yaml_value(original_filename)

    timestamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    frontmatter_lines = [
        "---",
        f"source_lang: {source_lang}",
        f"target_lang: {target_lang}",
        f"original_file: {escaped_filename}",
        'processor: "OL"',
        f'version: "{ol_version}"',
        f"translated_at: {timestamp}",
        "---",
        "",
    ]

    return "\n".join(frontmatter_lines)


def _generate_skip_frontmatter(
    source_lang: str,
    target_lang: str,
    original_filename: str,
    ol_version: str | None = None,
    detected_source_lang: str | None = None,
) -> str:
    if ol_version is None:
        ol_version = _get_ol_version()
    source_lang = _validate_lang_code(source_lang)
    target_lang = _validate_lang_code(target_lang)
    escaped_filename = _escape_yaml_value(original_filename)

    timestamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    frontmatter_lines = [
        "---",
        f"source_lang: {source_lang}",
        f"target_lang: {target_lang}",
        f"original_file: {escaped_filename}",
        'processor: "OL"',
        f'version: "{ol_version}"',
        f"translated_at: {timestamp}",
        "skipped: true",
        'skip_reason: "already_in_target_language"',
    ]
    if detected_source_lang:
        frontmatter_lines.append(f"detected_source_lang: {detected_source_lang}")

    frontmatter_lines.append("---")
    frontmatter_lines.append("")

    return "\n".join(frontmatter_lines)


def _get_ol_version() -> str:
    """Get OL version from module-level __version__."""
    # __version__ is defined at line 16 of ol_cli.py
    return __version__


def _build_xliff_header_note(src_lang: str, tgt_lang: str) -> str:
    """Build XLIFF-compliant header note element."""
    validated_src = _validate_lang_code(src_lang)
    validated_tgt = _validate_lang_code(tgt_lang)
    note_text = f"Translated from {validated_src} to {validated_tgt} by OL"
    return f'<header>\n    <note from="OL">{_escape_xml(note_text)}</note>\n  </header>'


def _inject_xliff_header(repaired: str, header_note: str) -> str:
    """Inject header note into XLIFF output at correct position."""
    # Insert header after <xliff ...> opening tag, before <file> element
    if "<file" in repaired:
        return repaired.replace("<file", header_note + "\n  <file", 1)
    return repaired  # No <file> element found, skip header injection


__version__ = "0.2.6"

# Initialize logging
init_logger()
logger = get_logger("cli")

# Global interrupt flag for graceful shutdown
_interrupted = False


def _sigint_handler(signum, frame):
    global _interrupted
    _interrupted = True
    typer.echo("\nReceived Ctrl+C - finishing in-flight files, no new starts...")


app = typer.Typer(
    name="ol",
    help="Omni-Localizer: AI-native localization pipeline with automated quality control.",
    add_completion=False,
)


class ExitCode:
    SUCCESS = 0
    PIPELINE_ERROR = 1
    CLI_USAGE_ERROR = 2
    INTERRUPTED = 3


def _setup_signal_handler():
    signal.signal(signal.SIGINT, _sigint_handler)


def is_interrupted() -> bool:
    return _interrupted


def validate_input_file(path: str) -> Path:
    file_path = Path(path)
    if not file_path.exists():
        raise typer.BadParameter(f"Input file not found: {path}")
    if not file_path.is_file():
        raise typer.BadParameter(f"Input is not a file: {path}")
    return file_path


def ensure_output_dir(path: str) -> Path:
    output_path = Path(path)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


def output_json(
    success: bool,
    input_file: str,
    output_file: str | None = None,
    source_lang: str | None = None,
    target_lang: str | None = None,
    error: str | None = None,
) -> None:
    """Output structured JSON to stdout."""
    import json

    result = {
        "success": success,
        "input_file": input_file,
    }
    if output_file:
        result["output_file"] = str(output_file)
    if source_lang:
        result["source_lang"] = source_lang
    if target_lang:
        result["target_lang"] = target_lang
    if error:
        result["error"] = error
    typer.echo(json.dumps(result, ensure_ascii=False))


def _apply_fake_llm_seam() -> None:
    """Test seam: when OMNI_TEST_FAKE_LLM=1, also stub ``span_aligner``.

    The OMNI_TEST_FAKE_LLM seam short-circuits the LLM call
    (``ModelPool.translate``) but does not cover the post-translation
    MD repair pipeline. Level 2 of that pipeline imports
    ``span_aligner.SpanProjector``, which constructs a HF transformer
    (``bert-base-multilingual-cased``) — that fails in hermetic CI
    (no API keys, no HF network).

    This helper installs a lightweight ``sys.modules['span_aligner']``
    stub whose ``SpanProjector.project`` is identity and ``align`` /
    ``align_spans`` return ``[]``. Idempotent: re-running it is a
    no-op (we mark the stub with a sentinel attribute).

    See ``docs/T14_LIMITATION.md`` for the full T14 history.
    """
    import sys as _seam_sys
    from unittest.mock import MagicMock as _SeamMagicMock

    existing = _seam_sys.modules.get("span_aligner")
    if existing is not None and getattr(existing, "_omni_fake_seam", False):
        return

    _span_mod = _SeamMagicMock()
    _span_mod.SpanProjector = lambda *a, **k: _SeamMagicMock(
        project=lambda text, *a, **k: text,
        align=lambda *a, **k: [],
    )
    _span_mod.align_spans = lambda *a, **k: []
    _span_mod._omni_fake_seam = True
    _seam_sys.modules["span_aligner"] = _span_mod


async def _translate_md_async(
    input_path: Path,
    output_path: Path,
    config_path: str | None,
    src_lang: str,
    tgt_lang: str,
    add_frontmatter: bool = True,
) -> str:
    import os
    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        import sys
        from pathlib import Path as _SeamPath
        _suite_root = _SeamPath(__file__).resolve().parents[2]
        if str(_suite_root) not in sys.path:
            sys.path.insert(0, str(_suite_root))
        from tests.test_e2e_pipeline_fixtures import _FakeModelPool
        pool = _FakeModelPool()
        _apply_fake_llm_seam()
    else:
        from ol_pool.router import ModelPool
        pool = ModelPool.get_instance(config_path) if config_path else ModelPool.get_instance()

    from ol_config.loader import load_config
    cfg, _ = load_config(config_path or "config/default.yaml")
    src_lang = src_lang or cfg.source_lang
    tgt_lang = tgt_lang or cfg.target_lang

    original_text = input_path.read_text(encoding="utf-8")
    shielded, shield_map = shield_markdown(original_text)

    if cfg.enable_lqa:
        from ol_lqa.judge import JudgeService
        from ol_retry.retry import RetryManager
        judge = JudgeService(pass_threshold=cfg.lqa_threshold, model_pool=pool)
        retry_mgr = RetryManager(
            max_retries=cfg.lqa_max_retries,
            pass_threshold=cfg.lqa_threshold,
        )

        async def translate_fn():
            return await pool.translate(shielded, src_lang, tgt_lang)

        async def judge_fn(source, translation, unit_id):
            return judge.judge(
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
            translated = await pool.translate(shielded, src_lang, tgt_lang)
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

        frontmatter = _generate_frontmatter(
            source_lang=safe_src_lang,
            target_lang=safe_tgt_lang,
            original_filename=input_path.name,
            ol_version=_get_ol_version(),
        )
        output_content = frontmatter + repaired
    else:
        output_content = repaired

    output_file = output_path / input_path.name
    output_file.write_text(output_content, encoding="utf-8")

    return str(output_file)


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
    import os
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
    import os
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
    except Exception:
        pass


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
    unit: Any,
    pool: Any,
    judge: Any,
    retry_mgr: Any,
    src_lang: str,
    tgt_lang: str,
    sem: asyncio.Semaphore,
    repair_pipeline: Any,
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
                        unit.source_text, src_lang, tgt_lang, context=None,
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
                    unit.source_text, src_lang, tgt_lang, context=None,
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


async def _translate_xliff_pipelined(
    units: list,
    pool: Any,
    judge: Any,
    retry_mgr: Any,
    src_lang: str,
    tgt_lang: str,
    sem: asyncio.Semaphore,
    repair_pipeline: Any = None,
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
            sem=sem, repair_pipeline=repair_pipeline,
        )

    threshold = retry_mgr._pass_threshold
    n = len(units)

    # Per-unit shared state — filled by the per-unit pipeline task.
    first_pass_translations: list[str | None] = [None] * n
    first_pass_results: list[Any] = [None] * n
    first_pass_translate_excs: list[BaseException | None] = [None] * n
    first_pass_judge_excs: list[BaseException | None] = [None] * n

    async def unit_pipeline(idx: int, unit: Any) -> None:
        """Translate then judge, both for one unit. Translate holds ``sem``;
        judge runs WITHOUT the sem so it can overlap with the next unit's
        translate (this is the A4 pipelining speedup)."""
        try:
            async with sem:
                first_pass_translations[idx] = await pool.translate(
                    unit.source_text, src_lang, tgt_lang, context=None,
                )
        except BaseException as exc:  # noqa: BLE001 — broad on purpose
            first_pass_translate_excs[idx] = exc
            return
        try:
            first_pass_results[idx] = await judge.judge(
                unit.source_text, first_pass_translations[idx], unit.unit_id,
                source_lang=src_lang, target_lang=tgt_lang,
            )
        except BaseException as exc:  # noqa: BLE001
            first_pass_judge_excs[idx] = exc

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
        async def _retry_unit_pipeline(idx: int) -> None:
            try:
                async with sem:
                    retry_translations[idx] = await pool.translate(
                        units[idx].source_text, src_lang, tgt_lang,
                        context=None,
                    )
            except BaseException as exc:  # noqa: BLE001
                return
            try:
                retry_results[idx] = await judge.judge(
                    units[idx].source_text, retry_translations[idx],
                    units[idx].unit_id,
                    source_lang=src_lang, target_lang=tgt_lang,
                )
            except BaseException as exc:  # noqa: BLE001
                retry_results[idx] = None

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


async def _translate_units_concurrent(
    units: list,
    pool: Any,
    judge: Any,
    retry_mgr: Any,
    src_lang: str,
    tgt_lang: str,
    sem: asyncio.Semaphore,
    repair_pipeline: Any = None,
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

    tasks = [
        asyncio.create_task(
            _translate_one_unit(
                u, pool, judge, retry_mgr,
                src_lang, tgt_lang, sem, repair_pipeline,
            )
        )
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


async def _translate_xliff_async(
    input_path: Path,
    output_path: Path,
    config_path: str | None,
    src_lang: str,
    tgt_lang: str,
) -> str:
    import os
    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        import sys
        from pathlib import Path as _SeamPath
        _suite_root = _SeamPath(__file__).resolve().parents[2]
        if str(_suite_root) not in sys.path:
            sys.path.insert(0, str(_suite_root))
        from tests.test_e2e_pipeline_fixtures import _FakeModelPool
        pool = _FakeModelPool()
        _apply_fake_llm_seam()
    else:
        from ol_pool.router import ModelPool
        pool = ModelPool.get_instance(
            config_path if config_path else os.environ.get("OL_CONFIG_PATH", "config/default.yaml")
        )

    from ol_xliff.parser import XliffParser
    from ol_buses.xliff_bus import write_target_back, _ensure_target_tags
    from ol_core.dataclass import TranslationContext, ChannelType

    from ol_config.loader import load_config
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
        )
    else:
        results = await _translate_units_concurrent(
            units, pool, judge, retry_mgr,
            src_lang, tgt_lang,
            sem=limiter.xliff_semaphore,
            repair_pipeline=repair_pipeline,
        )

    for unit, r in zip(units, results):
        unit.target_text = r.translated
        if r.warning:
            warnings_per_unit.setdefault(r.unit_id, []).append(r.warning)
        if r.repair_warnings:
            # Repair warnings replace the per-unit list (pre-existing
            # contract relied on by warnings extraction downstream).
            warnings_per_unit[unit.unit_id] = r.repair_warnings

    logger.debug(f"Translated {len(units)} units")

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
    header_note = _build_xliff_header_note(src_lang, tgt_lang)
    translated_text = _inject_xliff_header(translated_text, header_note)
    output_path_obj.write_text(translated_text, encoding="utf-8")

    return output_file


@app.command()
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
) -> int:
    try:
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

    logger.info(f"Command: translate_md {input}")
    try:
        src = source_lang or "en"
        tgt = target_lang or "zh"

        if config:
            from ol_config.loader import load_config

            cfg, glossary = load_config(config)
            src = src or cfg.source_lang
            tgt = tgt or cfg.target_lang
            typer.echo(f"Using config: {cfg.project_id} ({src} -> {tgt})")
        else:
            src = src or "en"
            tgt = tgt or "zh"

        output_file = asyncio.run(
            _translate_md_async(input_path, output_path, config, src, tgt, add_frontmatter),
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


async def _translate_batch_async(
    directory: Path,
    output_dir: Path,
    config_path: str | None,
    src_lang: str,
    tgt_lang: str,
    glossary: dict[str, Any] | None = None,
    max_concurrent: int = 5,
    add_frontmatter: bool = True,
    detect_language: bool = True,
) -> tuple[int, int]:
    import time

    from ol_batch.config import BatchConfig
    from ol_batch.discovery import discover_files, validate_directory
    from ol_batch.processor import BatchProcessor
    from ol_batch.progress import ProgressContext
    from ol_batch.summary import print_summary
    from ol_concurrency.scheduler import ConcurrencyLimiter
    from ol_pool.router import ModelPool

    if not validate_directory(directory):
        raise ValueError(f"Directory not found or is not a directory: {directory}")

    file_patterns = ["*.md", "*.xliff", "*.xlf"]
    files = discover_files(directory, file_patterns)

    if not files:
        typer.echo(f"No files found in {directory} matching {file_patterns}")
        return (0, 0)

    typer.echo(f"Found {len(files)} files to process")

    batch_config = BatchConfig(max_concurrent=max_concurrent)
    pool = ModelPool.get_instance(config_path) if config_path else ModelPool.get_instance()

    # POST_MORTEM OL-1: surface LQA knobs to the batch path.
    from ol_config.loader import load_config
    cfg, _ = load_config(config_path or "config/default.yaml")
    enable_lqa = getattr(cfg, "enable_lqa", False)
    lqa_threshold = getattr(cfg, "lqa_threshold", 7.0)
    lqa_max_retries = getattr(cfg, "lqa_max_retries", 2)

    limiter = ConcurrencyLimiter(max_translation=max_concurrent)
    processor = BatchProcessor(
        config=batch_config, model_pool=pool, limiter=limiter, glossary=glossary,
        enable_lqa=enable_lqa,
        lqa_threshold=lqa_threshold, lqa_max_retries=lqa_max_retries,
    )

    start_time = time.time()
    async with ProgressContext() as _:
        result = await processor.process_batch(
            files,
            output_dir,
            add_frontmatter=add_frontmatter,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            detect_language=detect_language,
            enable_lqa=enable_lqa,
            lqa_threshold=lqa_threshold,
            lqa_max_retries=lqa_max_retries,
        )

    duration = time.time() - start_time
    print_summary(result, duration)

    return (len(result.succeeded), len(result.failed))


@app.command()
def translate_batch(
    directory: str = typer.Argument(..., help="Input directory path"),
    output_dir: str | None = typer.Option(None, "--output-dir", "-o", help="Output directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    source_lang: str | None = typer.Option(
        None, "--source-lang", "-s", help="Source language (overrides config)"
    ),
    target_lang: str | None = typer.Option(
        None, "--target-lang", "-t", help="Target language (overrides config)"
    ),
    concurrency: int = typer.Option(5, "--concurrency", "-j", help="Max concurrent translations"),
    add_frontmatter: bool = typer.Option(
        True, "--frontmatter/--no-frontmatter", help="Add frontmatter to translated files"
    ),
    detect_language: bool = typer.Option(
        True,
        "--detect-language/--no-detect-language",
        help="Detect source language before translating",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output JSON instead of human-readable text"
    ),
) -> int:
    try:
        input_path = Path(directory)
        if not input_path.exists():
            raise typer.BadParameter(f"Directory not found: {directory}")
        if not input_path.is_dir():
            raise typer.BadParameter(f"Input is not a directory: {directory}")
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

    logger.info(f"Command: translate_batch {directory}")
    try:
        src = source_lang or "en"
        tgt = target_lang or "zh"

        if config:
            from ol_config.loader import load_config

            cfg, glossary = load_config(config)
            src = src or cfg.source_lang
            tgt = tgt or cfg.target_lang
            typer.echo(f"Using config: {cfg.project_id} ({src} -> {tgt})")
        else:
            src = src or "en"
            tgt = tgt or "zh"

        succeeded, failed = asyncio.run(
            _translate_batch_async(
                input_path,
                output_path,
                config,
                src,
                tgt,
                glossary,
                concurrency,
                add_frontmatter,
                detect_language,
            ),
        )

        if failed > 0:
            if json_output:
                output_json(False, directory, error=f"{failed} files failed")
            logger.info(f"Completed: translate_batch {directory}")
            raise typer.Exit(code=ExitCode.PIPELINE_ERROR)
        if json_output:
            output_json(True, directory, source_lang=src, target_lang=tgt)
        logger.info(f"Completed: translate_batch {directory}")
        raise typer.Exit(code=ExitCode.SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            output_json(False, directory, error=str(e))
        else:
            typer.echo(f"Pipeline error: {e}", err=True)
        logger.error(f"Failed: translate_batch {directory} - {e}")
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)


@app.command()
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
) -> int:
    try:
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
        src_lang = source_lang
        tgt_lang = target_lang
        config_path = config

        if config:
            from ol_config.loader import load_config

            cfg, _ = load_config(config)
            src_lang = src_lang or cfg.source_lang
            tgt_lang = tgt_lang or cfg.target_lang
            typer.echo(f"Using config: {cfg.project_id} ({src_lang} -> {tgt_lang})")
        else:
            src_lang = src_lang or "en"
            tgt_lang = tgt_lang or "zh"

        # Load .env to get MINIMAX_API_KEY etc. before calling LLM
        _load_env_for_cli()

        asyncio.run(_translate_xliff_async(Path(input), output_path, config_path, src_lang, tgt_lang))

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


@app.command()
def extract_warnings(
    input: str = typer.Argument(..., help="Input file path (MD or XLIFF)"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path"),
) -> int:
    try:
        input_path = validate_input_file(input)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e.message}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)

    logger.info(f"Command: extract_warnings {input}")
    try:
        content = input_path.read_text(encoding="utf-8")
        warnings = []
        import re

        md_warn_pattern = re.compile(r"<!--\s*OL_WARN:\s*([^>]+)\s*-->")
        for match in md_warn_pattern.finditer(content):
            warnings.append(f"MD: {match.group(0)}")

        xliff_warn_pattern = re.compile(r'<note\s+from="OL"[^>]*>([^<]+)</note>')
        for match in xliff_warn_pattern.finditer(content):
            warnings.append(f"XLIFF: {match.group(0)}")

        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_content = "\n".join(warnings) if warnings else "# No warnings found"
            output_path.write_text(output_content, encoding="utf-8")
            typer.echo(f"Extracted {len(warnings)} warnings to: {output}")
        elif warnings:
            typer.echo(f"Found {len(warnings)} warnings:")
            for w in warnings:
                typer.echo(w)
        else:
            typer.echo("# No warnings found (0 warnings)")

        logger.info(f"Completed: extract_warnings {input}")
        raise typer.Exit(code=ExitCode.SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Pipeline error: {e}", err=True)
        logger.error(f"Failed: extract_warnings {input} - {e}")
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)


@app.callback(invoke_without_command=True)
def main(
    version: bool | None = typer.Option(None, "--version", is_eager=True, help="Show version"),
) -> None:
    if version:
        typer.echo(f"ol version {__version__}")
        raise typer.Exit()


def main_entry() -> int:
    app()
    return ExitCode.SUCCESS


if __name__ == "__main__":
    sys.exit(main_entry())
