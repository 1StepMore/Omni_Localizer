"""Omni-Localizer CLI - Typer-based command line interface."""
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any

import typer

# ========== Version ==========
from importlib.metadata import version as _pkg_version
__version__ = _pkg_version("omni-localizer")

# ========== Logging ==========
from ol_core.dataclass import ChannelType, TranslationContext
from ol_logging.core import get_logger, init_logger
init_logger()
logger = get_logger("cli")

# ========== Re-exports (backward compat for tests and external consumers) ==========
# Use module __getattr__ to lazy-load these so we don't trigger heavy LLM
# imports at module load time (avoids circular import with ol_batch.processor).

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "_translate_xliff_pipelined": ("ol_cli.translate_xliff", "_translate_xliff_pipelined"),
    "_translate_units_concurrent": ("ol_cli.translate_xliff", "_translate_units_concurrent"),
    "_translate_md_async": ("ol_cli.translate_md", "_translate_md_async"),
    "_translate_md_units_concurrent": ("ol_cli.translate_md", "_translate_md_units_concurrent"),
    "_cache_key": ("ol_cli.cache", "_cache_key"),
    "_cache_root": ("ol_cli.cache", "_cache_root"),
    "_check_cache": ("ol_cli.cache", "_check_cache"),
    "_write_cache": ("ol_cli.cache", "_write_cache"),
    "_clear_ol_cache": ("ol_cli.cache", "_clear_ol_cache"),
    "_checkpoint_root": ("ol_cli.cache", "_checkpoint_root"),
    "_compute_checkpoint_hash": ("ol_cli.cache", "_compute_checkpoint_hash"),
    "_is_checkpoint_enabled": ("ol_cli.cache", "_is_checkpoint_enabled"),
    "_apply_post_translate_restoration": ("ol_cli.cache", "_apply_post_translate_restoration"),
    "_build_restoration_pool": ("ol_cli.cache", "_build_restoration_pool"),
    "CACHE_DIR_NAME": ("ol_cli.cache", "CACHE_DIR_NAME"),
    "CHECKPOINT_INTERVAL_DEFAULT": ("ol_cli.cache", "CHECKPOINT_INTERVAL_DEFAULT"),
    "_generate_frontmatter": ("ol_cli.frontmatter", "_generate_frontmatter"),
    "_generate_skip_frontmatter": ("ol_cli.frontmatter", "_generate_skip_frontmatter"),
    "_get_ol_version": ("ol_cli.frontmatter", "_get_ol_version"),
    "_validate_lang_code": ("ol_cli.frontmatter", "_validate_lang_code"),
    "_escape_yaml_value": ("ol_cli.frontmatter", "_escape_yaml_value"),
    "_escape_xml": ("ol_cli.frontmatter", "_escape_xml"),
    "_build_xliff_header_note": ("ol_cli.frontmatter", "_build_xliff_header_note"),
    "_inject_xliff_header": ("ol_cli.frontmatter", "_inject_xliff_header"),
    "_load_glossary_or_none": ("ol_cli.frontmatter", "_load_glossary_or_none"),
    "_batch_short_units": ("ol_cli.translate_xliff", "_batch_short_units"),
    "_parse_batch_response": ("ol_cli.translate_xliff", "_parse_batch_response"),
    "_translate_batch": ("ol_cli.translate_xliff", "_translate_batch"),
    "_translate_one_unit": ("ol_cli.translate_xliff", "_translate_one_unit"),
    "_translate_xliff_async": ("ol_cli.translate_xliff", "_translate_xliff_async"),
    "_UnitTranslationResult": ("ol_cli.translate_xliff", "_UnitTranslationResult"),
    "_translate_batch_async": ("ol_cli.translate_batch", "_translate_batch_async"),
}


def __getattr__(name: str):
    """Lazy-load re-exports to avoid circular imports at module load time."""
    if name in _LAZY_IMPORTS:
        mod_name, attr_name = _LAZY_IMPORTS[name]
        from importlib import import_module
        mod = import_module(mod_name)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    raise AttributeError(f"module 'ol_cli' has no attribute {name!r}")

# ========== Signal handling ==========
_interrupted = False


def _sigint_handler(signum, frame):
    global _interrupted
    _interrupted = True
    typer.echo("\nReceived Ctrl+C - finishing in-flight files, no new starts...")


def _setup_signal_handler():
    signal.signal(signal.SIGINT, _sigint_handler)


def is_interrupted() -> bool:
    return _interrupted


# ========== Typer app ==========
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


# ========== CLI infrastructure ==========

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


# ========== Test seam ==========

