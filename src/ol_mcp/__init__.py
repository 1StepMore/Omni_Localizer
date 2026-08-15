"""OL MCP Server - text-in/text-out MCP tools for Omni-Localizer."""
from ol_mcp.tools import mcp

__all__ = ["mcp"]
try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("omni-localizer")
except Exception:  # expected
    __version__ = "0.0.0+unknown"  # fallback for dev installs without metadata