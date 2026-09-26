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
        # Use near-identical pair to get high character n-gram overlap
        result = await judge_service.judge(
            source="Hello world this is a very long test sentence used for testing",
            target="Hello world this is a very long test sentence used for testing",
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

        await service.judge(
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
            "terminology_consistency": 80,
            "format_preservation": 80,
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
            "terminology_consistency": 70,
            "format_preservation": 70,
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


class TestPartialFieldRenormalization:
    """T13-01 回归：LLM 缺席的维度必须「省略」而非补 0。

    judge prompt 只询问 accuracy / fluency / adequacy / score，而 rubric 还给
    terminology_consistency(0.20) 与 format_preservation(0.15) 留了权重。
    修复前 _remap_llm_fields 用 .get(field, 0) 补 0，把这两个权重塞进归一化
    分母却不贡献分子，使 judge_overall_score 被硬性封顶在 0.65×10 = 6.5/10
    （即 3.25/5），任何译文都不可能过 7.0 的阈值。
    """

    def test_missing_dimensions_are_omitted(self):
        scores = JudgeService._remap_llm_fields(
            {"accuracy": 90, "fluency": 90, "adequacy": 90, "score": 90},
        )
        assert "terminology_consistency" not in scores
        assert "format_preservation" not in scores

    def test_partial_scores_renormalize_to_full_range(self):
        scores = JudgeService._remap_llm_fields(
            {"accuracy": 90, "fluency": 90, "adequacy": 90, "score": 90},
        )
        overall = EvaluationResult(unit_id="u1", judge_scores=scores).judge_overall_score
        assert abs(overall - 9.0) < 1e-6, (
            f"缺省维度补 0 会把满分压到 5.85；归一化后应为 9.0，实际 {overall}"
        )

    def test_explicit_zero_is_kept(self):
        """LLM 明确给 0 分是真实信号，不能被当成「缺席」丢掉。"""
        scores = JudgeService._remap_llm_fields({"adequacy": 0, "fluency": 50})
        assert scores == {"adequacy": 0.0, "fluency": 5.0}

    def test_all_dimensions_present_unchanged(self):
        scores = JudgeService._remap_llm_fields(
            {"adequacy": 80, "fluency": 80, "terminology_consistency": 80, "format_preservation": 80},
        )
        assert abs(EvaluationResult(unit_id="u1", judge_scores=scores).judge_overall_score - 8.0) < 1e-6

    @pytest.mark.asyncio
    async def test_judge_over_prompt_shaped_response_passes_threshold(self):
        """端到端：LLM 只按 prompt 的字段作答时，优秀译文不应被误判为低分。"""
        mock_model_pool = MagicMock()
        mock_model_pool.judge = AsyncMock(return_value={
            "accuracy": 90, "fluency": 90, "adequacy": 90, "score": 90,
            "format_errors": [],
        })
        service = JudgeService(pass_threshold=7.0, model_pool=mock_model_pool)

        result = await service.judge(
            source="Hello world", target="Bonjour le monde", unit_id="u1",
        )

        assert abs(result.judge_overall_score - 9.0) < 1e-6
        assert not any("below threshold" in w for w in result.warnings), (
            f"9.0/10 的译文被误判低于 7.0 阈值：{result.warnings}"
        )


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

    @pytest.mark.asyncio
    async def test_criterion_no_judge_reported_is_skipped(self, ensemble_judge):
        """T13-01（ensemble 侧）：全体 judge 都缺席的维度不得当成 0 分投票。"""
        partial = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={"adequacy": 9.0, "fluency": 9.0},
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )
        ensemble_judge._judges[0].judge = AsyncMock(return_value=partial)
        ensemble_judge._judges[1].judge = AsyncMock(return_value=partial)

        result = await ensemble_judge.judge(source="Hello", target="Bonjour", unit_id="u1")

        assert "terminology_consistency" not in result.judge_scores
        assert "format_preservation" not in result.judge_scores
        assert abs(result.judge_overall_score - 9.0) < 1e-6, (
            f"缺席维度补 0 会把 9.0 压到 5.85；实际 {result.judge_overall_score}"
        )

    @pytest.mark.asyncio
    async def test_criterion_reported_by_some_judges_uses_only_those(self, ensemble_judge):
        """部分 judge 报出该维度时，只用报出的分数聚合，缺席者不参与中位数。"""
        full = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={"adequacy": 8.0, "fluency": 8.0, "terminology_consistency": 8.0},
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )
        partial = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={"adequacy": 8.0, "fluency": 8.0},
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )
        ensemble_judge._judges[0].judge = AsyncMock(return_value=full)
        ensemble_judge._judges[1].judge = AsyncMock(return_value=partial)

        result = await ensemble_judge.judge(source="Hello", target="Bonjour", unit_id="u1")

        assert result.judge_scores["terminology_consistency"] == 8.0, (
            f"缺席者被当成 0 分投票，中位数应为 8.0，实际 "
            f"{result.judge_scores.get('terminology_consistency')}"
        )
        assert "format_preservation" not in result.judge_scores


class TestJudgeServiceScorerMerge:
    """OL#72: JudgeService must accept an optional scorer and merge its
    ``score_and_evaluate`` output (scorer_scores + mqm_spans) into the
    returned EvaluationResult. This is the pluggable-scorer contract."""

    @pytest.mark.asyncio
    async def test_judge_merges_bleu_scorer_scores(self):
        from ol_lqa.scorer import ScorerService

        service = JudgeService(pass_threshold=7.0, scorer=ScorerService())
        result = await service.judge(
            source="Hello world",
            target="Hello world",
            unit_id="u1",
        )
        assert "bleu" in result.scorer_scores
        assert "regex_match" in result.scorer_scores

    @pytest.mark.asyncio
    async def test_judge_merges_scorer_mqm_spans(self):
        class _StubCometScorer:
            async def score_and_evaluate(
                self, source, target, unit_id, source_lang="en", target_lang="en",
            ):
                return EvaluationResult(
                    unit_id=unit_id,
                    scorer_scores={"xcomet": 0.91},
                    mqm_spans=[{"severity": "minor", "text": "x"}],
                )

        service = JudgeService(pass_threshold=7.0, scorer=_StubCometScorer())
        result = await service.judge(
            source="Hello", target="Bonjour", unit_id="u1",
        )
        assert result.scorer_scores == {"xcomet": 0.91}
        assert result.mqm_spans == [{"severity": "minor", "text": "x"}]

    @pytest.mark.asyncio
    async def test_judge_without_scorer_keeps_empty_scorer_scores(self):
        service = JudgeService(pass_threshold=7.0)
        result = await service.judge(source="Hello", target="Bonjour", unit_id="u1")
        assert result.scorer_scores == {}
        assert result.mqm_spans == []
