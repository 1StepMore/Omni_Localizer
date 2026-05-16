"""Omni-Localizer core data structures and interfaces."""
from ol_core.dataclass import (
    ChannelType,
    TranslationUnit,
    TranslationContext,
    RepairContext,
    EvaluationResult,
)
from ol_core.exceptions import (
    OLBaseError,
    RestoreFailedError,
    FormatNotSupportedError,
    TranslationError,
)
from ol_core.interfaces import LLMRestorer, MockLLMRestorer

__all__ = [
    "ChannelType",
    "TranslationUnit",
    "TranslationContext",
    "RepairContext",
    "EvaluationResult",
    "OLBaseError",
    "RestoreFailedError",
    "FormatNotSupportedError",
    "TranslationError",
    "LLMRestorer",
    "MockLLMRestorer",
]