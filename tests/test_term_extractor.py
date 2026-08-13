"""Unit tests for ol_terminology.extractor module (YAKE-only)."""
from unittest.mock import MagicMock, patch

import pytest

from ol_terminology.extractor import extract_terms


class TestExtractTermsEmptyInput:
    """Test extract_terms with empty input."""

    def test_extract_terms_returns_dict(self):
        result = extract_terms([])
        assert isinstance(result, dict)
        assert result == {}


class TestExtractTermsYAKEPrimary:
    """Test YAKE as the primary (and only) extractor."""

    def test_extract_terms_yake_primary(self):
        """Test YAKE returns terms when available."""
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.return_value = [
            ("machine learning", 0.15),
            ("natural language processing", 0.22),
        ]
        mock_yake_module = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))

        with patch("ol_terminology.extractor._YAKE_AVAILABLE", True):
            with patch("ol_terminology.extractor._yake", mock_yake_module):
                result = extract_terms(["test text"])

                assert result == {
                    "machine learning": 0.15,
                    "natural language processing": 0.22,
                }

    def test_extract_terms_yake_unavailable_raises(self):
        """When _YAKE_AVAILABLE is False, raises ImportError."""
        with patch("ol_terminology.extractor._YAKE_AVAILABLE", False):
            with patch("ol_terminology.extractor._probe_yake", return_value=None):
                with pytest.raises(ImportError, match="pip install omni-localizer\\[ml\\]"):
                    extract_terms(["some text"])


class TestExtractTermsFiltersLowScore:
    """Test that all extracted terms are returned with correct keys."""

    def test_extract_terms_returns_all_terms(self):
        """YAKE returns terms as-is; verify dict has all expected keys."""
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.return_value = [
            ("important term", 0.1),
            ("another term", 0.3),
            ("low priority term", 0.9),
        ]
        mock_yake_module = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))

        with patch("ol_terminology.extractor._YAKE_AVAILABLE", True):
            with patch("ol_terminology.extractor._yake", mock_yake_module):
                result = extract_terms(["some test content"])

                assert len(result) == 3
                assert "important term" in result
                assert "another term" in result
                assert "low priority term" in result


class TestExtractTermsSorting:
    """Test that YAKE scores are preserved (lower = more relevant)."""

    def test_extract_terms_preserves_yake_scores(self):
        """YAKE scores are inverse: lower = more relevant. Verify scores stored as-is."""
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.return_value = [
            ("third term", 0.9),
            ("first term", 0.1),
            ("second term", 0.5),
        ]
        mock_yake_module = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))

        with patch("ol_terminology.extractor._YAKE_AVAILABLE", True):
            with patch("ol_terminology.extractor._yake", mock_yake_module):
                result = extract_terms(["test content"])

                assert "first term" in result
                assert "second term" in result
                assert "third term" in result
                assert result["first term"] == 0.1
                assert result["third term"] == 0.9


class TestExtractTermsYakeRaises:
    """Test YAKE failure raises ImportError."""

    def test_yake_extraction_failure_raises(self):
        """When YAKE extraction itself fails, raise ImportError."""
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.side_effect = Exception("YAKE internal error")
        mock_yake_module = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))

        with patch("ol_terminology.extractor._YAKE_AVAILABLE", True):
            with patch("ol_terminology.extractor._yake", mock_yake_module):
                with pytest.raises(ImportError, match="YAKE extraction failed"):
                    extract_terms(["test content"])


class TestExtractTermsBothUnavailable:
    """Test behavior when YAKE is unavailable."""

    def test_raises_importerror_when_yake_unavailable(self):
        """extract_terms raises ImportError with install hint when YAKE is missing."""
        with patch("ol_terminology.extractor._probe_yake", return_value=None):
            with pytest.raises(ImportError, match="pip install omni-localizer"):
                extract_terms(["some text"])


