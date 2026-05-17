"""File discovery utilities for batch processing."""

from pathlib import Path


def validate_directory(path: Path) -> bool:
    if not path.exists():
        return False
    if not path.is_dir():
        return False
    return True


def discover_files(directory: Path, patterns: list[str]) -> list[Path]:
    if not validate_directory(directory):
        return []

    results: list[Path] = []
    for pattern in patterns:
        for path in directory.rglob(pattern):
            if path.is_symlink():
                continue
            if path.is_file():
                results.append(path)

    return sorted(results)