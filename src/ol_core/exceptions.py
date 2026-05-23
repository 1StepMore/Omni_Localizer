"""Custom exceptions for Omni-Localizer."""


class OLBaseError(Exception):
    """Base exception for all Omni-Localizer errors."""

    pass


class RestoreFailedError(OLBaseError):
    """Raised when Level 3 LLM re-insertion fails.
    Triggers Level 4 safe fallback (append placeholders to sentence end).
    """

    pass


class FormatNotSupportedError(OLBaseError):
    """Raised when input format is not supported."""

    SUPPORTED_FORMATS: set[str] = {'.md', '.xliff', '.xlf'}

    def __init__(self, path: str):
        supported = ', '.join(self.SUPPORTED_FORMATS)
        super().__init__(
            f"Unsupported file format: {path}. Supported formats: {supported}",
        )


class TranslationError(OLBaseError):
    """Raised when translation fails."""

    pass
