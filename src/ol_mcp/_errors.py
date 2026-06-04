"""C12: shared error boundary for OL MCP tools.

This module provides a single `@mcp_error_boundary` decorator that replaces
the 6+ `try/except Exception as e: return ...str(e)...` copies across
`ol_mcp/tools.py`.

Behavior:
- Log the full traceback at ERROR level server-side.
- Return a JSON string with `success=False`, an opaque `error_code`
  (mapped from exception class), and a user-friendly `message` (no
  internals).
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
from typing import Any, Callable

_logger = logging.getLogger("ol_mcp.errors")

# Stable, opaque error code mapping. Adding new codes is fine; do not
# change the strings (clients may switch on them).
_ERROR_CODE_MAP: dict[type, str] = {
    FileNotFoundError: "OL_FILE_NOT_FOUND",
    PermissionError: "OL_PERMISSION_DENIED",
    ValueError: "OL_INVALID_INPUT",
    KeyError: "OL_MISSING_KEY",
    TimeoutError: "OL_TIMEOUT",
    NotImplementedError: "OL_NOT_IMPLEMENTED",
}


def _classify(exc: BaseException) -> str:
    """Map an exception class to a stable, opaque error code."""
    for klass, code in _ERROR_CODE_MAP.items():
        if isinstance(exc, klass):
            return code
    return "OL_INTERNAL_ERROR"


def _safe_user_message(exc: BaseException) -> str:
    """User-facing message: never includes file paths, exception class,
    or any internal detail. Generic per code class.
    """
    code = _classify(exc)
    return {
        "OL_FILE_NOT_FOUND": "A required file was not found.",
        "OL_PERMISSION_DENIED": "Permission denied for the requested operation.",
        "OL_INVALID_INPUT": "The request input was invalid.",
        "OL_MISSING_KEY": "A required key was missing from the input.",
        "OL_TIMEOUT": "The operation timed out.",
        "OL_NOT_IMPLEMENTED": "The requested feature is not yet implemented.",
        "OL_INTERNAL_ERROR": "An internal error occurred. Check server logs.",
    }.get(code, "An internal error occurred. Check server logs.")


def mcp_error_boundary(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: log full traceback server-side; return opaque error JSON.

    Use on any OL MCP tool that returns a JSON string. The wrapped function
    may return a dict, str (already JSON), or any other JSON-serializable
    value. The wrapper ensures that the return is always a JSON string.
    """

    @functools.wraps(fn)
    async def async_wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            _logger.exception(
                "MCP tool %s raised: %s",
                getattr(fn, "__name__", "<unknown>"),
                exc,
            )
            code = _classify(exc)
            payload = {
                "success": False,
                "error_code": code,
                "message": _safe_user_message(exc),
            }
            return json.dumps(payload, ensure_ascii=False)

    @functools.wraps(fn)
    def sync_wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            _logger.exception(
                "MCP tool %s raised: %s",
                getattr(fn, "__name__", "<unknown>"),
                exc,
            )
            code = _classify(exc)
            payload = {
                "success": False,
                "error_code": code,
                "message": _safe_user_message(exc),
            }
            return json.dumps(payload, ensure_ascii=False)

    if inspect.iscoroutinefunction(fn):
        return async_wrapper
    return sync_wrapper
