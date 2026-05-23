"""Unit tests for ol_terminology.extractor module."""
from unittest.mock import MagicMock, patch

from ol_terminology.extractor import extract_terms


class TestExtractTermsEmptyInput:
    """Test extract_terms with empty input."""

    def test_extract_terms_returns_dict(self):
        result = extract_terms([])
        assert isinstance(result, dict)
        assert result == {}


class TestExtractTermsKeyBERTFallback:
    """Test KeyBERT to YAKE fallback behavior."""

    def test_extract_terms_keybert_fallback(self):
        """Test KeyBERT unavailable → YAKE fallback path."""
        mock_extractor = MagicMock()
        mock_extractor.extract_keywords.return_value = [
            ("machine learning", 0.85),
            ("natural language processing", 0.78),
        ]
        mock_yake_module = MagicMock(KeywordExtractor=MagicMock(return_value=mock_extractor))

        with patch("ol_terminology.extractor._KEYBERT_AVAILABLE", False):
            with patch("ol_terminology.extractor._YAKE_AVAILABLE", True):
                with patch("ol_terminology.extractor.yake", mock_yake_module):
                    result = extract_terms(["test text"])

                    assert result == {
                        "machine learning": 0.85,
                        "natural language processing": 0.78,
                    }


class TestExtractTermsFiltersLowScore:
    """Test filtering of low score terms."""

    def test_extract_terms_filters_low_score_terms(self):
        with patch("ol_terminology.extractor._KEYBERT_AVAILABLE", True):
            mock_model = MagicMock()
            mock_model.extract_keywords.return_value = [
                ("important term", 0.9),
                ("another term", 0.7),
                ("low priority term", 0.1),
            ]

            with patch("ol_terminology.extractor.KeyBERT", return_value=mock_model):
                result = extract_terms(["some test content"])

                assert len(result) == 3
                assert "important term" in result
                assert "low priority term" in result


class TestExtractTermsSorting:
    """Test term sorting by importance score."""

    def test_extract_terms_returns_sorted_terms(self):
        with patch("ol_terminology.extractor._KEYBERT_AVAILABLE", True):
            mock_model = MagicMock()
            mock_model.extract_keywords.return_value = [
                ("third term", 0.3),
                ("first term", 0.9),
                ("second term", 0.6),
            ]

            with patch("ol_terminology.extractor.KeyBERT", return_value=mock_model):
                result = extract_terms(["test content"])

                assert "first term" in result
                assert "second term" in result
                assert "third term" in result
                assert result["first term"] == 0.9


class TestExtractTermsYAKEFallback:
    """Test YAKE fallback when KeyBERT fails."""

    def test_yake_used_when_keybert_fails(self):
        with patch("ol_terminology.extractor._KEYBERT_AVAILABLE", True):
            mock_model = MagicMock()
            mock_model.extract_keywords.side_effect = Exception("KeyBERT failed")

            with patch("ol_terminology.extractor.KeyBERT", return_value=mock_model):
                with patch("ol_terminology.extractor._YAKE_AVAILABLE", True):
                    mock_yake_extractor = MagicMock()
                    mock_yake_extractor.extract_keywords.return_value = [
                        ("fallback term", 0.75),
                    ]

                    with patch("ol_terminology.extractor.yake") as mock_yake_module:
                        mock_yake_module.KeywordExtractor.return_value = mock_yake_extractor

                        result = extract_terms(["test content"])

                        assert result == {"fallback term": 0.75}


class TestExtractTermsBothUnavailable:
    """Test behavior when both extractors are unavailable."""

    def test_returns_empty_dict_when_both_unavailable(self):
        with patch("ol_terminology.extractor._KEYBERT_AVAILABLE", False):
            with patch("ol_terminology.extractor._YAKE_AVAILABLE", False):
                result = extract_terms(["some text"])
                assert result == {}