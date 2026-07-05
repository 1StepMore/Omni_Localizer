"""Tests for ModelPool source language residual detection (Issue #49)."""
import pytest
from ol_pool.router import (
    has_source_language_residual,
    ModelPoolSourceLanguageResidualError,
)


class TestSourceLanguageResidual:
    """Tests for the has_source_language_residual helper."""

    # ── zh→en branch (existing) ──────────────────────────────────────

    def test_pure_english_passes(self):
        """Pure English text should not be flagged as residual."""
        text = "Haier is a global leader in home appliances and smart home solutions."
        assert not has_source_language_residual(text, "zh", "en")

    def test_pure_chinese_detected(self):
        """Pure Chinese text should be flagged as residual for zh->en."""
        text = "海尔是全球领先的家电和智能家居解决方案提供商。"
        assert has_source_language_residual(text, "zh", "en")

    def test_english_with_chinese_terms_passes(self):
        """English text with occasional CJK font names/terms should pass (<15%)."""
        text = "The product name is SimSun N SimHei and supports Arial Unicode MS."
        assert not has_source_language_residual(text, "zh", "en")

    def test_mixed_mostly_chinese_detected(self):
        """Mostly Chinese text should be flagged."""
        text = "海尔集团 创立于1984年，Haier Group was founded in 1984, 是一家全球领先的家电企业"
        assert has_source_language_residual(text, "zh", "en")

    def test_empty_string_passes(self):
        """Empty string should not raise."""
        assert not has_source_language_residual("", "zh", "en")

    def test_non_zh_pairs_return_false(self):
        """Non zh->en pairs should not be checked yet."""
        text = "Some English text"
        assert not has_source_language_residual(text, "en", "fr")
        assert not has_source_language_residual(text, "en", "de")

    def test_whitespace_passes(self):
        """Whitespace-only text should not be flagged."""
        assert not has_source_language_residual("   \n  ", "zh", "en")

    def test_threshold_boundary_at_15_percent(self):
        """Text with exactly 15% CJK passes; just above is flagged."""
        # 15 CJK chars + 85 ASCII = 15% ratio (passes)
        text_15pct = "\u4e00" * 15 + "a" * 85
        assert not has_source_language_residual(text_15pct, "zh", "en")
        # 16 CJK chars + 84 ASCII = 16% (flagged)
        text_16pct = "\u4e00" * 16 + "a" * 84
        assert has_source_language_residual(text_16pct, "zh", "en")

    # ── en→zh branch (new) ───────────────────────────────────────────

    def test_en2zh_pure_chinese_passes(self):
        """Pure Chinese output for en->zh should not be flagged."""
        text = "海尔是全球领先的家电和智能家居解决方案提供商。"
        assert not has_source_language_residual(text, "en", "zh")

    def test_en2zh_pure_english_detected(self):
        """Pure English output for en->zh should NOT be flagged (en->zh guard removed)."""
        text = "Haier is a global leader in home appliances and smart home solutions."
        assert not has_source_language_residual(text, "en", "zh")

    def test_en2zh_mostly_chinese_passes(self):
        """Chinese text with a few English terms should pass (<15% ASCII alpha)."""
        text = "海尔AI家电产品非常出色，质量可靠，值得购买。"  # 2/21 = ~9.5% ASCII alpha
        assert not has_source_language_residual(text, "en", "zh")

    def test_en2zh_mostly_english_detected(self):
        """Mostly English output for en->zh should NOT be flagged (en->zh guard removed)."""
        text = "Haier Group was founded in 1984. 它是一家全球领先的家电企业, operating in over 100 markets."
        assert not has_source_language_residual(text, "en", "zh")

    def test_en2zh_threshold_boundary(self):
        """All en->zh pairs return False (en->zh guard removed)."""
        text_15pct = "a" * 15 + "\u4e00" * 85
        assert not has_source_language_residual(text_15pct, "en", "zh")
        text_16pct = "a" * 16 + "\u4e00" * 84
        assert not has_source_language_residual(text_16pct, "en", "zh")

    def test_en2zh_whitespace_only_passes(self):
        """Whitespace-only text should not be flagged for en->zh."""
        assert not has_source_language_residual("   \n  ", "en", "zh")

    def test_en2zh_empty_string_passes(self):
        """Empty string should not be flagged for en->zh."""
        assert not has_source_language_residual("", "en", "zh")


class TestModelPoolResidualError:
    """Test that ModelPoolSourceLanguageResidualError is importable and raiseable."""

    def test_exception_can_be_raised(self):
        """The exception class should be raiseable."""
        with pytest.raises(ModelPoolSourceLanguageResidualError):
            raise ModelPoolSourceLanguageResidualError("test error")

    def test_exception_message(self):
        """Exception should preserve the message."""
        msg = "Translation output contains zh-language residual for en target (CJK ratio > 15%)"
        try:
            raise ModelPoolSourceLanguageResidualError(msg)
        except ModelPoolSourceLanguageResidualError as e:
            assert str(e) == msg
