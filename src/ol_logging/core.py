"""Core logging initialization and utilities."""

import logging
from pathlib import Path

from ol_logging.constants import INFO, LOG_DIR
from ol_logging.handlers import get_console_handler, get_file_handler, is_console_enabled

_initialized = False

def init_logger(level: int = INFO, log_dir: Path = LOG_DIR) -> None:
    """Initialize root logger with handlers."""
    global _initialized
    if _initialized:
        return

    root_logger = logging.getLogger("ol")
    root_logger.setLevel(level)
    root_logger.addHandler(get_file_handler(log_dir, level))

    if is_console_enabled():
        root_logger.addHandler(get_console_handler(level))

    _initialized = True

def get_logger(name: str) -> logging.Logger:
    """Get logger for module (e.g., 'cli' or 'batch.processor')."""
    return logging.getLogger(f"ol.{name}")

def is_initialized() -> bool:
    """Check if logger has been initialized."""
    return _initialized
