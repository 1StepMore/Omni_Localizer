"""Custom exceptions for Omni-Localizer."""

from ol_core.exceptions import OLBaseError, RestoreFailedError, FormatNotSupportedError, TranslationError


class HashMismatchError(OLBaseError):
    """Raised when checkpoint hash doesn't match source file."""
    pass


__all__ = ["OLBaseError", "HashMismatchError", "RestoreFailedError", "FormatNotSupportedError", "TranslationError"]