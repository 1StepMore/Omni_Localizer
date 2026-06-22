"""OL MCP Server entry point.

Run via: python -m ol_mcp
Or install with pip install -e ".[mcp]" and run: ol-mcp

Phase 1.4 rewrite: switched from ``mcp.server.fastmcp.FastMCP.run_stdio_async``
(which hangs in this environment on the first JSON-RPC handshake) to the
raw ``mcp.server.Server`` + ``stdio_server()`` pattern that
``tests/mcp/test_minimal_stdio.py`` already validated as working.
"""
from __future__ import annotations

import anyio
from mcp import stdio_server

from ol_mcp.health import start_health_server as _health_start
from ol_mcp.tools import mcp


async def main() -> None:
    """Run the OL MCP server with stdio transport."""
    _health_start()
    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream,
            mcp.create_initialization_options(),
            raise_exceptions=False,
        )


if __name__ == "__main__":
    anyio.run(main)
