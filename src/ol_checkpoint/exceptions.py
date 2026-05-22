"""Custom exceptions for Omni-Localizer."""

from ol_core.exceptions import (
    FormatNotSupportedError,
    OLBaseError,
    RestoreFailedError,
    TranslationError,
)


class HashMismatchError(OLBaseError):
    """Raised when checkpoint hash doesn't match source file."""

    pass


__all__ = ["FormatNotSupportedError", "HashMismatchError", "OLBaseError", "RestoreFailedError", "TranslationError"]
