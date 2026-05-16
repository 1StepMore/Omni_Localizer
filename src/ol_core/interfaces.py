"""LLM interface contracts for Omni-Localizer."""
from abc import ABC, abstractmethod
from typing import Dict


class LLMRestorer(ABC):
    """
    Level 3 LLM re-insertion interface.

    Phase 0: Define interface
    Phase 1/2: Use MockLLMRestorer
    Phase 3a: Use LiteLLMRestorer (real LiteLLM call)
    """

    @abstractmethod
    def restore_placeholders(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        """
        Restore placeholders to correct positions in translated text.

        Args:
            translated_text: LLM translated text (may have lost placeholders)
            original_text: Original text WITH placeholders, for positioning reference
            shield_map: Mapping of placeholder ID to original tag

        Returns:
            Text with placeholders restored to correct positions

        Raises:
            RestoreFailedError: When restoration fails (triggers Level 4 safe fallback)
        """
        pass


class MockLLMRestorer(LLMRestorer):
    """
    Phase 1/2 mock implementation.
    Does nothing - just returns translated_text unchanged.
    Level 1/2/4 handle placeholder restoration.
    """

    def restore_placeholders(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        return translated_text