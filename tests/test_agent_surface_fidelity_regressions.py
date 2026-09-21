"""Regression tests for MCP agent-surface fidelity defects C2, C4, and OL#96.

C2 — ``OL_PATH_DENIED`` error-code mapping. A sandbox path denial raises
``PathDeniedError`` (a subclass of ``ValueError``); ``_classify`` must map
it to the stable ``OL_PATH_DENIED`` code, not to the generic
``OL_INVALID_INPUT`` inherited from ``ValueError``. The user-facing message
must stay opaque (``PATH_DENIED_MESSAGE``), never leaking internals.

C4 — punctuation ``SyntaxWarning``. ``ol_post.punctuation`` documents
backslash sequences (``\\`\\`\\``...`) in its module docstring; if the raw
string prefix is dropped, CPython emits ``SyntaxWarning: invalid escape
sequence`` at compile time. Importing the module under
``-W error::SyntaxWarning`` turns that warning into a failure, locking the
raw-string fix.

OL#96 — ``OL_MCP_NOT_CONFIGURED`` error-code mapping. The fail-CLOSED
"MCP allowlist missing" refusal is a server-side misconfiguration, not bad
caller input; ``_classify`` must map ``MCPNotConfiguredError`` to the stable
``OL_MCP_NOT_CONFIGURED`` code (before the generic ``ValueError`` entry) and
the recovery strategy must be ``configure_environment``, never ``fix_input``.

All tests assert real behavior (real exception classification, a real
compile-time warning) — removing any production fix makes them fail.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ol_mcp._errors import (
    OL_MCP_NOT_CONFIGURED,
    OL_PATH_DENIED,
    PATH_DENIED_MESSAGE,
    MCPNotConfiguredError,
    PathDeniedError,
    _classify,
    _error_payload,
    _safe_user_message,
    mcp_error_boundary,
)

_ALLOWLIST_VARS = (
    "MCP_ALLOWED_DIRECTORIES",
    "OL_MCP_ALLOWED_DIRS",
    "OL_ALLOWED_DIRECTORIES",
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"


def test_path_denied_error_maps_to_stable_code() -> None:
    """C2: path denial classifies as OL_PATH_DENIED, not the ValueError fallback."""
    denied = PathDeniedError("x")
    assert _classify(denied) == OL_PATH_DENIED
    # Derived-class precedence: PathDeniedError is a ValueError, but the
    # more specific entry must win instead of being swallowed by ValueError.
    assert _classify(ValueError("x")) == "OL_INVALID_INPUT"
    assert _safe_user_message(denied) == PATH_DENIED_MESSAGE


def test_mcp_not_configured_maps_to_stable_code(monkeypatch) -> None:
    """OL#96: a missing allowlist classifies as OL_MCP_NOT_CONFIGURED."""
    for var in _ALLOWLIST_VARS:
        monkeypatch.delenv(var, raising=False)

    from ol_mcp.security import get_default_validator

    with pytest.raises(MCPNotConfiguredError) as excinfo:
        get_default_validator()
    exc = excinfo.value

    assert _classify(exc) == OL_MCP_NOT_CONFIGURED
    # Precedence guard: bare ValueError still maps to the generic code.
    assert _classify(ValueError("x")) == "OL_INVALID_INPUT"

    message = _safe_user_message(exc)
    assert "not configured" in message.lower()
    assert "/" not in message  # no path / internals leaked

    payload = _error_payload(exc)
    assert payload["success"] is False
    assert payload["error"]["code"] == OL_MCP_NOT_CONFIGURED
    assert payload["error_code"] == OL_MCP_NOT_CONFIGURED
    assert payload["recovery"]["strategy"] == "configure_environment"
    assert payload["recovery"]["strategy"] != "fix_input"


def test_mcp_not_configured_boundary_payload(monkeypatch) -> None:
    """OL#96: the full mcp_error_boundary envelope carries code + env recovery."""
    for var in _ALLOWLIST_VARS:
        monkeypatch.delenv(var, raising=False)

    from ol_mcp.security import get_default_validator

    @mcp_error_boundary
    def _boom() -> dict:
        get_default_validator()
        return {}

    payload = json.loads(_boom())

    assert payload["success"] is False
    assert payload["error"]["code"] == OL_MCP_NOT_CONFIGURED
    assert payload["recovery"]["strategy"] == "configure_environment"


def test_punctuation_module_has_no_invalid_escape_warning() -> None:
    """C4: importing ol_post.punctuation under -W error emits no SyntaxWarning."""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-W",
            "error::SyntaxWarning",
            "-c",
            "import ol_post.punctuation",
        ],
        cwd=str(_SRC_DIR),
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"ol_post.punctuation raised a compile-time warning:\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
