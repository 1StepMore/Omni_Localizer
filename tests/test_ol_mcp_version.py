"""Test P1-T1: OL MCP __version__ should match the installed package version."""
import re


def test_ol_mcp_version_is_not_hardcoded_zero_one():
    """OL MCP __version__ must NOT be hardcoded '0.1.0' (the package is at 0.7.0)."""
    from ol_mcp import __version__
    assert __version__ != "0.1.0", (
        f"ol_mcp.__version__ is hardcoded '0.1.0' but OL is at a different version. "
        f"Use importlib.metadata to derive from the installed package."
    )


def test_ol_mcp_version_matches_installed_package():
    """OL MCP __version__ should match the installed omni-localizer version."""
    from ol_mcp import __version__
    from importlib.metadata import version as pkg_version
    installed = pkg_version("omni-localizer")
    assert __version__ == installed, (
        f"ol_mcp.__version__ ({__version__}) does not match installed omni-localizer ({installed})"
    )


def test_ol_mcp_version_is_semver():
    """Version must be a valid semver string (X.Y.Z)."""
    from ol_mcp import __version__
    assert re.match(r"^\d+\.\d+\.\d+", __version__), (
        f"__version__ ({__version__!r}) is not a valid semver string"
    )
