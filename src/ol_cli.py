"""Omni-Localizer CLI - Typer-based command line interface."""

import asyncio
import hashlib
import os
import re
import shutil
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

# ========== OL Frontmatter Support ==========
from datetime import UTC, datetime
from pathlib import Path

import typer

from ol_logging.core import get_logger, init_logger
from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_xliff.pipeline import XLIFFRepairPipeline
from ol_core.dataclass import TranslationUnit

if TYPE_CHECKING:
    from ol_lqa.judge import JudgeService
    from ol_pool.router import ModelPool
    from ol_retry.retry import RetryManager
    from ol_terminology import Glossary


# ========== A6: Content-addressed cache (~/.omni_cache/ol/) ==========
# Re-runs of the same input+config skip the expensive translation and just
# copy the cached <input_stem>.<ext> to the output dir. The cache root can
# be overridden with the OMNI_CACHE_DIR env var (used by tests). Mode 0o700
# protects any sensitive content (e.g., a translated MD file that contains
# private info).
# CACHE_DIR_NAME is the per-module subdirectory under OMNI_CACHE_DIR.
CACHE_DIR_NAME = "ol"
_cache_logger = get_logger("cli.cache")


# ========== A12: Glossary single-use module state ==========
# The typer command sets ``_pending_glossary`` before calling
# ``asyncio.run(_translate_*_async(...))``; the async entry point
# reads it via ``_consume_glossary_for_translation()`` and clears it.
#
# Why module state? Because the pre-existing ``test_ol_cache.py`` and
# ``test_xliff_translate.py`` fakes mock the async functions with a
# fixed-arity signature; adding a ``glossary`` positional param would
# break them. Module state lets us thread the glossary through without
# changing the function's public signature. The CLI is a sequential
# command path (set state → asyncio.run → read state → clear), so
# concurrent state corruption is not a concern.
_pending_glossary: 'Glossary | None' = None


def _set_glossary_for_next_translation(glossary: 'Glossary | None') -> None:
    """Set the glossary for the next ``_translate_*_async`` call.

    Single-use: the next consume clears it. Subsequent consumes
    return ``None`` until another ``_set_glossary_for_next_translation``
    is issued.
    """
    global _pending_glossary
    _pending_glossary = glossary


def _consume_glossary_for_translation() -> 'Glossary | None':
    """Read the pending glossary (set by the typer command) and clear it."""
    global _pending_glossary
    g = _pending_glossary
    _pending_glossary = None
    return g


# ========== A12.4: Restoration enabled-flag single-use module state ==========
# ``--no-restoration`` is the user-visible switch. The typer command sets
# the flag (True = restoration enabled, default) before
# ``asyncio.run(_translate_*_async(...))``; the async entry point reads
# it via ``_consume_restoration_for_translation()`` and clears it.
# Same rationale as the glossary module state: we don't want to change
# ``_translate_*_async``'s positional signature because pre-existing
# test_ol_cache.py fakes mock it with a fixed 5-arg signature.
_pending_restoration_enabled: bool = True


def _set_restoration_for_next_translation(enabled: bool) -> None:
    global _pending_restoration_enabled
    _pending_restoration_enabled = enabled


def _consume_restoration_for_translation() -> bool:
    """Defaults to ``True`` (restoration enabled) so callers that don't
    set it explicitly keep working. Reset to the default after consume."""
    global _pending_restoration_enabled
    v = _pending_restoration_enabled
    _pending_restoration_enabled = True
    return v


# ========== A12.5: glossary_max_terms single-use module state ==========
# ``--glossary-max-terms N`` overrides the default top-5 in
# ``Glossary.inject_into_prompt``. We don't add a positional arg to
# ``_translate_*_async`` for the same reason as glossary/restoration.
_pending_glossary_max_terms: int = 5


def _set_glossary_max_terms_for_next_translation(n: int) -> None:
    global _pending_glossary_max_terms
    if not isinstance(n, int) or n < 1:
        n = 5
    _pending_glossary_max_terms = n


