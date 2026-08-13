"""ol translation-status — Poll status of an async translation task.

Companion CLI to the OL MCP get_translation_status tool. Prints the
task status (pending, running, completed, failed) and result info.
"""
from __future__ import annotations

import json

import typer

from cli._shared import ExitCode


def translation_status(
    request_id: str = typer.Argument(..., help="Request ID returned by an async translation call"),
) -> None:
    """Poll the status of an async OL translation task."""
    try:
        from ol_mcp.status import get_translation_status as _impl
        from ol_mcp.task_tracker import InMemoryTaskTracker
        result = _impl(request_id, InMemoryTaskTracker())
    except Exception as e:
        typer.echo(f"Error: failed to get status: {e}", err=True)
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)

    typer.echo(json.dumps(result, ensure_ascii=False))
    raise typer.Exit(code=ExitCode.SUCCESS)