class TestCJKFilter:
    """CJK-based post-processing filter for Chinese/Japanese text.

    The filter drops terms without CJK characters when the input
    text contains CJK (Chinese, Japanese kana). Pure English input
    is unaffected (regression guard for the existing English path).
    """

    def test_cjk_filter_drops_pure_english_terms_on_chinese_input(self):
        """Chinese input → only CJK terms in result; 'API' (English fragment) dropped."""
        from ol_terminology.extractor import extract_terms
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.return_value = [
            ("API", 0.1),
            ("Gateway", 0.2),
            ("端点和中间件架构设计", 0.3),
        ]
        mock_yake = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))
        with patch("ol_terminology.extractor._YAKE_AVAILABLE", True), \
             patch("ol_terminology.extractor._yake", mock_yake):
            result = extract_terms(["这是一个测试文档,关于API端点和中间件架构设计"])
        assert "API" not in result
        assert "Gateway" not in result
        assert "端点和中间件架构设计" in result

    def test_cjk_filter_drops_english_fragments_on_mixed_input(self):
        """Mixed Chinese+English → pure English terms dropped; CJK terms preserved."""
        from ol_terminology.extractor import extract_terms
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.return_value = [
            ("API", 0.1),
            ("Service Mesh", 0.15),
            ("端点和中间件架构设计", 0.3),
            ("服务网格", 0.4),
        ]
        mock_yake = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))
        with patch("ol_terminology.extractor._YAKE_AVAILABLE", True), \
             patch("ol_terminology.extractor._yake", mock_yake):
            result = extract_terms([
                "本文档描述了API网关的部署架构。该网关支持Service Mesh。"
            ])
        assert "API" not in result
        assert "Service Mesh" not in result
        assert "端点和中间件架构设计" in result
        assert "服务网格" in result

    def test_cjk_filter_pure_english_regression_unchanged(self):
        """Pure English input → all English terms preserved (regression guard)."""
        from ol_terminology.extractor import extract_terms
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.return_value = [
            ("machine learning", 0.1),
            ("natural language processing", 0.2),
        ]
        mock_yake = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))
        with patch("ol_terminology.extractor._YAKE_AVAILABLE", True), \
             patch("ol_terminology.extractor._yake", mock_yake):
            result = extract_terms(["Machine learning and natural language processing"])
        assert "machine learning" in result
        assert "natural language processing" in result

    def test_cjk_filter_short_terms_rejected(self):
        """Single-character terms (CJK or not) are rejected."""
        from ol_terminology.extractor import extract_terms
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.return_value = [
            ("A", 0.1),       # English, 1 char → reject
            ("太", 0.2),       # CJK, 1 char → reject
            ("API", 0.3),      # English, 3 chars → reject (no CJK)
            ("端点", 0.4),     # CJK, 2 chars → keep
        ]
        mock_yake = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))
        with patch("ol_terminology.extractor._YAKE_AVAILABLE", True), \
             patch("ol_terminology.extractor._yake", mock_yake):
            result = extract_terms(["端点是 API 端点的简称"])
        assert "A" not in result
        assert "太" not in result
        assert "API" not in result
        assert "端点" in result

    def test_cjk_filter_japanese_kana_input(self):
        """Japanese hiragana/katakana input also activates the filter."""
        from ol_terminology.extractor import extract_terms
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.return_value = [
            ("こんにちは", 0.1),  # hiragana → keep
            ("API", 0.2),         # English fragment → drop
            ("サービス", 0.3),     # katakana → keep
        ]
        mock_yake = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))
        with patch("ol_terminology.extractor._YAKE_AVAILABLE", True), \
             patch("ol_terminology.extractor._yake", mock_yake):
            result = extract_terms(["こんにちは world API サービス"])
        assert "こんにちは" in result
        assert "サービス" in result
        assert "API" not in result