def _consume_glossary_max_terms_for_translation() -> int:
    global _pending_glossary_max_terms
    v = _pending_glossary_max_terms
    _pending_glossary_max_terms = 5
    return v


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


def _cache_root() -> Path:
    """Return the OL cache root, creating it (mode 0o700) on first access.

    The env var is read at call-time (not at import-time) so tests can
    override it via monkeypatch.setenv() before any call.
    """
    root = Path(
        os.environ.get("OMNI_CACHE_DIR", str(Path.home() / ".omni_cache"))
    ) / CACHE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _cache_key(
    input_path: Path,
    config_path: str | None,
    add_frontmatter: bool = True,
    concurrency: int = 5,
    detect_language: bool = True,
    lqa_enabled: bool = False,
    no_restoration: bool = False,
    no_glossary: bool = False,
    glossary: str | None = None,
    glossary_max_terms: int = 5,
) -> str:
    """Return sha256(input_bytes + config_bytes_if_any + behavioral_flags).

    Behavioral CLI flags that affect the produced output bytes (frontmatter
    on/off, concurrency for batch, language-detection, LQA, restoration,
    glossary, glossary-max-terms) are mixed into the digest so a flag
    change invalidates the cached output. See T24a.
    """
    h = hashlib.sha256()
    h.update(input_path.read_bytes())
    if config_path:
        cfg = Path(config_path)
        if cfg.exists():
            h.update(cfg.read_bytes())
    h.update(f"|fm={int(add_frontmatter)}".encode())
    h.update(f"|con={int(concurrency)}".encode())
    h.update(f"|det={int(detect_language)}".encode())
    h.update(f"|lqa={int(lqa_enabled)}".encode())
    h.update(f"|nres={int(no_restoration)}".encode())
    h.update(f"|nglo={int(no_glossary)}".encode())
    h.update(f"|glo={glossary or ''}".encode())
    h.update(f"|gmt={int(glossary_max_terms)}".encode())
    return h.hexdigest()


def _check_cache(
    input_path: Path,
    output_path: Path,
    config_path: str | None,
    no_cache: bool = False,
    ext: str | None = None,
    add_frontmatter: bool = True,
    concurrency: int = 5,
    detect_language: bool = True,
    lqa_enabled: bool = False,
    no_restoration: bool = False,
    no_glossary: bool = False,
    glossary: str | None = None,
    glossary_max_terms: int = 5,
) -> bool:
    """If cached, copy ``<input_stem><ext>`` to ``output_path`` and return True.

    Honors ``--no-cache``: returns False without touching the cache.
    """
    if no_cache:
        return False
    if ext is None:
        ext = input_path.suffix
    key = _cache_key(
        input_path, config_path,
        add_frontmatter=add_frontmatter,
        concurrency=concurrency,
        detect_language=detect_language,
        lqa_enabled=lqa_enabled,
        no_restoration=no_restoration,
        no_glossary=no_glossary,
        glossary=glossary,
        glossary_max_terms=glossary_max_terms,
    )
    cache_file = _cache_root() / f"{key}{ext}"
    if cache_file.exists():
        target = output_path / input_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(cache_file, target)
        _cache_logger.info(f"Cache hit: {cache_file} -> {target}")
        return True
    return False


def _write_cache(
    input_path: Path,
    output_path: Path,
    config_path: str | None,
    no_cache: bool = False,
    ext: str | None = None,
    add_frontmatter: bool = True,
    concurrency: int = 5,
    detect_language: bool = True,
    lqa_enabled: bool = False,
    no_restoration: bool = False,
    no_glossary: bool = False,
    glossary: str | None = None,
    glossary_max_terms: int = 5,
) -> None:
    """Copy the produced output into the cache for next run.

    Honors ``--no-cache``: no-op.
    """
    if no_cache:
        return
    output_file = output_path / input_path.name
    if not output_file.exists():
        return
    if ext is None:
        ext = input_path.suffix
    key = _cache_key(
        input_path, config_path,
        add_frontmatter=add_frontmatter,
        concurrency=concurrency,
        detect_language=detect_language,
        lqa_enabled=lqa_enabled,
        no_restoration=no_restoration,
        no_glossary=no_glossary,
        glossary=glossary,
        glossary_max_terms=glossary_max_terms,
    )
    cache_file = _cache_root() / f"{key}{ext}"
    cache_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy(output_file, cache_file)
    _cache_logger.debug(f"Cache miss: wrote {cache_file}")


