import pytest
from ol_md.pipeline import MDRepairPipeline
from ol_core.interfaces import MockLLMRestorer


class TestRepairPipeline:
    def test_l1_stop_cascade(self):
        pipeline = MDRepairPipeline()
        result = pipeline.repair('text \x00OL_CODE_0000\x00 end', 'original', {'CODE_0000': 'code'})
        assert 'OL_CODE_0000' in result

    def test_l4_fallback(self):
        pipeline = MDRepairPipeline()
        result = pipeline.repair('text end', 'original \x00OL_CODE_0000\x00', {'CODE_0000': 'code'})
        assert 'OL_WARN' in result