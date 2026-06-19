"""OL MCP Server entry point.

Run via: python -m ol_mcp
Or install with pip install -e ".[mcp]" and run: ol-mcp
"""
import asyncio

from ol_mcp.tools import mcp

__all__ = ["main"]


async def main() -> None:
    """Run the OL MCP server with stdio transport."""
    await mcp.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())