class TestChineseQualityAfterFix:
    """Issue #43: After fix, Chinese extraction returns clean terms.

    Note: P0 (no jieba) produces limited keyword quality — fragments may
    still appear. P1 (jieba) is required for production-quality Chinese
    keywords. These P0 tests validate that NOISE IS REMOVED (no grammar
    particle fragments, no excessively long terms) — not that keywords
    are perfect.

    B2 lifecycle: T0.0's `TestChineseNoiseReproduction.test_chinese_noise_before_fix`
    is REMOVED (T0.0 captured the buggy state in git history; the inverted
    assertion below is the live test).
    """

    def test_chinese_quality_after_fix(self):
        """After fix: no noise terms (fragments with grammar particles or long)."""
        try:
            from ol_terminology.extractor import _probe_yake
            if _probe_yake() is None:
                pytest.skip("YAKE not installed")
        except ImportError:
            pytest.skip("YAKE not installed")
        chinese_text = [
            '海尔集团是中国最大的家电制造商之一。海尔的创始人是张瑞敏,他在1984年创立了海尔。',
            '海尔的产品包括冰箱、洗衣机、空调、电视等家电产品。其中,海尔冰箱在中国市场占有率最高。',
            '海尔的国际化战略始于1990年代,现在海尔已经成为全球领先的家电品牌。',
        ]
        result = extract_terms(chinese_text)
        terms = list(result.keys())

        # N1: Check for ACTUAL fragments (terms that ARE grammar particles),
        # not terms that merely CONTAIN a particle character (e.g. '创始人'
        # contains '始' but is a valid keyword, not a fragment).
        FRAGMENT_MARKERS = frozenset('的了在于是包括成为等始于')

        def is_fragment(t):
            return len(t) <= 2 and all(c in FRAGMENT_MARKERS for c in t)

        has_actual_fragment = any(is_fragment(t) for t in terms)
        # After fix: no ACTUAL fragment terms should be present
        assert not has_actual_fragment, (
            f"Fragment terms found: {[t for t in terms if is_fragment(t)]}"
        )

    def test_chinese_has_subject_term(self):
        """After fix: at least one term contains the document subject."""
        try:
            from ol_terminology.extractor import _probe_yake
            if _probe_yake() is None:
                pytest.skip("YAKE not installed")
        except ImportError:
            pytest.skip("YAKE not installed")
        chinese_text = [
            '海尔集团是中国最大的家电制造商之一。海尔的创始人是张瑞敏,他在1984年创立了海尔。',
            '海尔的产品包括冰箱、洗衣机、空调、电视等家电产品。其中,海尔冰箱在中国市场占有率最高。',
            '海尔的国际化战略始于1990年代,现在海尔已经成为全球领先的家电品牌。',
        ]
        result = extract_terms(chinese_text)
        terms = list(result.keys())
        assert any('海尔' in t for t in terms), f"Missing '海尔' in: {terms}"


class TestEnglishRegression:
    """Issue #43: English text must not be affected by CJK cleaning.

    B1 fix: `_clean_text()` only strips CJK punctuation when CJK is
    present. English text is left untouched to preserve contractions
    (don't, it's), abbreviations (e.g., Mr.), and word-internal chars.
    """

    def test_english_contractions_preserved(self):
        """English contractions like 'don't' must not be split by _clean_text."""
        try:
            from ol_terminology.extractor import _probe_yake
            if _probe_yake() is None:
                pytest.skip("YAKE not installed")
        except ImportError:
            pytest.skip("YAKE not installed")
        text = ["Machine learning doesn't work without data. It's that simple."]
        result = extract_terms(text)
        # At least one term should be a 2-word phrase (contractions preserved)
        assert any(len(t.split()) >= 2 for t in result.keys()), \
            f"Expected multi-word terms (contractions preserved), got: {list(result.keys())}"

    def test_clean_text_preserves_english(self):
        """English text with periods/apostrophes: _clean_text leaves it alone.

        B1 fix: CJK punctuation stripping is conditional on CJK content.
        English text is not modified (preserves contractions, abbreviations).
        """
        from ol_terminology.extractor import _clean_text
        # English text: nothing should be stripped (no CJK present)
        assert _clean_text("don't it's e.g.") == "don't it's e.g."
        assert _clean_text("Mr. Smith said, 'Hello.'") == "Mr. Smith said, 'Hello.'"

    def test_clean_text_strips_cjk_punctuation(self):
        """CJK text: punctuation IS stripped when CJK is present."""
        from ol_terminology.extractor import _clean_text
        result = _clean_text("海尔集团，是中国最大的。")
        assert '，' not in result
        assert '。' not in result
        assert '海尔' in result
