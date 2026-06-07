import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ol_core.dataclass import EvaluationResult
from ol_lqa.judge import JudgeService
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
        assert result.attempt_history[0][0] == "a"
        assert abs(result.attempt_history[0][1] - 6.0) < 1e-6
        assert result.attempt_history[1][0] == "b"
        assert abs(result.attempt_history[1][1] - 7.5) < 1e-6

    @pytest.mark.asyncio
    async def test_judge_retry_triggers_below_threshold(self):
        """A0.6: Retry must be reachable when LLM score is below threshold.

        Pre-fix: LLM 0-100 values were stored as-is, so judge_overall_score
        was always >= 25 (min from defaults), making lqa_threshold=5.0
        unreachable. Post-fix: values are rescaled 0-100→0-10, so a low
        LLM score genuinely triggers retry.
        """
        mgr = RetryManager(max_retries=2, pass_threshold=7.0)
        translations = ["bad_translation_v1", "bad_translation_v2", "good_translation"]

        async def translate():
            return translations.pop(0)

        mock_model_pool = MagicMock()
        mock_model_pool.judge = AsyncMock(return_value={
            "accuracy": 40,
            "fluency": 40,
            "adequacy": 40,
            "score": 40,
        })
        service = JudgeService(pass_threshold=7.0, model_pool=mock_model_pool)

        async def judge_fn(source, target, unit_id):
            return await service.judge(source, target, unit_id)

        result = await mgr.execute_with_retry("u1", "source text", translate, judge_fn)
        assert result.attempts == 3, (
            f"Expected 3 attempts (1 initial + 2 retries) because LLM score=40 "
            f"rescales to 4.0 which is below threshold 7.0. "
            f"Got {result.attempts} attempts. Pre-fix this was unreachable."
        )
        assert result.warning == "OL_WARN: Low_Score"

    @pytest.mark.asyncio
    async def test_translate_fn_transport_error_does_not_drop_unit(self):
        """A8 verification: a transport error in translate_fn does NOT drop
        the unit silently. RetryResult.transport_error=True, best_translation
        falls back to source_text, warning contains 'OL_WARN: TRANSLATION_FAILED'.

        Pin the OL-4 wrap in retry.py:38-56 so future refactors can't
        silently regress to a string-only return.
        """
        import asyncio
        mgr = RetryManager(max_retries=2, pass_threshold=7.0)

        async def translate():
            raise asyncio.TimeoutError("upstream API timed out after 60s")

        async def judge(source, target, unit_id):
            return EvaluationResult(
                unit_id=unit_id, scorer_scores={},
                judge_scores={"adequacy": 8.0, "fluency": 8.0},
                format_preserved=True, format_errors=[], warnings=[],
            )

        result = await mgr.execute_with_retry(
            "u1", "ORIGINAL_SOURCE_TEXT", translate, judge
        )
        assert result.transport_error is True, (
            "translate_fn raised but transport_error is False; unit silently dropped"
        )
        assert result.best_translation == "ORIGINAL_SOURCE_TEXT", (
            f"best_translation should fall back to source, got {result.best_translation!r}"
        )
        assert result.warning is not None
        assert "OL_WARN: TRANSLATION_FAILED" in result.warning
        assert "TimeoutError" in result.warning

    @pytest.mark.asyncio
    async def test_translate_fn_transport_error_propagates_via_a2_gather(self):
        """A8 verification: in an A2-style asyncio.gather, one unit's transport
        error does not abort the other units. The failed unit's result has
        transport_error=True; the other units translate normally.
        """
        import asyncio
        mgr = RetryManager(max_retries=0, pass_threshold=7.0)
        texts = ["alpha", "fail-1", "beta", "fail-2", "gamma"]

        async def translate_one(text):
            async def translate():
                if "fail" in text:
                    raise asyncio.TimeoutError(f"timeout for {text!r}")
                return f"TRANSLATED({text})"

            async def judge(source, target, unit_id):
                return EvaluationResult(
                    unit_id=unit_id, scorer_scores={},
                    judge_scores={"adequacy": 8.0, "fluency": 8.0},
                    format_preserved=True, format_errors=[], warnings=[],
                )

            return await mgr.execute_with_retry(
                f"u_{text}", text, translate, judge
            )

        results = await asyncio.gather(
            *[translate_one(t) for t in texts], return_exceptions=True
        )

        succeeded = [r for r in results if isinstance(r, RetryResult) and not r.transport_error]
        failed = [r for r in results if isinstance(r, RetryResult) and r.transport_error]
        raised = [r for r in results if isinstance(r, Exception)]

        assert len(succeeded) == 3, (
            f"Expected 3 successful translates, got {len(succeeded)}. results={results!r}"
        )
        assert len(failed) == 2, (
            f"Expected 2 transport_error RetryResults, got {len(failed)}"
        )
        assert len(raised) == 0, (
            f"translate_fn raised should NOT propagate as Exception (A8 wrap); "
            f"got {len(raised)} exceptions: {raised!r}"
        )
        for r in failed:
            assert r.best_translation in texts
            assert "OL_WARN: TRANSLATION_FAILED" in r.warning

    # POST_MORTEM OL-5: RetryResult carries the underlying exception in
    # the `exception` field (renamed from `judge_exception` since it can
    # come from EITHER translate_fn or judge_fn). Old name kept as
    # backward-compat alias.

    def test_exception_field_carries_translate_err(self):
        """When translate_fn raises, the exception object is preserved on .exception."""
        boom = RuntimeError("LLM provider down")
        def translate_fn():
            raise boom
        def judge_fn(s, t, u):
            raise AssertionError("should not be called when translate fails")

        mgr = RetryManager(max_retries=0, pass_threshold=7.0)
        result = asyncio.run(
            mgr.execute_with_retry("u1", "source", translate_fn, judge_fn)
        )

        assert result.transport_error is True
        assert result.exception is boom

    def test_judge_exception_alias_works(self):
        """The old `.judge_exception` attribute name is preserved as an alias."""
        boom = ValueError("judge blew up")
        async def translate_fn():
            return "ok"
        async def judge_fn(s, t, u):
            raise boom

        mgr = RetryManager(max_retries=0, pass_threshold=7.0)
        result = asyncio.run(
            mgr.execute_with_retry("u1", "source", translate_fn, judge_fn)
        )

        # Old API still works.
        assert result.judge_exception is boom
        # New API also works.
        assert result.exception is boom
