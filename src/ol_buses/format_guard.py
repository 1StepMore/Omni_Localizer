"""Input format guard for Omni-Localizer."""
from pathlib import Path

SUPPORTED_FORMATS: set[str] = {'.md', '.xliff', '.xlf'}

class FormatNotSupportedError(Exception):
    """Raised when input format is not supported."""

    def __init__(self, file_path: str):
        supported = ', '.join(SUPPORTED_FORMATS)
        super().__init__(
            f"Unsupported file format: {file_path}. "
            f"Supported formats: {supported}",
        )
        self.file_path = file_path
        self.supported_formats = SUPPORTED_FORMATS.copy()

def is_supported(file_path: str) -> bool:
    """Check if file format is supported.

    Args:
        file_path: Path to file

    Returns:
        True if format is supported (.md, .xliff, .xlf)

    """
    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_FORMATS

def validate_input_format(file_path: str) -> str:
    """Validate input format and return channel type.

    Args:
        file_path: Path to file

    Returns:
        Channel type: 'md' or 'xliff'

    Raises:
        FormatNotSupportedError: If format not supported

    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == '.md':
        return 'md'
    elif ext in ('.xliff', '.xlf'):
        return 'xliff'
    else:
        raise FormatNotSupportedError(file_path)

def get_supported_formats() -> set[str]:
    """Get copy of supported format extensions.

    Returns:
        Set of supported extensions (e.g., {'.md', '.xliff', '.xlf'})

    """
    return SUPPORTED_FORMATS.copy()
