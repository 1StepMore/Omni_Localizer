"""Tests for Smart Routing Engine."""

import pytest

from ol_core.dataclass import ChannelType
from ol_core.exceptions import FormatNotSupportedError
from ol_routing.router import route_batch, route_by_extension


class TestRouteByExtension:
    """Test route_by_extension function."""

    def test_md_extension_returns_md_channel(self):
        """Test .md files return ChannelType.MD."""
        assert route_by_extension("file.md") == ChannelType.MD
        assert route_by_extension("/path/to/file.md") == ChannelType.MD

    def test_uppercase_md_normalized(self):
        """Test uppercase .MD is normalized to lowercase."""
        assert route_by_extension("file.MD") == ChannelType.MD
        assert route_by_extension("file.Md") == ChannelType.MD
        assert route_by_extension("file.mD") == ChannelType.MD

    def test_xliff_extension_returns_xliff_channel(self):
        """Test .xliff files return ChannelType.XLIFF."""
        assert route_by_extension("file.xliff") == ChannelType.XLIFF
        assert route_by_extension("/path/to/file.xliff") == ChannelType.XLIFF

    def test_xlf_extension_returns_xliff_channel(self):
        """Test .xlf files return ChannelType.XLIFF."""
        assert route_by_extension("file.xlf") == ChannelType.XLIFF

    def test_uppercase_xliff_normalized(self):
        """Test uppercase .XLIFF and .XLF are normalized."""
        assert route_by_extension("file.XLIFF") == ChannelType.XLIFF
        assert route_by_extension("file.XLF") == ChannelType.XLIFF

    def test_unsupported_format_raises_error(self):
        """Test unsupported formats raise FormatNotSupportedError."""
        unsupported = ["file.txt", "file.json", "file.docx", "file.pdf"]
        for path in unsupported:
            with pytest.raises(FormatNotSupportedError) as exc_info:
                route_by_extension(path)
            assert "Unsupported file format" in str(exc_info.value)

    def test_double_extension_rejected(self):
        """Test double extension like .md.txt is rejected."""
        with pytest.raises(FormatNotSupportedError) as exc_info:
            route_by_extension("file.md.txt")
        assert "Unsupported file format" in str(exc_info.value)

    def test_multiple_dots_rejected(self):
        """Test files with multiple dots are rejected."""
        with pytest.raises(FormatNotSupportedError):
            route_by_extension("file.backup.md")
        with pytest.raises(FormatNotSupportedError):
            route_by_extension("archive.tar.gz")


class TestRouteBatch:
    """Test route_batch function."""

    def test_batch_routing_returns_dict(self):
        """Test batch routing returns dictionary of paths to ChannelTypes."""
        paths = ["file1.md", "file2.xliff"]
        result = route_batch(paths)
        assert isinstance(result, dict)
        assert len(result) == 2
        assert result["file1.md"] == ChannelType.MD
        assert result["file2.xliff"] == ChannelType.XLIFF

    def test_batch_routing_multiple_files(self):
        """Test batch routing with multiple files."""
        paths = ["a.md", "b.xlf", "c.xliff", "d.MD"]
        result = route_batch(paths)
        assert result["a.md"] == ChannelType.MD
        assert result["b.xlf"] == ChannelType.XLIFF
        assert result["c.xliff"] == ChannelType.XLIFF
        assert result["d.MD"] == ChannelType.MD

    def test_batch_routing_preserves_path_keys(self):
        """Test batch routing preserves original path strings as keys."""
        paths = ["/absolute/path.md", "relative/path.xliff"]
        result = route_batch(paths)
        assert "/absolute/path.md" in result
        assert "relative/path.xliff" in result

    def test_batch_routing_error_propagates(self):
        """Test batch routing propagates FormatNotSupportedError."""
        paths = ["valid.md", "invalid.xyz"]
        with pytest.raises(FormatNotSupportedError):
            route_batch(paths)
