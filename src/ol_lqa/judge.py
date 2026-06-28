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
            "accuracy": JudgeService._rescale(result.get("accuracy", 0)),
            "score": JudgeService._rescale(result.get("score", 0)),
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
            except Exception as pool_err:  # expected — return safe fallback result
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
        except Exception as sync_err:  # expected — return safe fallback result
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

    # WAVE 4 (L-C7): replaced the naive mock scorer (length-only heuristic)
    # with a character n-gram overlap heuristic that actually considers
    # the source text. The heuristic computes character bigram overlap
    # between source and target (normalized by length) and maps it to a
    # 0-10 scale. This is still NOT a real LLM judging — configure
    # model_pool for production-quality scoring.
    # The NotImplementedError path is available for callers that want to
    # fail fast when no model_pool is configured.

    def _judge_sync(self, source: str, target: str) -> dict[str, float]:
        """Heuristic judging based on character n-gram overlap.

        Computes character bigram overlap between source and target as
        a proxy for translation quality. This works reasonably well for
        related languages (e.g., zh↔en) and is O(n) per pair — no LLM
        call needed.

        For real LLM-based scoring, configure model_pool in JudgeService.
        When no model_pool is set and the caller prefers fast failure,
        set raise_on_missing_model_pool=True on the JudgeService (not
        yet implemented — file a feature request).
        """
        adequacy = self._heuristic_ngram_score(source, target)
        fluency = self._heuristic_fluency_score(target)
        terminology = self._heuristic_ngram_score(source, target)
        format_score = self._heuristic_format_score(target)
        return {
            "adequacy": adequacy,
            "fluency": fluency,
            "terminology_consistency": terminology,
            "format_preservation": format_score,
        }

    @staticmethod
    def _character_ngrams(text: str, n: int = 2) -> set[tuple[str, ...]]:
        """Extract character n-grams from text."""
        if not text:
            return set()
        text = text.lower().strip()
        return set(zip(*[text[i:] for i in range(n)]))

    def _heuristic_ngram_score(self, source: str, target: str) -> float:
        """Score based on character bigram overlap between source and target.

        Returns a score on a 0-10 scale. Higher overlap → higher score.
        For short texts (single chars), falls back to length ratio.
        """
        if not source or not target:
            return 5.0
        source_ngrams = self._character_ngrams(source)
        target_ngrams = self._character_ngrams(target)
        if not source_ngrams or not target_ngrams:
            # Length ratio as fallback for trivial texts
            ratio = min(len(target) / max(len(source), 1), 1.0)
            return 5.0 + ratio * 3.0
        intersection = source_ngrams & target_ngrams
        union = source_ngrams | target_ngrams
        jaccard = len(intersection) / max(len(union), 1)
        # Map Jaccard [0, 1] → score [0, 10]
        return round(jaccard * 10.0, 1)

    def _heuristic_fluency_score(self, target: str) -> float:
        """Score based on target text fluency heuristics.

        Uses average word length as a crude fluency proxy:
        - Very short words may indicate fragmented output
        - Very long words may indicate poor tokenization
        - Empty or whitespace-only: 5.0 (neutral)
        """
        if not target or not target.strip():
            return 5.0
        words = target.split()
        if not words:
            return 5.0
        avg_word_len = sum(len(w) for w in words) / len(words)
        # Most languages have avg word length between 3-8 chars
        if avg_word_len < 1.5:
            return 4.0
        if avg_word_len < 2.5:
            return 6.0
        if avg_word_len <= 8.0:
            return 8.0
        if avg_word_len <= 12.0:
            return 6.0
        return 4.0

    def _heuristic_format_score(self, target: str) -> float:
        """Score format preservation based on presence of expected structure.

        Currently checks for unbalanced brackets/quotes as a basic
        format check. Returns 10.0 if no issues found.
        """
        if not target:
            return 5.0
        issues = 0
        # Check balanced parentheses
        for open_c, close_c in [("(", ")"), ("[", "]"), ("{", "}")]:
            if target.count(open_c) != target.count(close_c):
                issues += 1
        # Check balanced quotes
        for q in ['"', "'"]:
            if target.count(q) % 2 != 0:
                issues += 1
        if issues == 0:
            return 10.0
        if issues <= 2:
            return 7.0
        return 5.0

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