def _clear_ol_cache() -> int:
    """Remove all cached OL files. Returns the number of files removed."""
    root = _cache_root()
    if not root.exists():
        return 0
    count = sum(1 for _ in root.iterdir())
    shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return count


def _load_glossary_or_none(path: str | None) -> 'Glossary | None':
    """Load a glossary file, or return None if ``path`` is None.

    ``--glossary`` is OPTIONAL — when the flag is not passed we return
    ``None`` and the translation pipeline runs without glossary
    injection (existing behavior, no regression).

    On load failure (malformed JSON/YAML, schema error, missing file),
    we exit with a clear error message — never silently fall back, the
    user passed the flag intentionally and wants to know.
    """
    if path is None:
        return None
    from ol_terminology import Glossary

    p = Path(path)
    if not p.exists():
        typer.echo(f"Error: glossary file not found: {path}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)
    try:
        return Glossary.load(p)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"Error: failed to load glossary {path}: {e}", err=True)
        raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)


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
    request_id: str | None = None,
) -> str:
    if ol_version is None:
        ol_version = _get_ol_version()
    """Generate YAML frontmatter header with translation metadata.

    Args:
        source_lang: Source language code (ISO 639-1)
        target_lang: Target language code (ISO 639-1)
        original_filename: Original input filename
        ol_version: OL version number
        request_id: Optional UUID for end-to-end tracing (B2).

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
    ]
    if request_id:
        frontmatter_lines.append(f"request_id: {request_id}")
    frontmatter_lines.extend(["---", ""])

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


def _extract_request_id(input_path: Path) -> str | None:
    """Extract request_id from OPP manifest.json or XLIFF header (B2).

    Looks for a sibling ``*_manifest.json`` first, then falls back to
    scanning the XLIFF header for a ``request_id=...`` note.
    Returns None if not found.
    """
    import re as _re
    manifest_candidate = input_path.parent / f"{input_path.stem}_manifest.json"
    if manifest_candidate.exists():
        try:
            import json as _json
            data = _json.loads(manifest_candidate.read_text(encoding="utf-8"))
            rid = data.get("request_id")
            if rid:
                return rid
        except (OSError, ValueError):
            pass
    if input_path.suffix.lower() in (".xlf", ".xliff"):
        try:
            content = input_path.read_text(encoding="utf-8")
            m = _re.search(r"request_id=([0-9a-fA-F-]{36})", content)
            if m:
                return m.group(1)
        except OSError:
            pass
    return None


def _build_xliff_header_note(src_lang: str, tgt_lang: str, request_id: str | None = None) -> str:
    """Build XLIFF-compliant header note element."""
    validated_src = _validate_lang_code(src_lang)
    validated_tgt = _validate_lang_code(tgt_lang)
    note_text = f"Translated from {validated_src} to {validated_tgt} by OL"
    if request_id:
        note_text += f" request_id={request_id}"
    return f'<header>\n    <note from="OL">{_escape_xml(note_text)}</note>\n  </header>'


def _inject_xliff_header(repaired: str, header_note: str) -> str:
    """Inject header note into XLIFF output at correct position."""
    # Insert header after <xliff ...> opening tag, before <file> element
    if "<file" in repaired:
        return repaired.replace("<file", header_note + "\n  <file", 1)
    return repaired  # No <file> element found, skip header injection


from importlib.metadata import version as _pkg_version
__version__ = _pkg_version("omni-localizer")

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


def _enforce_file_size(input_path: Path, max_size_mb: int = 50) -> None:
    """Reject files larger than max_size_mb."""
    size_mb = input_path.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        raise typer.BadParameter(
            f"Input file {input_path.name} is {size_mb:.1f} MB, "
            f"exceeds limit of {max_size_mb} MB"
        )


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
    # A12.3: read the glossary from module state (set by the typer command
    # before asyncio.run). We intentionally keep this function's POSITIONAL
    # signature unchanged so the pre-existing test_ol_cache.py fakes
    # (which mock this function with a fixed 5-arg signature) still work.
    glossary = _consume_glossary_for_translation()
    import os
    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        import sys
        from pathlib import Path as _SeamPath
        _suite_root = _SeamPath(__file__).resolve().parents[2]
        if str(_suite_root) not in sys.path:
            sys.path.insert(0, str(_suite_root))
        from tests.test_e2e_pipeline_fixtures import _FakeModelPool
        from ol_pool.router import ModelPool as _MP
        pool = cast(_MP, cast(object, _FakeModelPool()))
        _apply_fake_llm_seam()
    else:
        from ol_pool.router import ModelPool
        pool = ModelPool.get_instance(config_path) if config_path else ModelPool.get_instance()

    from ol_config.loader import load_config
    cfg, _ = load_config(config_path or "config/default.yaml")
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
        # 2026-06-18 round 16 Phase B2: propagate request_id from OPP.
        rid = _extract_request_id(input_path)

        frontmatter = _generate_frontmatter(
            source_lang=safe_src_lang,
            target_lang=safe_tgt_lang,
            original_filename=input_path.name,
            ol_version=_get_ol_version(),
            request_id=rid,
        )
        output_content = frontmatter + repaired
    else:
        output_content = repaired

    from ol_post.punctuation import normalize_to_english, normalize_to_chinese
    import re as _re
    _fm_match = _re.match(r'^(---\s*\n.*?\n---\s*\n)', output_content, _re.DOTALL)
    if _fm_match:
        _fm = _fm_match.group(1)
        _body = output_content[len(_fm):]
        if tgt_lang.startswith("en"):
            _body = normalize_to_english(_body)
        elif tgt_lang.startswith("zh"):
            _body = normalize_to_chinese(_body)
        output_content = _fm + _body
    elif tgt_lang.startswith("en"):
        output_content = normalize_to_english(output_content)
    elif tgt_lang.startswith("zh"):
        output_content = normalize_to_chinese(output_content)

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
    import os
    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        import sys
        from pathlib import Path as _SeamPath
        _suite_root = _SeamPath(__file__).resolve().parents[2]
        if str(_suite_root) not in sys.path:
            sys.path.insert(0, str(_suite_root))
        from tests.test_e2e_pipeline_fixtures import _FakeModelPool
        from ol_pool.router import ModelPool as _MP
        pool = cast(_MP, cast(object, _FakeModelPool()))
        _apply_fake_llm_seam()
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
    glossary_max_terms: int = typer.Option(
        5, "--glossary-max-terms",
        min=1,
        help="How many top glossary terms to inject per trans-unit "
             "(default 5). Applies to --glossary / config glossary "
             "injection; ignored when --no-glossary is set.",
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
        loaded_glossary = _load_glossary_or_none(glossary)
        # A12.5: --no-glossary overrides both --glossary and the config glossary.
        if no_glossary:
            loaded_glossary = None
        _apply_glossary_max_terms(loaded_glossary, glossary_max_terms)
        _set_glossary_for_next_translation(loaded_glossary)
        _set_restoration_for_next_translation(enabled=not no_restoration)

        # A6: cache check before any expensive LLM work.
        if _check_cache(
            input_path, output_path, config, no_cache=no_cache,
            add_frontmatter=add_frontmatter,
            no_restoration=no_restoration,
            no_glossary=no_glossary,
            glossary=glossary,
            glossary_max_terms=glossary_max_terms,
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

        output_file = asyncio.run(
            _translate_md_async(
                input_path, output_path, config, src, tgt, add_frontmatter,
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
        loaded_glossary = _load_glossary_or_none(glossary)
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
