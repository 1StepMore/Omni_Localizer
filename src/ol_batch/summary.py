"""Batch processing summary and reporting."""

from rich.console import Console
from rich.table import Table

from ol_batch.config import BatchResult

console = Console()


def print_summary(result: BatchResult, duration: float) -> None:
    """Print batch processing summary with colored output.

    Args:
        result: Batch result containing succeeded and failed files.
        duration: Total processing duration in seconds.

    """
    console.print("\n[bold]Batch Processing Summary[/bold]")
    console.print(f"Duration: {duration:.2f}s")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total Files", str(result.total))
    table.add_row("Succeeded", f"[green]{len(result.succeeded)}[/green]")
    table.add_row("Failed", f"[red]{len(result.failed)}[/red]")
    table.add_row("Success Rate", f"{result.success_rate:.1f}%")

    console.print(table)

    if result.succeeded:
        console.print("\n[green]Succeeded files:[/green] (first 5)")
        for path in result.succeeded[:5]:
            console.print(f"  • {path.name}")
        if len(result.succeeded) > 5:
            console.print(f"  ... and {len(result.succeeded) - 5} more")

    if result.failed:
        console.print("\n[red]Failed files:[/red]")
        for path, error in result.failed:
            safe_error = _sanitize_error(error)
            console.print(f"  ✗ {path.name}: {safe_error}")


def _sanitize_error(error: str) -> str:
    """Remove sensitive data from error messages.

    Args:
        error: Original error message.

    Returns:
        Error message with sensitive data redacted.

    """
    import re

    patterns = [
        (r'api[_-]?key["\']?\s*[:=]\s*["\'][^"\']{8,}["\']', '[API_KEY_REDACTED]'),
        (r'Bearer\s+[A-Za-z0-9_\-]{20,}', '[TOKEN_REDACTED]'),
        (r'password["\']?\s*[:=]\s*["\'][^"\']+["\']', '[PASSWORD_REDACTED]'),
    ]

    sanitized = error
    for pattern, replacement in patterns:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

    return sanitized
