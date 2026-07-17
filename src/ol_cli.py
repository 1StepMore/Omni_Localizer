"""Omni-Localizer CLI - Typer-based command line interface."""
from __future__ import annotations

import re as _re
import sys

import typer

from importlib.metadata import version as _pkg_version
from ol_logging.core import get_logger, init_logger

__version__ = _pkg_version("omni-localizer")

# Initialize logging
init_logger()
logger = get_logger("cli")


def _validate_lang_code(code: str) -> str:
    if not _re.match(r"^[a-z]{2}(-[A-Z]{2})?$", code):
        raise ValueError(f"Invalid language code: {code}")
    return code


def _get_ol_version() -> str:
    return __version__





app = typer.Typer(
    name="ol",
    help="Omni-Localizer: AI-native localization pipeline with automated quality control.",
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Register SIGINT handler BEFORE heavy imports so Ctrl+C during cold start
# is caught by our handler (sets _interrupted flag) instead of the default
# handler (raises KeyboardInterrupt → exit 1).
# ---------------------------------------------------------------------------
from cli._shared import _setup_signal_handler  # noqa: E402

_setup_signal_handler()

# ---------------------------------------------------------------------------
# Import cli package — triggers submodule loading.
# Wrapped in try/except KeyboardInterrupt because CPython may raise
# KeyboardInterrupt during C-level import calls even with a custom
# signal handler (see OL#75 for details).
# ---------------------------------------------------------------------------
try:
    from cli import *  # noqa: E402, F401, F403

    # Explicit private-name re-exports for backward compat
    # (cli.translate_md etc. already use cli._shared, so no circular import)
    from cli._shared import (  # noqa: E402,F401
        ExitCode,
        _apply_fake_llm_seam,
        _setup_signal_handler,
        ensure_output_dir,
        output_json,
        validate_input_file,
    )
    from cli.cache import (  # noqa: E402,F401
        CACHE_DIR_NAME,
        _cache_key,
        _clear_ol_cache,
    )
    from cli.frontmatter import (  # noqa: E402,F401
        _build_xliff_header_note,
        _escape_xml,
        _generate_frontmatter,
        _generate_skip_frontmatter,
        _get_ol_version,
        _validate_lang_code,
    )
    from cli.translate_md import (  # noqa: E402,F401
        _translate_md_async,
        _translate_units_concurrent,
        translate_md,
    )
    from cli.translate_xliff import (  # noqa: E402,F401
        _translate_xliff_async,
        _translate_xliff_pipelined,
        translate_xliff,
    )
    from cli.batch import (  # noqa: E402,F401
        _translate_batch_async,
        extract_warnings,
        translate_batch,
    )
    from cli.capabilities import capabilities  # noqa: E402,F401
    from cli.shield_md import shield_md  # noqa: E402,F401
    from cli.unshield_md import unshield_md  # noqa: E402,F401
    from cli.extract_terms import extract_terms  # noqa: E402,F401
    from cli.add_tm_entries import add_tm_entries  # noqa: E402,F401
    from cli.disambiguate import disambiguate  # noqa: E402,F401
    from cli.generate_report import generate_report  # noqa: E402,F401
    from cli.inspect_config import inspect_config  # noqa: E402,F401
    from cli.judge_text import judge_text  # noqa: E402,F401
except KeyboardInterrupt:
    import os as _os
    _os._exit(3)
from cli.load_glossary import load_glossary  # noqa: E402,F401
from cli.search_tm import search_tm  # noqa: E402,F401
from cli.translation_status import translation_status  # noqa: E402,F401
from cli.ping import ping  # noqa: E402,F401
from cli.verify_terms import verify_terms  # noqa: E402,F401
from cli.profile_doc import profile_doc  # noqa: E402,F401
from cli.calibrate_threshold import calibrate_threshold  # noqa: E402,F401

# ---------------------------------------------------------------------------
# Register CLI commands with typer app
# ---------------------------------------------------------------------------
app.command()(translate_md)
app.command()(translate_xliff)
app.command()(translate_batch)
app.command()(extract_warnings)
app.command()(capabilities)
app.command()(shield_md)
app.command()(unshield_md)
app.command()(extract_terms)
app.command()(add_tm_entries)
app.command()(disambiguate)
app.command()(generate_report)
app.command()(inspect_config)
app.command()(judge_text)
app.command()(load_glossary)
app.command()(search_tm)
app.command()(translation_status)
app.command()(ping)
app.command()(verify_terms)
app.command()(profile_doc)
app.command()(calibrate_threshold)


# ---------------------------------------------------------------------------
# Main callback + entry point
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(
    version: bool | None = typer.Option(None, "--version", is_eager=True, help="Show version"),
) -> None:
    _setup_signal_handler()
    if version:
        typer.echo(f"ol version {__version__}")
        raise typer.Exit()


def main_entry() -> int:
    _setup_signal_handler()
    app()
    return ExitCode.SUCCESS


if __name__ == "__main__":
    sys.exit(main_entry())
