"""Rich progress bar for batch processing."""

import asyncio

from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn


class ProgressContext:
    """Context manager for rich progress bar with async cleanup."""

    def __init__(self) -> None:
        self._progress: Progress | None = None
        self._task_id: int | None = None
        self._done = asyncio.Event()

    async def __aenter__(self) -> "ProgressContext":
        self._progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[progress]{task.completed}/{task.total} files"),
            TimeRemainingColumn(),
        )
        self._progress.__enter__()
        self._task_id = self._progress.add_task("Processing: ", total=100)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._progress is not None:
            self._progress.__exit__(exc_type, exc_val, exc_tb)

    def update(self, filename: str, completed: int, total: int) -> None:
        """Update progress bar with current state."""
        if self._progress is not None and self._task_id is not None:
            description = f"Processing: {filename}"
            self._progress.update(
                self._task_id,
                description=description,
                completed=completed,
                total=total,
            )
