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
        weighted = judge_service._compute_overall_score(scores)
        assert abs(weighted - 10.0) < 0.01

    def test_weighted_score_partial_criteria(self, judge_service):
        scores = {"adequacy": 10.0, "fluency": 10.0}
        weighted = judge_service._compute_overall_score(scores)
        expected = (10.0 + 10.0) / 2
        assert abs(weighted - expected) < 0.01

    @pytest.mark.asyncio
    async def test_judge_with_glossary(self):
        """AC-4: JudgeService passes glossary to model_pool for terminology_consistency scoring."""
        mock_model_pool = MagicMock()
        mock_model_pool.judge = AsyncMock(return_value={
            "adequacy": 80,
            "fluency": 80,
            "terminology_consistency": 60,
            "format_preservation": 80,
            "score": 75,
        })
        service = JudgeService(pass_threshold=7.0, model_pool=mock_model_pool)
        glossary = {"Hello": "Bonjour", "world": "monde"}

        result = await service.judge(
            source="Hello world",
            target="Bonjour monde",
            unit_id="u1",
            glossary=glossary,
        )

        # Verify glossary was passed to model pool
        mock_model_pool.judge.assert_called_once()
        call_args = mock_model_pool.judge.call_args[0]
        passed_glossary = call_args[4]
        assert passed_glossary == glossary


    @pytest.mark.asyncio
    async def test_judge_without_glossary_still_works(self):
        mock_model_pool = MagicMock()
        mock_model_pool.judge = AsyncMock(return_value={
            "adequacy": 80,
            "fluency": 80,
            "terminology_consistency": 80,
            "format_preservation": 80,
            "score": 80,
        })
        service = JudgeService(pass_threshold=7.0, model_pool=mock_model_pool)

        result = await service.judge(
            source="Hello world",
            target="Bonjour monde",
            unit_id="u1",
        )

        assert isinstance(result, EvaluationResult)
        assert result.unit_id == "u1"
        assert "terminology_consistency" in result.judge_scores

    @pytest.mark.asyncio
    async def test_judge_glossary_passed_to_model_pool(self):
        mock_model_pool = MagicMock()
        mock_model_pool.judge = AsyncMock(return_value={
            "accuracy": 80,
            "fluency": 80,
            "terminology_consistency": 80,
            "format_preservation": 80,
            "score": 80,
        })
        service = JudgeService(pass_threshold=7.0, model_pool=mock_model_pool)
        glossary = {"API": "api", "SDK": "sdk"}

        await service.judge(
            source="API and SDK",
            target="api et sdk",
            unit_id="u1",
            glossary=glossary,
        )

        call_args = mock_model_pool.judge.call_args[0]
        passed_glossary = call_args[4]
        assert passed_glossary == glossary

    # ── A0.1 ──────────────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_judge_rescales_0_100_to_0_10(self):
        """A0.1: LLM returns 0-100 scale; JudgeService must rescale to 0-10."""
        mock_model_pool = MagicMock()
        mock_model_pool.judge = AsyncMock(return_value={
            "accuracy": 80,
            "fluency": 75,
            "adequacy": 85,
            "score": 80,
        })
        service = JudgeService(pass_threshold=7.0, model_pool=mock_model_pool)

        result = await service.judge(
            source="Hello world",
            target="Bonjour monde",
            unit_id="u1",
        )

        for key, score in result.judge_scores.items():
            assert 0.0 <= score <= 10.0, (
                f"judge_scores[{key}]={score} is out of 0-10 range; "
                f"LLM 0-100 values must be rescaled"
            )

        assert abs(result.judge_overall_score - 8.0) < 0.1, (
            f"Expected judge_overall_score ≈ 8.0 (rescaled), "
            f"got {result.judge_overall_score}"
        )

    # ── A0.2 ──────────────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_score_field_propagates(self):
        """A0.2: LLM 'score' field must propagate to overall score, not be lost."""
        mock_model_pool = MagicMock()
        mock_model_pool.judge = AsyncMock(return_value={
            "accuracy": 70,
            "fluency": 70,
            "adequacy": 70,
            "score": 70,
        })
        service = JudgeService(pass_threshold=7.0, model_pool=mock_model_pool)

        result = await service.judge(
            source="Hello world",
            target="Bonjour monde",
            unit_id="u1",
        )

        assert abs(result.judge_overall_score - 7.0) < 0.1, (
            f"Expected judge_overall_score ≈ 7.0 (from LLM score=70 rescaled), "
            f"got {result.judge_overall_score}. Pre-fix this was ~65 due to "
            f"field-name mismatch causing defaults of 50."
        )

    # ── A0.3 ──────────────────────────────────────────────────────────
    def test_judge_overall_score_uses_rubric_weights(self):
        """A0.3: _compute_overall_score must use RUBRIC_WEIGHTS, not simple mean."""
        scores = {
            "adequacy": 10.0,
            "fluency": 10.0,
            "terminology_consistency": 0.0,
            "format_preservation": 0.0,
        }
        weighted = JudgeService._compute_overall_score(JudgeService(), scores)
        simple_mean = 5.0
        expected_weighted = 0.35 * 10.0 + 0.30 * 10.0
        assert abs(weighted - expected_weighted) < 0.01, (
            f"Expected weighted mean {expected_weighted}, got {weighted}. "
            f"Simple mean would be {simple_mean}."
        )
        assert abs(weighted - simple_mean) > 0.5, (
            f"Weighted mean {weighted} should differ significantly from "
            f"simple mean {simple_mean}"
        )

    # ── A0.4 ──────────────────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_format_preserved_computed(self):
        """A0.4: format_preserved must be computed from LLM format_errors, not hardcoded."""
        mock_model_pool = MagicMock()
        mock_model_pool.judge = AsyncMock(return_value={
            "accuracy": 80,
            "fluency": 80,
            "adequacy": 80,
            "score": 80,
            "format_errors": ["missing placeholder"],
        })
        service = JudgeService(pass_threshold=7.0, model_pool=mock_model_pool)
        result = await service.judge(
            source="Hello world",
            target="Bonjour monde",
            unit_id="u1",
        )
        assert result.format_preserved is False, (
            "format_preserved must be False when LLM reports format_errors"
        )
        assert "missing placeholder" in result.format_errors

        mock_model_pool2 = MagicMock()
        mock_model_pool2.judge = AsyncMock(return_value={
            "accuracy": 80,
            "fluency": 80,
            "adequacy": 80,
            "score": 80,
            "format_errors": [],
        })
        service2 = JudgeService(pass_threshold=7.0, model_pool=mock_model_pool2)
        result2 = await service2.judge(
            source="Hello world",
            target="Bonjour monde",
            unit_id="u1",
        )
        assert result2.format_preserved is True, (
            "format_preserved must be True when LLM reports no format_errors"
        )
        assert result2.format_errors == []


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
