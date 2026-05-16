"""COMETService tests for Omni-Localizer."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestCOMETService:
    def test_comet_service_instantiation(self):
        from ol_lqa.comet import COMETService

        service = COMETService()
        assert service.model_name == "Unbabel/XCOMET-XL"

    def test_comet_service_custom_model(self):
        from ol_lqa.comet import COMETService

        service = COMETService(model_name="Unbabel/XCOMET-XXL")
        assert service.model_name == "Unbabel/XCOMET-XXL"

    def test_model_lazy_load(self):
        from ol_lqa.comet import COMETService

        service = COMETService()
        assert service._model is None

    @patch("ol_lqa.comet.download_model")
    @patch("ol_lqa.comet.load_from_checkpoint")
    def test_ensure_model_loads(self, mock_load, mock_download):
        from ol_lqa.comet import COMETService

        mock_download.return_value = "/path/to/model"
        mock_model = MagicMock()
        mock_load.return_value = mock_model

        service = COMETService()
        model = service._ensure_model()

        mock_download.assert_called_once_with("Unbabel/XCOMET-XL")
        mock_load.assert_called_once_with("/path/to/model")
        assert model == mock_model
        assert service._model == mock_model

    @patch("ol_lqa.comet.download_model")
    @patch("ol_lqa.comet.load_from_checkpoint")
    def test_ensure_model_cached(self, mock_load, mock_download):
        from ol_lqa.comet import COMETService

        mock_download.return_value = "/path/to/model"
        mock_model = MagicMock()
        mock_load.return_value = mock_model

        service = COMETService()
        service._ensure_model()
        service._ensure_model()

        mock_download.assert_called_once()
        mock_load.assert_called_once()

    @patch("ol_lqa.comet.download_model")
    @patch("ol_lqa.comet.load_from_checkpoint")
    def test_score_xcomet_returns_float(self, mock_load, mock_download):
        from ol_lqa.comet import COMETService

        mock_download.return_value = "/path/to/model"
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.scores = [0.95]
        mock_model.predict.return_value = mock_output
        mock_load.return_value = mock_model

        service = COMETService()

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            score = loop.run_until_complete(
                service.score_xcomet("Hello", "Bonjour", "en", "fr")
            )
        finally:
            loop.close()

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    @patch("ol_lqa.comet.download_model")
    @patch("ol_lqa.comet.load_from_checkpoint")
    def test_get_mqm_spans_returns_list(self, mock_load, mock_download):
        from ol_lqa.comet import COMETService

        mock_download.return_value = "/path/to/model"
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.metadata = [
            {
                "error_spans": [
                    {
                        "start": 0,
                        "end": 5,
                        "text": "Bonjour",
                        "severity": "minor",
                        "confidence": 0.9,
                    }
                ]
            }
        ]
        mock_model.predict.return_value = mock_output
        mock_load.return_value = mock_model

        service = COMETService()
        spans = service.get_mqm_spans("Hello", "Bonjour")

        assert isinstance(spans, list)
        assert len(spans) == 1
        assert spans[0]["text"] == "Bonjour"
        assert spans[0]["severity"] == "minor"

    @patch("ol_lqa.comet.download_model")
    @patch("ol_lqa.comet.load_from_checkpoint")
    def test_get_mqm_spans_empty_when_no_errors(self, mock_load, mock_download):
        from ol_lqa.comet import COMETService

        mock_download.return_value = "/path/to/model"
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.metadata = [{"error_spans": []}]
        mock_model.predict.return_value = mock_output
        mock_load.return_value = mock_model

        service = COMETService()
        spans = service.get_mqm_spans("Hello", "Hello")

        assert isinstance(spans, list)
        assert len(spans) == 0

    @patch("ol_lqa.comet.download_model")
    @patch("ol_lqa.comet.load_from_checkpoint")
    def test_score_and_evaluate_returns_evaluation_result(self, mock_load, mock_download):
        from ol_lqa.comet import COMETService

        mock_download.return_value = "/path/to/model"
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.scores = [0.85]
        mock_output.metadata = [{"error_spans": []}]
        mock_model.predict.return_value = mock_output
        mock_load.return_value = mock_model

        service = COMETService()

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                service.score_and_evaluate(
                    "Hello world",
                    "Bonjour le monde",
                    "unit_1",
                    "en",
                    "fr"
                )
            )
        finally:
            loop.close()

        assert result.unit_id == "unit_1"
        assert "xcomet" in result.scorer_scores
        assert result.scorer_scores["xcomet"] == 0.85
        assert result.warnings == []

    @patch("ol_lqa.comet.download_model")
    @patch("ol_lqa.comet.load_from_checkpoint")
    def test_score_and_evaluate_with_mqm_warnings(self, mock_load, mock_download):
        from ol_lqa.comet import COMETService

        mock_download.return_value = "/path/to/model"
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.scores = [0.7]
        mock_output.metadata = [
            {
                "error_spans": [
                    {"start": 0, "end": 5, "text": "Bonjour", "severity": "major", "confidence": 0.8}
                ]
            }
        ]
        mock_model.predict.return_value = mock_output
        mock_load.return_value = mock_model

        service = COMETService()

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                service.score_and_evaluate(
                    "Hello",
                    "Bonjour",
                    "unit_1",
                    "en",
                    "fr"
                )
            )
        finally:
            loop.close()

        assert "MQM spans: 1 errors detected" in result.warnings


class TestCOMETServiceEdgeCases:
    @patch("ol_lqa.comet.download_model")
    @patch("ol_lqa.comet.load_from_checkpoint")
    def test_score_xcomet_with_empty_output(self, mock_load, mock_download):
        from ol_lqa.comet import COMETService

        mock_download.return_value = "/path/to/model"
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.scores = []
        mock_model.predict.return_value = mock_output
        mock_load.return_value = mock_model

        service = COMETService()

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            score = loop.run_until_complete(
                service.score_xcomet("Hello", "Bonjour", "en", "fr")
            )
        finally:
            loop.close()

        assert score == 0.0

    @patch("ol_lqa.comet.download_model")
    @patch("ol_lqa.comet.load_from_checkpoint")
    def test_get_mqm_spans_with_no_metadata(self, mock_load, mock_download):
        from ol_lqa.comet import COMETService

        mock_download.return_value = "/path/to/model"
        mock_model = MagicMock()
        mock_output = MagicMock()
        mock_output.metadata = None
        mock_model.predict.return_value = mock_output
        mock_load.return_value = mock_model

        service = COMETService()
        spans = service.get_mqm_spans("Hello", "Bonjour")

        assert isinstance(spans, list)
        assert len(spans) == 0