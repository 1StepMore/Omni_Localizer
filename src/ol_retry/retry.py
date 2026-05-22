import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from ol_core.dataclass import EvaluationResult


@dataclass
class RetryResult:
    attempts: int
    final_score: float
    best_translation: str
    warning: str | None
    attempt_history: list[tuple[str, float]] = field(default_factory=list)


class RetryManager:
    def __init__(self, max_retries: int = 2, pass_threshold: float = 7.0) -> None:
        self._max_retries = max_retries
        self._pass_threshold = pass_threshold

    async def execute_with_retry(
        self,
        unit_id: str,
        source_text: str,
        translate_fn: Callable[[], str],
        judge_fn: Callable[[str, str, str], EvaluationResult],
    ) -> RetryResult:
        attempt_history: list[tuple[str, float]] = []
        best_result: EvaluationResult | None = None
        best_translation: str = ""
        warning: str | None = None

        for attempt in range(self._max_retries + 1):
            translation = await translate_fn() if asyncio.iscoroutinefunction(translate_fn) else translate_fn()
            result = await judge_fn(source_text, translation, unit_id)

            score = result.judge_overall_score
            attempt_history.append((translation, score))

            if best_result is None or score > best_result.judge_overall_score:
                best_result = result
                best_translation = translation

            if score >= self._pass_threshold:
                return RetryResult(
                    attempts=attempt + 1,
                    final_score=score,
                    best_translation=translation,
                    warning=None,
                    attempt_history=attempt_history,
                )

            if attempt < self._max_retries:
                continue

        warning = "OL_WARN: Low_Score" if best_result and best_result.judge_overall_score < self._pass_threshold else None
        return RetryResult(
            attempts=len(attempt_history),
            final_score=best_result.judge_overall_score if best_result else 0.0,
            best_translation=best_translation,
            warning=warning,
            attempt_history=attempt_history,
        )
