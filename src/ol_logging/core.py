"""Core logging initialization and utilities."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import structlog

from ol_logging.constants import INFO, LOG_DIR
from ol_logging.formatters import _build_final_renderer, _build_processors
from ol_logging.handlers import get_console_handler, get_file_handler, is_console_enabled

_initialized = False


class _NamedPrintLogger(structlog.PrintLogger):
    def __init__(self, file=None) -> None:
        super().__init__(file)
        self.name = "unnamed"


class _NamedPrintLoggerFactory:
    """Print logger factory that stores the logger name so ``add_logger_name`` works."""

    def __init__(self, file=None) -> None:
        self.file = file

    def __call__(self, *args: Any) -> _NamedPrintLogger:
        logger = _NamedPrintLogger(self.file)
        if args:
            first = args[0]
            if isinstance(first, str):
                logger.name = first
            else:
                logger.name = getattr(first, "name", "unnamed")
        return logger


def configure_structlog(level: int, file: Any = None) -> None:
    """Configure structlog globally with the standard processor chain.

    If ``file`` is provided, structlog ``PrintLoggerFactory`` writes to
    that file (same file as the stdlib handler for unified JSONL output).
    """
    structlog.configure(
        processors=_build_processors() + [_build_final_renderer()],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=_NamedPrintLoggerFactory(file=file),
        cache_logger_on_first_use=True,
    )


def init_logger(level: int = INFO, log_dir: Path = LOG_DIR) -> None:
    """Initialize root logger with handlers + configure structlog."""
    global _initialized
    if _initialized:
        return

    log_dir.mkdir(exist_ok=True, parents=True)
    from datetime import date
    log_file_path = log_dir / f"ol-{date.today().isoformat()}.log"
    configure_structlog(level, file=open(log_file_path, "a", encoding="utf-8"))

    root_logger = logging.getLogger("ol")
    root_logger.setLevel(level)
    root_logger.addHandler(get_file_handler(log_dir, level))

    if is_console_enabled():
        root_logger.addHandler(get_console_handler(level))

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """Return a stdlib logger for the given module path.

    Back-compat: returns ``logging.getLogger("ol.<name>")`` so existing
    callers that use ``logger.name`` or ``isinstance(logger, Logger)``
    continue to work. Structlog's primary path is enabled by the
    ``init_logger()`` formatter wiring; new code can also call
    ``structlog.get_logger("ol.<name>").info(event, key=value)`` and
    the same JSON/text shape is emitted via the same file handler.
    """
    return logging.getLogger(f"ol.{name}")


def is_initialized() -> bool:
    """Check if logger has been initialized."""
    return _initialized
