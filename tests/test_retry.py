import pytest

from ol_core.dataclass import EvaluationResult
from ol_retry.retry import RetryManager, RetryResult


class TestRetryResult:
    def test_creation(self):
        result = RetryResult(
            attempts=1,
            final_score=8.0,
            best_translation="hello",
            warning=None,
        )
        assert result.attempts == 1
        assert result.final_score == 8.0
        assert result.best_translation == "hello"
        assert result.warning is None


class TestRetryManager:
    def test_init_default(self):
        mgr = RetryManager()
        assert mgr._max_retries == 2
        assert mgr._pass_threshold == 7.0

    def test_init_custom(self):
        mgr = RetryManager(max_retries=1, pass_threshold=6.0)
        assert mgr._max_retries == 1
        assert mgr._pass_threshold == 6.0

    @pytest.mark.asyncio
    async def test_pass_first_attempt(self):
        mgr = RetryManager()
        translations = ["hello"]

        async def translate():
            return translations.pop(0)

        async def judge(source, target, unit_id):
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores={"adequacy": 8.0, "fluency": 8.0},
                format_preserved=True,
                format_errors=[],
                warnings=[],
            )

        result = await mgr.execute_with_retry("u1", "hello", translate, judge)
        assert result.attempts == 1
        assert result.final_score == 8.0
        assert result.warning is None

    @pytest.mark.asyncio
    async def test_retry_then_pass(self):
        mgr = RetryManager()
        call_count = 0

        async def translate():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "bad"
            return "good"

        async def judge(source, target, unit_id):
            score = 5.0 if target == "bad" else 8.0
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores={"adequacy": score, "fluency": score},
                format_preserved=True,
                format_errors=[],
                warnings=[],
            )

        result = await mgr.execute_with_retry("u1", "hello", translate, judge)
        assert result.attempts == 2
        assert result.final_score == 8.0

    @pytest.mark.asyncio
    async def test_all_fail_return_best(self):
        mgr = RetryManager(max_retries=2)
        translations = ["bad1", "bad2", "bad3"]

        async def translate():
            return translations.pop(0)

        async def judge(source, target, unit_id):
            score = 5.0 if "bad" in target else 8.0
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores={"adequacy": score, "fluency": score},
                format_preserved=True,
                format_errors=[],
                warnings=[],
            )

        result = await mgr.execute_with_retry("u1", "hello", translate, judge)
        assert result.attempts == 3
        assert result.warning == "OL_WARN: Low_Score"

    @pytest.mark.asyncio
    async def test_attempt_history_tracked(self):
        mgr = RetryManager(max_retries=1)
        translations = ["a", "b", "c"]

        async def translate():
            return translations.pop(0)

        async def judge(source, target, unit_id):
            score_map = {"a": 6.0, "b": 7.5, "c": 8.0}
            score = score_map.get(target, 5.0)
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores={"adequacy": score, "fluency": score},
                format_preserved=True,
                format_errors=[],
                warnings=[],
            )

        result = await mgr.execute_with_retry("u1", "hello", translate, judge)
        assert len(result.attempt_history) == 2
        assert result.attempt_history[0] == ("a", 6.0)
        assert result.attempt_history[1] == ("b", 7.5)