def _apply_fake_llm_seam() -> None:
    """Test seam: when OMNI_TEST_FAKE_LLM=1, also stub ``span_aligner``.

    The OMNI_TEST_FAKE_LLM seam short-circuits the LLM call
    (``ModelPool.translate``) but does not cover the post-translation
    MD repair pipeline. Level 2 of that pipeline imports
    ``span_aligner.SpanProjector``, which constructs a HF transformer
    (``bert-base-multilingual-cased``) -- that fails in hermetic CI
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


# ========== .env loading ==========

def _load_env_for_cli() -> None:
    """Load .env file for CLI commands that call LLM APIs.

    Search order:
      1. $OL_DOTENV env var (explicit override)
      2. ./.env (current working directory)
      3. Walk up parent directories looking for .env
      4. ~/.config/ol/.env (user-level fallback)

    If no .env is found, the function returns silently. The LLM call
    downstream will fail loudly at the auth layer if required keys are
    missing -- no silent fallback.
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


# ========== CLI Commands ==========

@app.command()
def translate_md(
    input: str = typer.Argument(..., help="Input markdown file path"),
    output_dir: str | None = typer.Option(None, "--output-dir", "-o", help="Output directory (required)"),
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
        # Access via module to trigger __getattr__; needed so tests
        # that patch ol_cli._translate_md_async work correctly.
        import sys as _sys
        _self = _sys.modules[__name__]
        _cache_root = _self._cache_root
        _check_cache = _self._check_cache
        _clear_ol_cache = _self._clear_ol_cache
        _write_cache = _self._write_cache
        _apply_post_translate_restoration = _self._apply_post_translate_restoration
        _build_restoration_pool = _self._build_restoration_pool
        _load_glossary_or_none = _self._load_glossary_or_none
        _translate_md_async = _self._translate_md_async

        if clear_cache:
            n = _clear_ol_cache()
            logger.info(f"Cleared {n} cached file(s) from {_cache_root()}")
            typer.echo(f"Cleared {n} cached file(s) from {_cache_root()}")
            raise typer.Exit(code=ExitCode.SUCCESS)

        src = source_lang or "en"
        tgt = target_lang or "zh"

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
        # A12.5: bind glossary_max_terms to the glossary instance
        if loaded_glossary is not None and glossary_max_terms != 5 and hasattr(loaded_glossary, "inject_into_prompt"):
            _original_inject = loaded_glossary.inject_into_prompt
            _gmt = glossary_max_terms
            def _patched_inject(source_text: str, prompt: str, max_terms: int | None = None) -> str:
                return _original_inject(source_text, prompt, max_terms=max_terms or _gmt)
            loaded_glossary.inject_into_prompt = _patched_inject

        # Build CLI context (replaces module state threading)
        cli_ctx = TranslationContext(
            file_path=str(input_path),
            channel_type=ChannelType.MD,
            original_full_text=input_path.read_text(encoding="utf-8"),
            glossary_obj=loaded_glossary,
            glossary_max_terms=glossary_max_terms,
            restoration_enabled=not no_restoration,
        )

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
                ctx=cli_ctx,
            ),
        )

        # A12.4: post-translate restoration runs after the async pipeline
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
        import sys as _sys
        _self = _sys.modules[__name__]
        _translate_batch_async = _self._translate_batch_async
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
                ctx=TranslationContext(
                    file_path=str(input_path),
                    channel_type=ChannelType.MD,
                    original_full_text="",
                ),
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
    output_dir: str | None = typer.Option(None, "--output-dir", "-o", help="Output directory (required)"),
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
        import sys as _sys
        _self = _sys.modules[__name__]
        _cache_root = _self._cache_root
        _check_cache = _self._check_cache
        _clear_ol_cache = _self._clear_ol_cache
        _write_cache = _self._write_cache
        _apply_post_translate_restoration = _self._apply_post_translate_restoration
        _build_restoration_pool = _self._build_restoration_pool
        _load_glossary_or_none = _self._load_glossary_or_none
        _translate_xliff_async = _self._translate_xliff_async

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
        # A12.5: bind glossary_max_terms to the glossary instance
        if loaded_glossary is not None and glossary_max_terms != 5 and hasattr(loaded_glossary, "inject_into_prompt"):
            _original_inject = loaded_glossary.inject_into_prompt
            _gmt = glossary_max_terms
            def _patched_inject(source_text: str, prompt: str, max_terms: int | None = None) -> str:
                return _original_inject(source_text, prompt, max_terms=max_terms or _gmt)
            loaded_glossary.inject_into_prompt = _patched_inject

        # Build CLI context (replaces module state threading)
        cli_ctx = TranslationContext(
            file_path=str(input_path),
            channel_type=ChannelType.XLIFF,
            original_full_text=input_path.read_text(encoding="utf-8"),
            glossary_obj=loaded_glossary,
            glossary_max_terms=glossary_max_terms,
            restoration_enabled=not no_restoration,
        )

        # Load .env to get MINIMAX_API_KEY etc. before calling LLM
        _load_env_for_cli()

        asyncio.run(_translate_xliff_async(
            Path(input), output_path, config_path, src_lang, tgt_lang,
            ctx=cli_ctx,
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
