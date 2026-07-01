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
