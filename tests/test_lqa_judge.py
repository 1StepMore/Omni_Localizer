from unittest.mock import AsyncMock, MagicMock

import pytest

from ol_core.dataclass import EvaluationResult
from ol_lqa.judge import EnsembleJudge, JudgeService


class TestJudgeService:
    @pytest.fixture
    def judge_service(self):
        service = JudgeService(pass_threshold=7.0)
        return service

    @pytest.mark.asyncio
    async def test_judge_returns_evaluation_result(self, judge_service):
        result = await judge_service.judge(
            source="Hello world",
            target="Bonjour monde",
            unit_id="u1",
        )
        assert isinstance(result, EvaluationResult)
        assert result.unit_id == "u1"
        assert "adequacy" in result.judge_scores
        assert "fluency" in result.judge_scores
        assert "terminology_consistency" in result.judge_scores
        assert "format_preservation" in result.judge_scores

    @pytest.mark.asyncio
    async def test_judge_scores_are_0_to_10(self, judge_service):
        result = await judge_service.judge(
            source="Test",
            target="Prueba",
            unit_id="u1",
        )
        for score in result.judge_scores.values():
            assert 0.0 <= score <= 10.0

    @pytest.mark.asyncio
    async def test_judge_warns_when_below_threshold(self, judge_service):
        result = await judge_service.judge(
            source="Hi",
            target="X",
            unit_id="u1",
        )
        assert any("below threshold" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_judge_no_warn_when_above_threshold(self, judge_service):
        result = await judge_service.judge(
            source="Hello world this is a very long test sentence",
            target="Bonjour monde ceci est un test encore plus long maintenant",
            unit_id="u1",
        )
        assert not any("below threshold" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_judge_batch(self, judge_service):
        pairs = [
            ("Hello", "Bonjour", "u1"),
            ("World", "Monde", "u2"),
        ]
        results = await judge_service.judge_batch(pairs)
        assert len(results) == 2
        assert results[0].unit_id == "u1"
        assert results[1].unit_id == "u2"

    def test_is_acceptable_above_threshold(self, judge_service):
        scores = {"adequacy": 8.0, "fluency": 8.0, "terminology_consistency": 7.0, "format_preservation": 7.0}
        assert judge_service.is_acceptable(scores) is True

    def test_is_acceptable_below_threshold(self, judge_service):
        scores = {"adequacy": 5.0, "fluency": 5.0, "terminology_consistency": 5.0, "format_preservation": 5.0}
        assert judge_service.is_acceptable(scores) is False

    def test_pass_threshold_property(self, judge_service):
        assert judge_service.pass_threshold == 7.0

    def test_weighted_score_calculation(self, judge_service):
        scores = {"adequacy": 10.0, "fluency": 10.0, "terminology_consistency": 10.0, "format_preservation": 10.0}
        weighted = judge_service._compute_weighted_score(scores)
        assert weighted == 10.0

    def test_weighted_score_partial_criteria(self, judge_service):
        scores = {"adequacy": 10.0, "fluency": 10.0}
        weighted = judge_service._compute_weighted_score(scores)
        expected = 10.0 * 0.35 + 10.0 * 0.30
        assert abs(weighted - expected) < 0.01


class TestEnsembleJudge:
    @pytest.fixture
    def ensemble_judge(self):
        mock_j1 = MagicMock()
        mock_j2 = MagicMock()
        return EnsembleJudge(judges=[mock_j1, mock_j2])

    @pytest.mark.asyncio
    async def test_ensemble_judge_returns_evaluation_result(self, ensemble_judge):
        mock_result = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={"adequacy": 8.0, "fluency": 8.0, "terminology_consistency": 8.0, "format_preservation": 8.0},
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )
        ensemble_judge._judges[0].judge = AsyncMock(return_value=mock_result)
        ensemble_judge._judges[1].judge = AsyncMock(return_value=mock_result)

        result = await ensemble_judge.judge(
            source="Hello",
            target="Bonjour",
            unit_id="u1",
        )
        assert isinstance(result, EvaluationResult)
        assert result.unit_id == "u1"

    @pytest.mark.asyncio
    async def test_ensemble_uses_median(self, ensemble_judge):
        result1 = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={"adequacy": 5.0, "fluency": 5.0, "terminology_consistency": 5.0, "format_preservation": 5.0},
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )
        result2 = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={"adequacy": 9.0, "fluency": 9.0, "terminology_consistency": 9.0, "format_preservation": 9.0},
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )
        ensemble_judge._judges[0].judge = AsyncMock(return_value=result1)
        ensemble_judge._judges[1].judge = AsyncMock(return_value=result2)

        result = await ensemble_judge.judge(
            source="Hello",
            target="Bonjour",
            unit_id="u1",
        )
        assert result.judge_scores["adequacy"] == 7.0
        assert result.judge_scores["fluency"] == 7.0

    @pytest.mark.asyncio
    async def test_ensemble_judge_batch(self, ensemble_judge):
        mock_result = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={"adequacy": 8.0, "fluency": 8.0, "terminology_consistency": 8.0, "format_preservation": 8.0},
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )
        ensemble_judge._judges[0].judge = AsyncMock(return_value=mock_result)
        ensemble_judge._judges[1].judge = AsyncMock(return_value=mock_result)

        results = await ensemble_judge.judge_batch([("Hello", "Bonjour", "u1")])
        assert len(results) == 1
        assert results[0].unit_id == "u1"

    def test_ensemble_uses_median_aggregation(self, ensemble_judge):
        pass
