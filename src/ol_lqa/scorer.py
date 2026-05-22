import asyncio

from ol_core.dataclass import EvaluationResult


class ScorerService:
    def __init__(self, threshold: float = 0.7) -> None:
        self._threshold = threshold

    async def score(
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
            self._score_sync,
            source,
            target,
        )
        return EvaluationResult(
            unit_id=unit_id,
            scorer_scores=scores,
            judge_scores={},
            format_preserved=True,
            format_errors=[],
            warnings=[],
        )

    def _score_sync(self, source: str, target: str) -> dict[str, float]:
        source_words = set(source.lower().split())
        target_words = set(target.lower().split())
        if not source_words:
            bleu = 0.0
        else:
            overlap = len(source_words & target_words)
            bleu = overlap / len(source_words)
        regex_match = 1.0 if target.strip() else 0.0
        return {
            "bleu": bleu,
            "regex_match": regex_match,
        }

    async def score_batch(
        self,
        pairs: list[tuple[str, str, str]],
    ) -> list[EvaluationResult]:
        tasks = [
            self.score(source, target, unit_id)
            for source, target, unit_id in pairs
        ]
        return await asyncio.gather(*tasks)

    @property
    def threshold(self) -> float:
        return self._threshold
