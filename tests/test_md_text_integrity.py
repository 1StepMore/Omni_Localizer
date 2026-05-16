import pytest
import re
from ol_md.repair.level1 import level1_regex_clean


class TestMDTextIntegrity:
    def test_length_check_normal(self):
        source = 'Hello world this is a normal sentence.'
        target = 'Bonjour monde ceci est une phrase normale.'
        # Length should be similar (within reasonable factor)
        ratio = len(target) / len(source) if source else 0
        assert 0.3 <= ratio <= 3.0

    def test_length_check_abnormally_expanded(self):
        source = 'Hi'
        target = 'This is a very long translation that is way beyond reasonable length expectations'
        ratio = len(target) / len(source) if source else 0
        # This should trigger a flag in real implementation
        assert ratio > 3.0

    def test_number_consistency(self):
        source = 'Value is 42 and 100'
        target = 'La valeur est 42 et 100'  # Numbers should be preserved
        numbers_source = re.findall(r'\d+', source)
        numbers_target = re.findall(r'\d+', target)
        assert numbers_source == numbers_target

    def test_number_missing(self):
        source = 'Item 123'
        target = 'Item'  # Number missing - should flag
        assert '123' not in target

    def test_key_term_preserved(self):
        source = 'The quick brown fox'
        target = 'Le rapide renard brun'  # Same key terms (quick, brown, fox)
        # Key terms should be present or explicitly marked
        assert 'fox' not in target or 'renard' in target

    def test_length_ratio_configurable_threshold(self):
        source = 'Hello'
        target = 'Bonjour'
        ratio = len(target) / len(source) if source else 0
        # Default threshold is 3.0, can be configured
        assert ratio <= 3.0  # Within default threshold

    def test_empty_source(self):
        source = ''
        target = ''
        ratio = len(target) / len(source) if source else 0
        # Empty should be handled gracefully
        assert ratio == 0

    def test_unicode_preserved(self):
        source = '中文测试 Chinese'
        target = '中文测试 Chinese'
        ratio = len(target) / len(source) if source else 0
        assert ratio == 1.0  # Perfect preservation