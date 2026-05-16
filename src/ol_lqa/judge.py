import asyncio
from typing import Dict, List, Optional, Tuple

from ol_core.dataclass import EvaluationResult


class JudgeService:
    RUBRIC_WEIGHTS = {
        "adequacy": 0.35,
        "fluency": 0.30,
        "terminology_consistency": 0.20,
        "format_preservation": 0.15,
    }

    def __init__(self, pass_threshold: float = 7.0) -> None:
        self._pass_threshold = pass_threshold

    async def judge(
        self,
        source: str,
        target: str,
        unit_id: str,
        source_lang: str = "en",
        target_lang: str = "en",
    ) -> EvaluationResult:
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(
            None,
            self._judge_sync,
            source,
            target,
        )

        warnings: List[str] = []
        overall = self._compute_weighted_score(scores)
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

    def _judge_sync(self, source: str, target: str) -> Dict[str, float]:
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
        if not target:
            return 5.0
        target_len = len(target.split())
        if target_len < 3:
            return 4.0
        if target_len < 10:
            return 7.0
        return 8.5

    def _compute_weighted_score(self, scores: Dict[str, float]) -> float:
        if not scores:
            return 0.0
        total = sum(
            scores.get(criterion, 0.0) * weight
            for criterion, weight in self.RUBRIC_WEIGHTS.items()
        )
        return total

    async def judge_batch(
        self,
        pairs: List[Tuple[str, str, str]],
        source_lang: str = "en",
        target_lang: str = "en",
    ) -> List[EvaluationResult]:
        tasks = [
            self.judge(source, target, unit_id, source_lang, target_lang)
            for source, target, unit_id in pairs
        ]
        return await asyncio.gather(*tasks)

    def is_acceptable(self, scores: Dict[str, float]) -> bool:
        return self._compute_weighted_score(scores) >= self._pass_threshold

    @property
    def pass_threshold(self) -> float:
        return self._pass_threshold


class EnsembleJudge:
    def __init__(self, judges: List[JudgeService], pass_threshold: float = 7.0) -> None:
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
            *[j.judge(source, target, unit_id, source_lang, target_lang) for j in self._judges]
        )

        criteria = ["adequacy", "fluency", "terminology_consistency", "format_preservation"]
        aggregated: Dict[str, float] = {}

        for criterion in criteria:
            scores = [r.judge_scores.get(criterion, 0.0) for r in results]
            sorted_scores = sorted(scores)
            n = len(sorted_scores)
            if n % 2 == 0:
                aggregated[criterion] = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
            else:
                aggregated[criterion] = sorted_scores[n // 2]

        warnings: List[str] = []
        overall = sum(aggregated.values()) / len(aggregated)
        if overall < self._pass_threshold:
            warnings.append(f"Ensemble judge score {overall:.1f} below threshold {self._pass_threshold}")

        return EvaluationResult(
            unit_id=unit_id,
            scorer_scores={},
            judge_scores=aggregated,
            format_preserved=True,
            format_errors=[],
            warnings=warnings,
        )

    async def judge_batch(
        self,
        pairs: List[Tuple[str, str, str]],
        source_lang: str = "en",
        target_lang: str = "en",
    ) -> List[EvaluationResult]:
        tasks = [
            self.judge(source, target, unit_id, source_lang, target_lang)
            for source, target, unit_id in pairs
        ]
        return await asyncio.gather(*tasks)