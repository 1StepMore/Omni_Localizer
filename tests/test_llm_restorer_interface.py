"""LLM Restorer interface tests for Omni-Localizer."""
import pytest

from ol_core.exceptions import RestoreFailedError
from ol_core.interfaces import LLMRestorer, MockLLMRestorer
from ol_md.repair.level3 import LiteLLMRestorer


class TestLLMRestorerInterface:
    """Test LLM restorer interface and implementations."""

    def test_llm_restorer_is_abc(self):
        assert hasattr(LLMRestorer, 'restore_placeholders')

    def test_mock_llm_restorer_inherits(self):
        assert issubclass(MockLLMRestorer, LLMRestorer)

    def test_lite_llm_restorer_inherits(self):
        assert issubclass(LiteLLMRestorer, LLMRestorer)

    def test_mock_returns_unchanged(self):
        mock = MockLLMRestorer()
        result = mock.restore_placeholders(
            "Bonjour",
            "Hello {{_OL_TAG_1_}}",
            {"tag1": "{{_OL_CODE_abc_}}"},
        )
        assert result == "Bonjour"

    def test_mock_with_various_inputs(self):
        mock = MockLLMRestorer()

        assert mock.restore_placeholders("", "", {}) == ""

        assert mock.restore_placeholders("Hello world", "Hello world", {}) == "Hello world"

        text = "Hello {{_OL_TAG_1_}} world"
        result = mock.restore_placeholders(text, text, {"1": "code"})
        assert result == text

class TestRestoreFailedError:
    """Test RestoreFailedError exception."""

    def test_can_raise_and_catch(self):
        with pytest.raises(RestoreFailedError):
            raise RestoreFailedError("Restoration failed")

    def test_error_message(self):
        msg = "Test error message"
        try:
            raise RestoreFailedError(msg)
        except RestoreFailedError as e:
            assert str(e) == msg
