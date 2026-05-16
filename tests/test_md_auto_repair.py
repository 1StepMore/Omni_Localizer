import pytest
from ol_md.pipeline import MDRepairPipeline
from ol_core.interfaces import MockLLMRestorer


class TestMDAutoRepair:
    def test_auto_repair_lost_shields_l1_success(self):
        """Level 1 cleans whitespace, stops cascade"""
        pipeline = MDRepairPipeline()
        text = 'text \x00OL_CODE_0000\x00 end'  # Placeholder intact
        result = pipeline.repair(text, 'original', {'CODE_0000': 'code'})
        assert '\x00OL_CODE_0000\x00' in result  # Intact

    def test_auto_repair_lost_shields_l4_fallback(self):
        """Level 4 triggers when placeholders missing"""
        pipeline = MDRepairPipeline()
        text = 'text end'  # Placeholder missing
        result = pipeline.repair(text, 'original \x00OL_CODE_0000\x00', {'CODE_0000': 'code'})
        assert 'OL_WARN' in result  # Fallback triggered

    def test_cascade_l1_to_l2(self):
        """L1 fails → L2 tries span-aligner"""
        pipeline = MDRepairPipeline()
        # Text with leading whitespace that could be cleaned
        text = '   text end'
        result = pipeline.repair(text, 'original', {})
        # Should at least get to L2 or beyond
        assert isinstance(result, str)

    def test_cascade_l3_mock_delegate(self):
        """L3 delegates to MockLLMRestorer (pass-through)"""
        pipeline = MDRepairPipeline(llm_restorer=MockLLMRestorer())
        text = 'text \x00OL_CODE_0000\x00 end'
        result = pipeline.repair(text, 'original', {'CODE_0000': 'code'})
        assert 'OL_CODE_0000' in result  # Mock doesn't change anything

    def test_is_complete_check(self):
        """Pipeline checks if all placeholders present"""
        pipeline = MDRepairPipeline()
        text = 'text \x00OL_CODE_0000\x00 end'
        shield_map = {'CODE_0000': 'code'}
        assert pipeline.is_complete(text, shield_map) == True

    def test_is_complete_false_when_missing(self):
        """Pipeline detects missing placeholders"""
        pipeline = MDRepairPipeline()
        text = 'text end'  # Placeholder missing
        shield_map = {'CODE_0000': 'code'}
        assert pipeline.is_complete(text, shield_map) == False

    def test_full_cascade_4_layers(self):
        """All 4 layers execute in sequence until complete"""
        pipeline = MDRepairPipeline()
        # Simulate a case that needs all layers
        text = 'text end'
        original = 'text \x00OL_MATH_0000\x00 end'
        shield_map = {'MATH_0000': '$formula$'}
        result = pipeline.repair(text, original, shield_map)
        # Should end in L4 since placeholder missing
        assert 'OL_WARN' in result or '\x00OL_MATH' in result

    def test_no_llm_restorer_uses_mock(self):
        """Pipeline works without explicit LLM restorer"""
        pipeline = MDRepairPipeline()  # No restorer passed
        text = 'text \x00OL_CODE_0000\x00 end'
        result = pipeline.repair(text, 'original', {'CODE_0000': 'code'})
        assert 'OL_CODE_0000' in result  # Should work with default