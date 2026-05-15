from abc import ABC, abstractmethod
from typing import Dict

class LLMRestorer(ABC):

    @abstractmethod
    def restore_placeholders(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        pass

class MockLLMRestorer(LLMRestorer):

    def restore_placeholders(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        return translated_text

class LiteLLMRestorer(LLMRestorer):

    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.0):
        self.model = model
        self.temperature = temperature

    def restore_placeholders(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        return translated_text