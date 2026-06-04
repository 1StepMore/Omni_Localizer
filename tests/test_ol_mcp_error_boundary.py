"""C12: tests for the @mcp_error_boundary decorator.

The decorator must:
- Log the full traceback server-side (not assert specific log calls here;
  just verify the original exception is not silently dropped).
- Return a response that does NOT include the original exception message
  or any internal path/exception class info to the client.
- Include a stable, opaque error_code so clients can react programmatically.
"""

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_REPO_ROOT = Path(__file__).parent.parent.parent
_OL_SRC = _REPO_ROOT / "src"
_OPP_SRC = _REPO_ROOT / "Omni_Pre_Processor" / "src"
if str(_OL_SRC) not in sys.path:
    sys.path.insert(0, str(_OL_SRC))
if str(_OPP_SRC) not in sys.path:
    sys.path.insert(0, str(_OPP_SRC))


class TestOLErrorBoundary:
    """C12: OL MCP tool errors must not leak internal details."""

    def test_ol_error_boundary_does_not_leak_exception_message(self, caplog):
        """A tool that raises a low-level exception must return an opaque
        error code; the original message must not appear in the response.
        """
        from ol_mcp import _errors
        from ol_mcp._errors import mcp_error_boundary

        # Define a fake tool decorated with mcp_error_boundary
        @mcp_error_boundary
        async def fake_tool(params):
            raise ValueError("internal secret: /home/user/.ssh/id_rsa content")

        result_str = asyncio.run(fake_tool(None))
        import json
        result = json.loads(result_str)
        assert result["success"] is False
        # The secret must NOT appear in the response
        assert "/home/user/.ssh/id_rsa" not in result_str
        assert "internal secret" not in result_str
        # An opaque error_code should be present
        assert "error_code" in result
        assert result["error_code"]  # non-empty

    def test_ol_error_boundary_returns_stable_error_code(self):
        """The same exception class should map to the same error_code."""
        from ol_mcp import _errors
        from ol_mcp._errors import mcp_error_boundary

        @mcp_error_boundary
        async def tool_a(params):
            raise FileNotFoundError("nope")

        @mcp_error_boundary
        async def tool_b(params):
            raise FileNotFoundError("another nope")

        import json
        r1 = json.loads(asyncio.run(tool_a(None)))
        r2 = json.loads(asyncio.run(tool_b(None)))
        # Both FileNotFoundError → same error code
        assert r1["error_code"] == r2["error_code"]

    def test_ol_error_boundary_logs_traceback(self, caplog):
        """The full traceback should be logged at ERROR level server-side."""
        from ol_mcp._errors import mcp_error_boundary

        @mcp_error_boundary
        async def tool(params):
            raise RuntimeError("explode here")

        with caplog.at_level(logging.ERROR):
            asyncio.run(tool(None))

        # caplog should have captured at least one ERROR log
        assert any(rec.levelno == logging.ERROR for rec in caplog.records)

    def test_ol_error_boundary_passes_through_success(self):
        """Successful execution must return the original result unwrapped."""
        from ol_mcp._errors import mcp_error_boundary

        @mcp_error_boundary
        async def tool(params):
            return '{"success": true, "result": 42}'

        result_str = asyncio.run(tool(None))
        assert '"success": true' in result_str or '"success":true' in result_str
        assert "42" in result_str


class TestOPPErrorBoundary:
    """C12: OPP MCP tool errors must not leak internal details."""

    def test_opp_error_boundary_does_not_leak_exception_message(self):
        """Verify the OPP error boundary module exists and works the same way."""
        # OPP has slightly different response shape (dict, not JSON string),
        # so the decorator should be designed to handle both.
        opp_mcp_dir = _REPO_ROOT / "Omni_Pre_Processor" / "src" / "opp" / "mcp"
        errors_path = opp_mcp_dir / "_errors.py"
        assert errors_path.exists(), "OPP _errors.py should exist"
        spec = importlib.util.spec_from_file_location("opp_errors", errors_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "mcp_error_boundary")

    def test_opp_error_boundary_hides_exception_message(self):
        """Apply decorator to a fake OPP-style tool and verify error message
        is opaque (does not contain the original exception text)."""
        from opp.mcp._errors import mcp_error_boundary

        @mcp_error_boundary
        async def fake_opp_tool(params):
            raise RuntimeError("internal secret: /home/user/.ssh/id_rsa")

        result = asyncio.run(fake_opp_tool(None))
        assert result["success"] is False
        assert "/home/user/.ssh/id_rsa" not in str(result)
        assert "internal secret" not in str(result)
        assert "error_code" in result
        assert result["error_code"]  # non-empty opaque code

    def test_opp_error_boundary_sync_function(self):
        """OPP also has sync tools (save_skeleton etc). Verify sync path."""
        from opp.mcp._errors import mcp_error_boundary

        @mcp_error_boundary
        def fake_opp_sync_tool(params):
            raise ValueError("/etc/passwd internal detail")

        result = fake_opp_sync_tool(None)
        assert result["success"] is False
        assert "/etc/passwd" not in str(result)
        assert "error_code" in result
