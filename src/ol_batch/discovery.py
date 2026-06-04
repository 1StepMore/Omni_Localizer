"""File discovery utilities for batch processing."""
import os
from pathlib import Path

from ol_logging.core import get_logger

_logger = get_logger("batch.discovery")


def validate_directory(path: Path) -> bool:
    if not path.exists():
        _logger.warning(f"Invalid directory: {path}")
        return False
    if not path.is_dir():
        _logger.warning(f"Invalid directory: {path}")
        return False
    if not os.access(path, os.R_OK):
        _logger.warning(f"Directory not readable: {path}")
        return False
    return True


def discover_files(directory: Path, patterns: list[str]) -> list[Path]:
    if not validate_directory(directory):
        return []

    _logger.info(f"Scanning directory: {directory}")
    _logger.debug(f"Patterns: {patterns}")

    results: list[Path] = []
    for pattern in patterns:
        for path in directory.rglob(pattern):
            if path.is_symlink():
                continue
            if path.is_file():
                results.append(path)

    _logger.info(f"Found {len(results)} files matching {patterns}")
    return sorted(results)
