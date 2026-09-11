"""C3 regression: OL MCP path validation is fail-CLOSED.

Wave 1 changed ``ol_mcp.security.get_default_validator()`` so that when
none of ``MCP_ALLOWED_DIRECTORIES`` / ``OL_MCP_ALLOWED_DIRS`` /
``OL_ALLOWED_DIRECTORIES`` is set, it raises ``ValueError`` (message
contains ``fail-CLOSED``) instead of silently granting cwd + /tmp.

conftest.py sets a hermetic ``MCP_ALLOWED_DIRECTORIES`` default, so the
unset-behavior test deletes all three vars before calling the factory.
"""
from __future__ import annotations

import pytest

_ALLOWLIST_VARS = (
    "MCP_ALLOWED_DIRECTORIES",
    "OL_MCP_ALLOWED_DIRS",
    "OL_ALLOWED_DIRECTORIES",
)


def _clear_allowlist(monkeypatch) -> None:
    for var in _ALLOWLIST_VARS:
        monkeypatch.delenv(var, raising=False)


def test_get_default_validator_raises_when_allowlist_unset(monkeypatch):
    """All three allowlist vars unset -> ValueError naming the fail-closed policy."""
    from ol_mcp.security import get_default_validator

    _clear_allowlist(monkeypatch)

    with pytest.raises(ValueError, match="fail-CLOSED"):
        get_default_validator()


def test_get_default_validator_uses_explicit_allowlist(monkeypatch, tmp_path):
    """MCP_ALLOWED_DIRECTORIES set -> validator resolves exactly that directory."""
    from ol_mcp.security import get_default_validator

    _clear_allowlist(monkeypatch)
    monkeypatch.setenv("MCP_ALLOWED_DIRECTORIES", str(tmp_path))

    validator = get_default_validator()

    assert tmp_path.resolve() in validator.allowed_directories


def test_mcp_server_main_refuses_to_start_without_allowlist(monkeypatch):
    """server.main() must refuse to serve when no allowlist is configured."""
    import asyncio

    from ol_mcp.server import main

    _clear_allowlist(monkeypatch)

    with pytest.raises(SystemExit, match="fail-CLOSED"):
        asyncio.run(main())
