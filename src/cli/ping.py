"""ol ping — Health check for OL MCP server.

Companion CLI to the OL MCP ping tool. Prints server version and status.
"""
from __future__ import annotations

import json

import typer

from cli._shared import ExitCode


def ping() -> None:
    """Health check: print OL server version."""
    from importlib.metadata import version as _v
    try:
        ol_version = _v("omni-localizer")
    except Exception:
        ol_version = "unknown"
    typer.echo(json.dumps({"module": "ol", "version": ol_version, "status": "ok"}))
    raise typer.Exit(code=ExitCode.SUCCESS)
