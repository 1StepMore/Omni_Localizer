"""Log formatters: structlog-based primary, pythonjsonlogger fallback.

The structlog path emits the standard JSON shape used across all 3 modules:
    {"timestamp": "2026-06-22T...", "level": "INFO", "module": "ol.cli",
     "request_id": "abc-123", "event": "Translated 5 files", **kwargs}

The pythonjsonlogger path is kept as a graceful fallback for code that
constructs a stdlib logger + StreamHandler manually (e.g. legacy tests).
Toggle via the ``OMNI_LOG_FORMAT`` env var (``json`` / ``console``).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import structlog

TEXT_FORMATTER = "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _uppercase_level(_logger: Any, _method_name: str, event_dict: dict) -> dict:
    if "level" in event_dict:
        event_dict["level"] = event_dict["level"].upper()
    return event_dict


def _add_module_field(_logger: Any, _method_name: str, event_dict: dict) -> dict:
    name = event_dict.pop("logger", None)
    if name is not None and "module" not in event_dict:
        event_dict["module"] = name
    return event_dict


def _is_json_mode() -> bool:
    return os.getenv("OMNI_LOG_FORMAT", "console").lower() == "json"


def _build_processors() -> list:
    """Pre-processors used by both structlog and the ProcessorFormatter."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.ExtraAdder(),
        structlog.stdlib.add_logger_name,
        _add_module_field,
        structlog.stdlib.add_log_level,
        _uppercase_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def _build_final_renderer() -> Any:
    """Return the final renderer (JSON in json mode, ConsoleRenderer otherwise)."""
    if _is_json_mode():
        return structlog.processors.JSONRenderer(sort_keys=True)
    return structlog.dev.ConsoleRenderer(colors=False)


def get_formatter() -> logging.Formatter:
    """Return a stdlib formatter for the legacy stdlib-only path.

    This is the back-compat shim used by tests and by callers that wire
    a fresh stdlib ``StreamHandler`` / ``FileHandler`` and log via
    ``logging.getLogger(...)``. New code should use the structlog
    primary path via ``get_logger()`` and let ``init_logger()`` wire
    the ``ProcessorFormatter`` onto the file handler automatically.
    """
    if _is_json_mode():
        return get_legacy_json_formatter()
    return logging.Formatter(TEXT_FORMATTER, datefmt=DATE_FORMAT)


def get_structlog_formatter() -> logging.Formatter:
    """Return a structlog ``ProcessorFormatter`` for stdlib handlers.

    Use this when you have an existing stdlib handler (e.g. the
    ``RotatingFileHandler`` wired up by ``handlers.get_file_handler``)
    and want it to emit the same JSON/text shape as the structlog
    primary path.
    """
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_build_processors(),
        processor=_build_final_renderer(),
    )


def get_legacy_json_formatter() -> logging.Formatter:
    """Return a pythonjsonlogger ``JsonFormatter`` (graceful fallback).

    Kept for legacy stdlib-only tests that wire a fresh ``StreamHandler``
    + ``setFormatter`` and log via stdlib. New code should use the
    structlog primary path (``get_formatter()`` or ``get_logger()``).
    """
    from pythonjsonlogger.json import JsonFormatter
    return JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "module",
        },
    )
