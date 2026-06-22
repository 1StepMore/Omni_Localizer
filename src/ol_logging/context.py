"""Async-safe context variables for logging."""

from contextvars import ContextVar

import structlog

current_file: ContextVar[str] = ContextVar('current_file', default='')
session_id: ContextVar[str] = ContextVar('session_id', default='')
batch_id: ContextVar[str] = ContextVar('batch_id', default='')
request_id: ContextVar[str] = ContextVar('request_id', default='')


def set_file_context(filename: str) -> None:
    """Set current file context."""
    current_file.set(filename)


def set_session_context(sid: str) -> None:
    """Set session ID context."""
    session_id.set(sid)


def set_batch_context(bid: str) -> None:
    """Set batch ID context."""
    batch_id.set(bid)


def set_request_id(rid: str) -> None:
    """Set request_id context (also pushed to structlog's contextvars)."""
    request_id.set(rid)
    structlog.contextvars.bind_contextvars(request_id=rid)


def bind_request_id(rid: str) -> None:
    """Bind request_id to structlog's contextvars (auto-emitted in JSON)."""
    request_id.set(rid)
    structlog.contextvars.bind_contextvars(request_id=rid)


def clear_request_id() -> None:
    """Clear the request_id from the current context."""
    request_id.set('')
    structlog.contextvars.unbind_contextvars('request_id')


def clear_context() -> None:
    """Clear all context variables."""
    current_file.set('')
    session_id.set('')
    batch_id.set('')
    clear_request_id()
