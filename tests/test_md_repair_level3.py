import pytest
from ol_md.repair.level3 import level3_llm_restore
from ol_core.interfaces import MockLLMRestorer


class TestRepairLevel3:
    def test_delegation_to_mock(self):
        result = level3_llm_restore('Hello world', 'Hello world', {}, MockLLMRestorer())
        assert result == 'Hello world'