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
from cli._shared import (  # noqa: E402,F401
    ExitCode,
    _apply_fake_llm_seam,
)
from cli.frontmatter import (  # noqa: E402,F401
    _build_xliff_header_note,
    _generate_frontmatter,
    _generate_skip_frontmatter,
    _get_ol_version,
    _validate_lang_code,
)
from cli.translate_md import (  # noqa: E402
    translate_md,
)
from cli.translate_xliff import (  # noqa: E402
    translate_xliff,
)
from cli.batch import (  # noqa: E402
    translate_batch, extract_warnings,
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
