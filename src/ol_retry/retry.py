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
    # POST_MORTEM OL-5: carries the error from EITHER stage (translate_fn
    # transport failure or judge_fn failure). Renamed from `judge_exception`
    # to reflect that it covers both. `judge_exception` is kept as a
    # deprecated alias for backward compat.
    exception: Exception | None = None
    transport_error: bool = False

    def __getattr__(self, name: str):
        # Backward-compat shim: callers using the old name still work.
        if name == "judge_exception":
            return self.__dict__.get("exception")
        raise AttributeError(name)


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
        last_judge_err: Exception | None = None
        last_transport_err = False

        for attempt in range(self._max_retries + 1):
            try:
                translation = await translate_fn() if asyncio.iscoroutinefunction(translate_fn) else translate_fn()
            except Exception as translate_err:
                # Translation failed; fall back to the source text and flag
                # transport_error so downstream consumers can distinguish this
                # from a genuine low-score retry.
                return RetryResult(
                    attempts=attempt + 1,
                    final_score=0.0,
                    best_translation=source_text,
                    warning=(
                        f"OL_WARN: TRANSLATION_FAILED "
                        f"({type(translate_err).__name__}: {str(translate_err)[:200]})"
                    ),
                    attempt_history=attempt_history,
                    exception=translate_err,
                    transport_error=True,
                )

            try:
                result = await judge_fn(source_text, translation, unit_id)
            except Exception as judge_err:
                # LQA judge call itself failed (e.g. provider content moderation,
                # network error). Fall back to the translation we already have
                # rather than crashing the whole pipeline for this file.
                last_judge_err = judge_err
                last_transport_err = True
                return RetryResult(
                    attempts=attempt + 1,
                    final_score=0.0,
                    best_translation=translation,
                    warning=f"OL_WARN: LQA_SKIPPED ({type(judge_err).__name__}: {judge_err})",
                    attempt_history=attempt_history + [(translation, 0.0)],
                    exception=judge_err,
                    transport_error=True,
                )

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
            exception=last_judge_err,
            transport_error=last_transport_err,
        )
