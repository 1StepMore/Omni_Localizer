"""Omni-Localizer CLI - Typer-based command line interface."""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import Any

import typer

from importlib.metadata import version as _pkg_version
from ol_logging.core import get_logger, init_logger

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


# ---------------------------------------------------------------------------
# Import cli package — triggers submodule loading.
# After this import, all public (+ private, via explicit re-exports) names
# from cli._shared, cli.cache, cli.frontmatter, cli.translate_md,
# cli.translate_xliff, and cli.batch are available on this module.
# ---------------------------------------------------------------------------
from cli import *  # noqa: E402, F401, F403

# Explicit private-name re-exports for backward compat
# (cli.translate_md etc. already use cli._shared, so no circular import)
from cli._shared import (  # noqa: E402
    _interrupted, _sigint_handler, ExitCode,
    _setup_signal_handler, is_interrupted,
    validate_input_file, _enforce_file_size,
    ensure_output_dir, output_json, _apply_fake_llm_seam,
)
from cli.cache import (  # noqa: E402
    CACHE_DIR_NAME, _cache_logger, _cache_root, _cache_key,
    _check_cache, _write_cache, _clear_ol_cache,
)
from cli.frontmatter import (  # noqa: E402
    _escape_yaml_value, _validate_lang_code, _escape_xml,
    _generate_frontmatter, _generate_skip_frontmatter, _get_ol_version,
    _extract_opp_metadata, _extract_request_id,
    _build_xliff_header_note, _inject_xliff_header,
)
from cli.translate_md import (  # noqa: E402
    _apply_glossary_max_terms, _apply_post_translate_restoration,
    _build_restoration_pool, _load_glossary_or_none,
    _load_env_for_cli, _load_dotenv,
    _UnitTranslationResult, _translate_one_unit, _translate_units_concurrent,
    _translate_md_async, _translate_md_units_concurrent, _translate_md_by_paragraph,
    translate_md,
)
from cli.translate_xliff import (  # noqa: E402
    _translate_xliff_pipelined, _translate_xliff_async, translate_xliff,
)
from cli.batch import (  # noqa: E402
    _translate_batch_async, translate_batch, extract_warnings,
)

# ---------------------------------------------------------------------------
# Register CLI commands with typer app
# ---------------------------------------------------------------------------
app.command()(translate_md)
app.command()(translate_xliff)
app.command()(translate_batch)
app.command()(extract_warnings)


# ---------------------------------------------------------------------------
# Main callback + entry point
# ---------------------------------------------------------------------------

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
