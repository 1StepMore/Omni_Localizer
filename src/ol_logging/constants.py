"""Logging constants and configuration."""

from pathlib import Path

# Log levels
DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40

# Paths
LOG_DIR = Path("logs")
LOG_FILE_PATTERN = "ol-{date}.log"

# Rotation
MAX_BYTES = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5

# Environment variables
LOG_LEVEL_ENV = "OL_LOG_LEVEL"
LOG_DIR_ENV = "OL_LOG_DIR"
LOG_CONSOLE_ENV = "OL_LOG_CONSOLE"