import pytest

from ol_core.dataclass import EvaluationResult
from ol_lqa.scorer import ScorerService


class TestScorerService:
    def test_init_default_threshold(self):
        svc = ScorerService()
        assert svc.threshold == 0.7

    def test_init_custom_threshold(self):
        svc = ScorerService(threshold=0.5)
        assert svc.threshold == 0.5

    @pytest.mark.asyncio
    async def test_score_single(self):
        svc = ScorerService()
        result = await svc.score("Hello world", "Hello world", "u1")
        assert isinstance(result, EvaluationResult)
        assert result.unit_id == "u1"
        assert "bleu" in result.scorer_scores
        assert "regex_match" in result.scorer_scores

    @pytest.mark.asyncio
    async def test_score_preserves_format(self):
        svc = ScorerService()
        result = await svc.score("test", "test", "u1")
        assert result.format_preserved is True
        assert result.format_errors == []
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_score_batch(self):
        svc = ScorerService()
        pairs = [
            ("Hello", "Hello", "u1"),
            ("World", "World", "u2"),
            ("Test", "Test", "u3"),
        ]
        results = await svc.score_batch(pairs)
        assert len(results) == 3
        assert all(isinstance(r, EvaluationResult) for r in results)
        assert results[0].unit_id == "u1"
        assert results[1].unit_id == "u2"
        assert results[2].unit_id == "u3"

    @pytest.mark.asyncio
    async def test_score_batch_empty(self):
        svc = ScorerService()
        results = await svc.score_batch([])
        assert results == []

    def test_score_sync(self):
        svc = ScorerService()
        scores = svc._score_sync("Hello world", "Hello world")
        assert "bleu" in scores
        assert "regex_match" in scores
        assert 0.0 <= scores["bleu"] <= 1.0001
        assert 0.0 <= scores["regex_match"] <= 1.0001

    def test_score_sync_different_texts(self):
        svc = ScorerService()
        scores = svc._score_sync("Hello", "Goodbye")
        assert "bleu" in scores
        assert "regex_match" in scores
        assert scores["bleu"] < 1.0
