"""Log handlers with rotation and console output."""
import logging.handlers
import os
from datetime import date
from pathlib import Path

from ol_logging.constants import BACKUP_COUNT, LOG_FILE_PATTERN, MAX_BYTES
from ol_logging.formatters import get_formatter


class _AutoRolloverFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that checks rollover in emit().

    The stdlib RotatingFileHandler only checks shouldRollover() inside
    handle(), not emit(). When a test (or any caller) invokes emit()
    directly, rotation never fires even for a single record larger than
    maxBytes. This subclass makes emit() self-contained.
    """

    def emit(self, record):
        if self.stream is None:
            self.stream = self._open()
        if self.maxBytes > 0:
            msg = "%s\n" % self.format(record)
            if self.stream.tell() + len(msg) >= self.maxBytes:
                self.doRollover()
        super().emit(record)


def get_file_handler(log_dir: Path, level: int) -> logging.Handler:
    """Create rotating file handler."""
    log_dir.mkdir(exist_ok=True, parents=True)
    handler = _AutoRolloverFileHandler(
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
