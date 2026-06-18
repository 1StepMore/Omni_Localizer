"""Log formatters for structured output.

Supports two formats via the OMNI_LOG_FORMAT env var:
- "console" (default): human-readable text format
- "json": structured JSON with timestamp, level, module, request_id, message

Example JSON output:
    {"timestamp": "2026-06-18 19:50:00", "level": "INFO", "module": "ol.cli",
     "request_id": "abc-123", "message": "Translated 5 files"}
"""

import logging
import os

TEXT_FORMATTER = "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

JSON_FORMAT_FIELDS = "%(asctime)s %(levelname)s %(name)s %(message)s"
JSON_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
JSON_RENAME_FIELDS = {
    "asctime": "timestamp",
    "levelname": "level",
    "name": "module",
}


def _is_json_mode() -> bool:
    """Check if JSON logging is enabled via env var."""
    return os.getenv("OMNI_LOG_FORMAT", "console").lower() == "json"


def get_formatter() -> logging.Formatter:
    """Return formatter: JSON when OMNI_LOG_FORMAT=json, else text."""
    if _is_json_mode():
        from pythonjsonlogger.json import JsonFormatter
        return JsonFormatter(
            JSON_FORMAT_FIELDS,
            datefmt=JSON_DATE_FORMAT,
            rename_fields=JSON_RENAME_FIELDS,
        )
    return logging.Formatter(TEXT_FORMATTER, datefmt=DATE_FORMAT)
