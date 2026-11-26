"""OL#221: the MCP console-script entry point must actually serve.

The entry used to be ``ol_mcp.server:main`` — an ``async def``. A console
script calls ``sys.exit(entry())``, so it received a coroutine, printed it
and exited 1 before serving. ``python -m ol_mcp`` was fine, which is why
only an entry-level probe catches this.

These tests pin the *entry* behaviour, not just "the function is callable":
one drives the sync wrapper through a real stdio handshake, one checks the
fail-CLOSED refusal still happens on that path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "entry-probe", "version": "1"},
    },
}


def _run_entry(tmp_path, *, allow: bool):
    env = {k: v for k, v in os.environ.items() if "MCP_ALLOWED" not in k and "ALLOWED_DIRECTORIES" not in k}
    env.pop("OL_MCP_ALLOWED_DIRS", None)
    env.pop("OL_ALLOWED_DIRECTORIES", None)
    if allow:
        env["OL_MCP_ALLOWED_DIRS"] = str(tmp_path)
    code = "import sys; from ol_mcp.server import cli; cli()"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(_INITIALIZE) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=180,
    )
    return proc


@pytest.mark.timeout(240)
def test_console_entry_answers_initialize(tmp_path):
    """`cli()` (what ol-mcp / ol-mcp-server call) must complete a handshake."""
    proc = _run_entry(tmp_path, allow=True)
    assert "serverInfo" in proc.stdout, (
        "the console-script entry did not answer initialize\n"
        f"stdout={proc.stdout[:600]!r}\nstderr={proc.stderr[:600]!r}"
    )
    assert "coroutine" not in proc.stderr.lower(), (
        f"entry returned a coroutine instead of serving: {proc.stderr[:400]!r}"
    )


def test_console_entry_keeps_fail_closed_without_allowlist(tmp_path):
    """No allowlist => refuse to start, with a readable reason (unchanged)."""
    proc = _run_entry(tmp_path, allow=False)
    assert proc.returncode != 0, f"expected a refusal, got rc=0 (stdout={proc.stdout[:300]!r})"
    combined = (proc.stderr or "") + (proc.stdout or "")
    assert "fail-CLOSED" in combined or "allow" in combined.lower(), combined[:400]
    assert "serverInfo" not in proc.stdout
