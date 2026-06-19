import asyncio
from typing import Any

from ol_core.dataclass import EvaluationResult, RUBRIC_WEIGHTS


class JudgeService:
    def __init__(self, pass_threshold: float = 7.0, model_pool=None) -> None:
        self._pass_threshold = pass_threshold
        self._model_pool = model_pool

    @staticmethod
    def _rescale(raw: float) -> float:
        return raw / 10.0

    @staticmethod
    def _remap_llm_fields(result: dict[str, Any]) -> dict[str, float]:
        return {
            "adequacy": JudgeService._rescale(result.get("adequacy", 0)),
            "fluency": JudgeService._rescale(result.get("fluency", 0)),
            "terminology_consistency": JudgeService._rescale(result.get("accuracy", 0)),
            "format_preservation": JudgeService._rescale(result.get("score", 0)),
        }

    _JUDGE_TEMPERATURE = 0.7

    async def judge(
        self,
        source: str,
        target: str,
        unit_id: str,
        source_lang: str = "en",
        target_lang: str = "en",
        glossary: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        if self._model_pool:
            try:
                result = await self._model_pool.judge(
                    source, target, source_lang, target_lang, glossary,
                    temperature=self._JUDGE_TEMPERATURE,
                )
            except Exception as pool_err:
                return EvaluationResult(
                    unit_id=unit_id,
                    scorer_scores={},
                    judge_scores={
                        "adequacy": 0,
                        "fluency": 0,
                        "terminology_consistency": 0,
                        "format_preservation": 0,
                    },
                    format_preserved=False,
                    format_errors=[],
                    warnings=[f"LQA judge error ({type(pool_err).__name__}: {pool_err})"],
                )
            judge_scores = self._remap_llm_fields(result)
            format_errors = result.get("format_errors", [])
            warnings: list[str] = []
            overall = self._compute_overall_score(judge_scores)
            if overall < self._pass_threshold:
                warnings.append(
                    f"Judge score {overall:.1f} below threshold {self._pass_threshold}"
                )
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores=judge_scores,
                format_preserved=len(format_errors) == 0,
                format_errors=format_errors,
                warnings=warnings,
            )

        loop = asyncio.get_event_loop()
        try:
            scores = await loop.run_in_executor(
                None,
                self._judge_sync,
                source,
                target,
            )
        except Exception as sync_err:
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores={
                    "adequacy": 0,
                    "fluency": 0,
                    "terminology_consistency": 0,
                    "format_preservation": 0,
                },
                format_preserved=False,
                format_errors=[],
                warnings=[f"LQA sync judge error ({type(sync_err).__name__}: {sync_err})"],
            )

        warnings = []
        overall = self._compute_overall_score(scores)
        if overall < self._pass_threshold:
            warnings.append(f"Judge score {overall:.1f} below threshold {self._pass_threshold}")

        return EvaluationResult(
            unit_id=unit_id,
            scorer_scores={},
            judge_scores=scores,
            format_preserved=True,
            format_errors=[],
            warnings=warnings,
        )

    # MOCK IMPLEMENTATION - replace with real LLM when model_pool is configured
    def _judge_sync(self, source: str, target: str) -> dict[str, float]:
        adequacy = self._mock_score(source, target, "adequacy")
        fluency = self._mock_score(target, "", "fluency")
        terminology = self._mock_score(source, target, "terminology")
        format_score = self._mock_score(source, target, "format")
        return {
            "adequacy": adequacy,
            "fluency": fluency,
            "terminology_consistency": terminology,
            "format_preservation": format_score,
        }

    def _mock_score(self, source: str, target: str, criterion: str) -> float:
        """Heuristic scoring based on target word count only.
        
        This is a MOCK implementation for Phase 1/2 testing.
        Does NOT evaluate actual translation quality.
        
        Scoring heuristics:
        - Empty target: 5.0 (neutral fallback)
        - <3 words: 4.0 (short = potentially incomplete)
        - 3-9 words: 7.0 (medium length = acceptable)
        - >=10 words: 8.5 (long enough = likely complete)
        
        Note: Uses only target word count. Ignores source text entirely.
        For real LLM-based scoring, configure model_pool in JudgeService.
        
        Args:
            source: Source text (IGNORED in mock - kept for interface compatibility)
            target: Translated target text
            criterion: Scoring criterion (IGNORED - mock has no per-criterion logic)
        
        Returns:
            Heuristic score from 4.0 to 8.5 based on target length
        """
        if not target:
            return 5.0
        target_len = len(target.split())
        if target_len < 3:
            return 4.0
        if target_len < 10:
            return 7.0
        return 8.5

    def _compute_overall_score(self, scores: dict[str, float]) -> float:
        if not scores:
            return 0.0
        weighted_sum = 0.0
        total_weight = 0.0
        for criterion, score in scores.items():
            weight = RUBRIC_WEIGHTS.get(criterion, 0.0)
            weighted_sum += score * weight
            total_weight += weight
        if total_weight == 0.0:
            return 0.0
        return weighted_sum / total_weight

    async def judge_batch(
        self,
        pairs: list[tuple[str, str, str]],
        source_lang: str = "en",
        target_lang: str = "en",
    ) -> list[EvaluationResult]:
        tasks = [
            self.judge(source, target, unit_id, source_lang, target_lang)
            for source, target, unit_id in pairs
        ]
        return await asyncio.gather(*tasks)

    def is_acceptable(self, scores: dict[str, float]) -> bool:
        return self._compute_overall_score(scores) >= self._pass_threshold

    @property
    def pass_threshold(self) -> float:
        return self._pass_threshold


class EnsembleJudge:
    def __init__(self, judges: list["JudgeService"], pass_threshold: float = 7.0) -> None:
        self._judges = judges
        self._pass_threshold = pass_threshold

    async def judge(
        self,
        source: str,
        target: str,
        unit_id: str,
        source_lang: str = "en",
        target_lang: str = "en",
    ) -> EvaluationResult:
        results = await asyncio.gather(
            *[j.judge(source, target, unit_id, source_lang, target_lang) for j in self._judges],
        )

        criteria = ["adequacy", "fluency", "terminology_consistency", "format_preservation"]
        aggregated: dict[str, float] = {}

        for criterion in criteria:
            scores = [r.judge_scores.get(criterion, 0.0) for r in results]
            sorted_scores = sorted(scores)
            n = len(sorted_scores)
            if n % 2 == 0:
                aggregated[criterion] = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
            else:
                aggregated[criterion] = sorted_scores[n // 2]

        warnings: list[str] = []
        weighted_sum = 0.0
        total_weight = 0.0
        for criterion, score in aggregated.items():
            weight = RUBRIC_WEIGHTS.get(criterion, 0.0)
            weighted_sum += score * weight
            total_weight += weight
        overall = weighted_sum / total_weight if total_weight > 0 else 0.0
        if overall < self._pass_threshold:
            warnings.append(f"Ensemble judge score {overall:.1f} below threshold {self._pass_threshold}")

        return EvaluationResult(
            unit_id=unit_id,
            scorer_scores={},
            judge_scores=aggregated,
            format_preserved=False,
            format_errors=[],
            warnings=warnings,
        )

    async def judge_batch(
        self,
        pairs: list[tuple[str, str, str]],
        source_lang: str = "en",
        target_lang: str = "en",
    ) -> list[EvaluationResult]:
        tasks = [
            self.judge(source, target, unit_id, source_lang, target_lang)
            for source, target, unit_id in pairs
        ]
        return await asyncio.gather(*tasks)
