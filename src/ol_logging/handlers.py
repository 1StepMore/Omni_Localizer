"""Log handlers with rotation and console output."""

import logging.handlers
import os
from datetime import date
from pathlib import Path

from ol_logging.constants import LOG_FILE_PATTERN, MAX_BYTES, BACKUP_COUNT
from ol_logging.formatters import get_formatter


def get_file_handler(log_dir: Path, level: int) -> logging.Handler:
    """Create rotating file handler."""
    log_dir.mkdir(exist_ok=True, parents=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / LOG_FILE_PATTERN.format(date=date.today().isoformat()),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
    )
    handler.setLevel(level)
    handler.setFormatter(get_formatter())
    return handler


def get_console_handler(level: int) -> logging.Handler:
    """Create console handler for optional stdout output."""
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(get_formatter())
    return handler


def is_console_enabled() -> bool:
    """Check if console logging is enabled via env var."""
    return os.getenv("OL_LOG_CONSOLE", "") == "1"