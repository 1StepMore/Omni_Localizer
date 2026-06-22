"""Logging constants and configuration."""

from pathlib import Path

DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40

LOG_DIR = Path("logs")
LOG_FILE_PATTERN = "ol-{date}.log"

MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

LOG_LEVEL_ENV = "OL_LOG_LEVEL"
LOG_DIR_ENV = "OL_LOG_DIR"
LOG_CONSOLE_ENV = "OL_LOG_CONSOLE"
LOG_FORMAT_ENV = "OMNI_LOG_FORMAT"

REQUEST_ID_FIELD = "request_id"
