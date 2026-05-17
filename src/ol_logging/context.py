"""Async-safe context variables for logging."""

from contextvars import ContextVar

current_file: ContextVar[str] = ContextVar('current_file', default='')
session_id: ContextVar[str] = ContextVar('session_id', default='')
batch_id: ContextVar[str] = ContextVar('batch_id', default='')


def set_file_context(filename: str) -> None:
    """Set current file context."""
    current_file.set(filename)


def set_session_context(sid: str) -> None:
    """Set session ID context."""
    session_id.set(sid)


def set_batch_context(bid: str) -> None:
    """Set batch ID context."""
    batch_id.set(bid)


def clear_context() -> None:
    """Clear all context variables."""
    current_file.set('')
    session_id.set('')
    batch_id.set('')