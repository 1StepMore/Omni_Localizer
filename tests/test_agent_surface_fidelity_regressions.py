"""Regression tests for MCP agent-surface fidelity defects C2 and C4.

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

Both tests assert real behavior (real exception classification, a real
compile-time warning) — removing either production fix makes them fail.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ol_mcp._errors import (
    OL_PATH_DENIED,
    PATH_DENIED_MESSAGE,
    PathDeniedError,
    _classify,
    _safe_user_message,
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
