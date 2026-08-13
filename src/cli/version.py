"""Version utilities for OL CLI."""
from __future__ import annotations

def version_callback(value: bool) -> None:
    """Handle --version flag."""
    if value:
        from ol_cli import __version__
        import typer
        typer.echo(f"ol version {__version__}")
        raise typer.Exit()
