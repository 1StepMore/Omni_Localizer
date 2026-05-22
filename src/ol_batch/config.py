"""Batch processing configuration module."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BatchConfig:
    max_concurrent: int = 5
    retry_attempts: int = 3
    retry_delay: float = 1.0
    file_patterns: list[str] = field(
        default_factory=lambda: ["*.md", "*.xliff", "*.xlf"],
    )
    skip_existing: bool = True
    timeout: float | None = None


@dataclass
class BatchResult:
    succeeded: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    total: int = 0

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return len(self.succeeded) / self.total * 100
