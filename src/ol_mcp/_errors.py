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
import time
from dataclasses import dataclass
from typing import Any, Callable

_logger = logging.getLogger("ol_mcp.errors")

# Stable error code for a path outside the MCP allowed-directories sandbox.
# Do not change the string — clients switch on it. Mirrors OPP_PATH_DENIED.
OL_PATH_DENIED = "OL_PATH_DENIED"
PATH_DENIED_MESSAGE = "Path is not within the allowed directories."


class PathDeniedError(ValueError):
    """Raised when a path falls outside the MCP allowed-directories sandbox."""


# Stable, opaque error code mapping. Adding new codes is fine; do not
# change the strings (clients may switch on them).
_ERROR_CODE_MAP: dict[type, str] = {
    FileNotFoundError: "OL_FILE_NOT_FOUND",
    PermissionError: "OL_PERMISSION_DENIED",
    PathDeniedError: OL_PATH_DENIED,
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


# ── R-09: recovery hints ─────────────────────────────────────────────
# Hints are static constants: never interpolate the exception message or
# caller-controlled data (prompt-injection safety). Contract-tested by
# tests/contract/test_recovery_hints_contract.py.


@dataclass(frozen=True, slots=True)
class RecoveryHint:
    """A recoverability hint attached to a stable error code."""

    strategy: str
    hint: str


RECOVERY_HINTS: dict[str, RecoveryHint] = {
    "OL_FILE_NOT_FOUND": RecoveryHint(
        "fix_input",
        "Verify the glossary, TMX, or config file path exists, then re-issue.",
    ),
    "OL_PERMISSION_DENIED": RecoveryHint(
        "fix_input",
        "Check file permissions for the server process, then re-issue.",
    ),
    "OL_PATH_DENIED": RecoveryHint(
        "use_allowed_path",
        "Set MCP_ALLOWED_DIRECTORIES to include the path, or use a path already "
        "inside it, then re-issue.",
    ),
    "OL_INVALID_INPUT": RecoveryHint(
        "fix_input",
        "Validate the request against the tool's input schema; retry only if the "
        "LLM output was transient.",
    ),
    "OL_MISSING_KEY": RecoveryHint(
        "fix_input",
        "Add the missing required field from the tool's input schema, then re-issue.",
    ),
    "OL_TIMEOUT": RecoveryHint(
        "retry",
        "Retry, or raise the model timeout for large batches.",
    ),
    "OL_NOT_IMPLEMENTED": RecoveryHint(
        "abort",
        "Do not retry; this code path is not implemented. File a feature request.",
    ),
    "OL_INTERNAL_ERROR": RecoveryHint(
        "report_bug",
        "Check server logs for the traceback; retry once only if the failure looks "
        "transient.",
    ),
    "OL_UNKNOWN_TOOL": RecoveryHint(
        "fix_input",
        "Call one of the advertised OL tools; check the tool name spelling.",
    ),
    "AUTH_FAILED": RecoveryHint(
        "reissue_with_auth",
        "Re-issue the call with the correct auth_token matching MCP_SHARED_SECRET.",
    ),
    "RATE_LIMITED": RecoveryHint(
        "retry",
        "Wait for the rate-limit window to reset, then retry with lower concurrency.",
    ),
}

#: Every error code this module can emit — including AUTH_FAILED /
#: RATE_LIMITED / OL_UNKNOWN_TOOL, raised by the server's auth,
#: rate-limit, and dispatch paths rather than by ``_ERROR_CODE_MAP``.
DECLARED_ERROR_CODES: frozenset[str] = (
    frozenset(_ERROR_CODE_MAP.values())
    | {"OL_INTERNAL_ERROR", "OL_UNKNOWN_TOOL", "AUTH_FAILED", "RATE_LIMITED"}
)

_FALLBACK_RECOVERY = RecoveryHint(
    "report_bug",
    "Unknown error code; inspect server logs for the traceback and file a bug report.",
)


def recovery_for(code: str) -> dict[str, str]:
    """Return the ``{strategy, hint}`` recovery envelope for *code*.

    Unknown codes receive a safe ``report_bug`` fallback, so every error
    envelope always carries a recovery object.
    """
    rec = RECOVERY_HINTS.get(code, _FALLBACK_RECOVERY)
    return {"strategy": rec.strategy, "hint": rec.hint}


def _safe_user_message(exc: BaseException) -> str:
    """User-facing message: never includes file paths, exception class,
    or any internal detail. Generic per code class.
    """
    code = _classify(exc)
    return {
        "OL_FILE_NOT_FOUND": "A required file was not found.",
        "OL_PERMISSION_DENIED": "Permission denied for the requested operation.",
        "OL_PATH_DENIED": PATH_DENIED_MESSAGE,
        "OL_INVALID_INPUT": "The request input was invalid.",
        "OL_MISSING_KEY": "A required key was missing from the input.",
        "OL_TIMEOUT": "The operation timed out.",
        "OL_NOT_IMPLEMENTED": "The requested feature is not yet implemented.",
        "OL_INTERNAL_ERROR": "An internal error occurred. Check server logs.",
    }.get(code, "An internal error occurred. Check server logs.")


def _error_payload(exc: BaseException) -> dict[str, Any]:
    """Build the JSON-ready error payload for *exc* (code, message, recovery)."""
    code = _classify(exc)
    msg = _safe_user_message(exc)
    return {
        "success": False,
        "error": {"code": code, "message": msg},
        "error_code": code,
        "message": msg,
        "recovery": recovery_for(code),
    }


def mcp_error_boundary(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: log full traceback server-side; return opaque error JSON.

    Use on any OL MCP tool that returns a JSON string. The wrapped function
    may return a dict, str (already JSON), or any other JSON-serializable
    value. The wrapper ensures that the return is always a JSON string.
    """
    tool_name = getattr(fn, "__name__", "<unknown>")

    def _record_metrics(duration_ms: float, success: bool) -> None:
        # 2026-06-18 round 16 Phase B5: Prometheus metrics.
        try:
            import os as _os
            _suite_root = _os.path.dirname(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
            )
            if _suite_root not in _os.sys.path:
                _os.sys.path.insert(0, _suite_root)
            from omni_metrics import record_tool_call
            record_tool_call("ol", tool_name, duration_ms, success)
        except Exception:  # expected — metrics recording is best-effort
            pass

    @functools.wraps(fn)
    async def async_wrapper(*args, **kwargs):
        t0 = time.time()
        try:
            result = await fn(*args, **kwargs)
            _record_metrics((time.time() - t0) * 1000, True)
            return result
        except Exception as exc:
            _record_metrics((time.time() - t0) * 1000, False)
            _logger.exception(
                "MCP tool %s raised: %s",
                tool_name,
                exc,
            )
            return json.dumps(_error_payload(exc), ensure_ascii=False)

    @functools.wraps(fn)
    def sync_wrapper(*args, **kwargs):
        t0 = time.time()
        try:
            result = fn(*args, **kwargs)
            _record_metrics((time.time() - t0) * 1000, True)
            return result
        except Exception as exc:
            _record_metrics((time.time() - t0) * 1000, False)
            _logger.exception(
                "MCP tool %s raised: %s",
                tool_name,
                exc,
            )
            return json.dumps(_error_payload(exc), ensure_ascii=False)

    if inspect.iscoroutinefunction(fn):
        return async_wrapper
    return sync_wrapper
