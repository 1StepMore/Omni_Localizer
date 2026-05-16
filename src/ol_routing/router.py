"""Router module for file format-based channel routing."""
from pathlib import Path
from typing import Dict, List

from ol_core.dataclass import ChannelType
from ol_core.exceptions import FormatNotSupportedError

SUPPORTED_FORMATS = {".md", ".xliff", ".xlf"}


def route_by_extension(path: str) -> ChannelType:
    """
    Route file to MD or XLIFF channel based on file extension.

    Args:
        path: Path to the file

    Returns:
        ChannelType.MD for .md files (case-insensitive)
        ChannelType.XLIFF for .xliff and .xlf files (case-insensitive)

    Raises:
        FormatNotSupportedError: If format not supported or has double extension
    """
    p = Path(path)
    ext = p.suffix.lower()

    # Check for double extension (e.g., .md.txt has parts after extension)
    if len(p.name.split(".")) > 2:
        raise FormatNotSupportedError(path)

    if ext == ".md":
        return ChannelType.MD
    elif ext in (".xliff", ".xlf"):
        return ChannelType.XLIFF
    else:
        raise FormatNotSupportedError(path)


def route_batch(paths: List[str]) -> Dict[str, ChannelType]:
    """
    Route multiple files to their appropriate channels.

    Args:
        paths: List of file paths

    Returns:
        Dictionary mapping file paths to their ChannelType
    """
    return {p: route_by_extension(p) for p in paths}