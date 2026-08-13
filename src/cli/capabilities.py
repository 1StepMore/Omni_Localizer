"""ol capabilities — Print module capabilities (tools, formats, etc.).

Companion CLI to the OL MCP get_capabilities tool. Prints the same
JSON content that the MCP tool returns, so agents working through
either transport see the same view of what OL can do.
"""
from __future__ import annotations

import json

import typer

from cli._shared import ExitCode
from ol_mcp.get_capabilities import get_capabilities


def capabilities(
    json_output: bool = typer.Option(
        True, "--json/--no-json", help="Output as JSON (default) or pretty"
    ),
) -> None:
    """Print OL module capabilities (roles, language pairs, available tools)."""
    # get_capabilities is a sync function that returns a JSON string.
    # It already runs rate-limit + auth checks internally.
    result = get_capabilities()
    if json_output:
        typer.echo(result)
    else:
        try:
            data = json.loads(result)
            content = data.get("content", data)
            typer.echo(f"Module: {content.get('module')}")
            typer.echo(f"Version: {content.get('version')}")
            typer.echo(f"Roles: {', '.join(content.get('roles', []))}")
            typer.echo(f"Language pairs: {', '.join(content.get('language_pairs', []))}")
            typer.echo(f"Tools ({len(content.get('tools', []))}):")
            for tool in content.get("tools", []):
                typer.echo(f"  - {tool}")
        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            typer.echo(f"Error parsing capabilities response: {e}", err=True)
            typer.echo(result, err=True)
            raise typer.Exit(code=ExitCode.CLI_USAGE_ERROR)
