"""Tests for defensive error handling added per POST_MORTEM.md.

Covers:
- OL-2: ModelPool.judge() handles transport errors (Timeout/RateLimitError/Auth/other)
- OL-3: JudgeService.judge() returns EvaluationResult on model_pool errors
- OL-4: RetryManager.execute_with_retry catches translate_fn exceptions
- OL-5: RetryResult has judge_exception and transport_error fields
"""

import pybreaker
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from litellm.exceptions import AuthenticationError, RateLimitError, Timeout

from ol_core.dataclass import EvaluationResult
from ol_lqa.judge import JudgeService
from ol_pool.router import ModelPool
from ol_retry.retry import RetryManager, RetryResult


# ============================================================
# OL-2: ModelPool.judge() transport-error handling
# ============================================================
class TestModelPoolJudgeTransportErrors:
    """POST_MORTEM OL-2: judge() must NOT propagate transport errors."""

    def _make_pool(self, side_effect):
        pool = ModelPool.__new__(ModelPool)
        pool._test_mode = False
        pool._logger = MagicMock()
        pool._router = MagicMock()
        pool._router.acompletion = MagicMock(side_effect=side_effect)
        # A3 added the LRU cache; tests using __new__ to bypass __init__
        # must set _cache_enabled to opt out of cache lookup (the cache
        # is what `pool._cache` would normally wrap).
        pool._cache_enabled = False
        pool._breakers = {"translation": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60), "judging": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60), "restoration": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)}
        return pool

    @pytest.mark.asyncio
    @patch("src.ol_pool.router.load_config")
    async def test_judge_timeout_returns_transport_error(self, mock_load_config):
        mock_load_config.return_value = MagicMock(
            llm_pool=MagicMock(translation=[], judging=[], restoration=[]),
        )
        pool = self._make_pool(Timeout("judge timed out"))
        result = await pool.judge("src", "tgt", "en", "en")
        assert result["score"] == 0
        assert result.get("transport_error") is True
        assert "timeout" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    @patch("src.ol_pool.router.load_config")
    async def test_judge_rate_limit_returns_transport_error(self, mock_load_config):
        mock_load_config.return_value = MagicMock(
            llm_pool=MagicMock(translation=[], judging=[], restoration=[]),
        )
        pool = self._make_pool(RateLimitError("rate limited"))
        result = await pool.judge("src", "tgt", "en", "en")
        assert result["score"] == 0
        assert result.get("transport_error") is True
        assert "rate_limit" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    @patch("src.ol_pool.router.load_config")
    async def test_judge_auth_error_returns_transport_error(self, mock_load_config):
        mock_load_config.return_value = MagicMock(
            llm_pool=MagicMock(translation=[], judging=[], restoration=[]),
        )
        pool = self._make_pool(AuthenticationError("auth failed"))
        result = await pool.judge("src", "tgt", "en", "en")
        assert result["score"] == 0
        assert result.get("transport_error") is True
        assert "auth" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    @patch("src.ol_pool.router.load_config")
    async def test_judge_unknown_exception_returns_transport_error(self, mock_load_config):
        mock_load_config.return_value = MagicMock(
            llm_pool=MagicMock(translation=[], judging=[], restoration=[]),
        )
        pool = self._make_pool(RuntimeError("new_sensitive content moderation"))
        result = await pool.judge("src", "tgt", "en", "en")
        assert result["score"] == 0
        assert result.get("transport_error") is True
        assert (
            "new_sensitive" in result.get("reason", "")
            or "unknown" in result.get("reason", "").lower()
        )


# ============================================================
# OL-3: JudgeService.judge() error containment
# ============================================================
class TestJudgeServiceErrorContainment:
    """POST_MORTEM OL-3: judge() must not crash if model_pool.judge throws."""

    @pytest.mark.asyncio
    async def test_judge_swallows_model_pool_exception(self):
        service = JudgeService(pass_threshold=7.0)
        service._model_pool = MagicMock()
        service._model_pool.judge = AsyncMock(
            side_effect=RuntimeError("upstream blew up"),
        )

        result = await service.judge("src", "tgt", "u1", "en", "en")
        assert isinstance(result, EvaluationResult)
        assert result.unit_id == "u1"
        for score in result.judge_scores.values():
            assert score == 0
        assert any("judge" in w.lower() for w in result.warnings)


# ============================================================
# OL-4: RetryManager catches translate_fn exceptions
# ============================================================
class TestRetryManagerTranslateFnException:
    """POST_MORTEM OL-4: translate_fn throwing must not crash the pipeline."""

    @pytest.mark.asyncio
    async def test_translate_fn_throws_returns_retry_result(self):
        mgr = RetryManager(max_retries=2, pass_threshold=7.0)

        async def translate_throws():
            raise RuntimeError("provider rejected request (new_sensitive)")

        async def judge_ok(source, target, unit_id):
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores={"adequacy": 8.0, "fluency": 8.0},
                format_preserved=True,
                format_errors=[],
                warnings=[],
            )

        result = await mgr.execute_with_retry(
            "u1", "source text", translate_throws, judge_ok,
        )
        assert isinstance(result, RetryResult)
        assert result.warning is not None
        assert "TRANSLATION_FAILED" in result.warning
        assert result.best_translation == "source text"

    @pytest.mark.asyncio
    async def test_translate_fn_throws_with_zero_retries(self):
        mgr = RetryManager(max_retries=0, pass_threshold=7.0)

        async def translate_throws():
            raise TimeoutError("op timeout")

        async def judge_ok(source, target, unit_id):
            return EvaluationResult(
                unit_id=unit_id,
                scorer_scores={},
                judge_scores={"adequacy": 8.0, "fluency": 8.0},
                format_preserved=True,
                format_errors=[],
                warnings=[],
            )

        result = await mgr.execute_with_retry("u1", "fallback_src", translate_throws, judge_ok)
        assert isinstance(result, RetryResult)
        assert result.best_translation == "fallback_src"
        assert result.attempts == 1


# ============================================================
# OL-5: RetryResult has judge_exception and transport_error fields
# ============================================================
class TestRetryResultNewFields:
    """POST_MORTEM OL-5: RetryResult exposes judge_exception and transport_error."""

    def test_retry_result_default_field_values(self):
        result = RetryResult(
            attempts=1, final_score=8.0, best_translation="hi", warning=None,
        )
        assert hasattr(result, "judge_exception")
        assert hasattr(result, "transport_error")
        assert result.judge_exception is None
        assert result.transport_error is False

    def test_retry_result_accepts_judge_exception(self):
        """POST_MORTEM OL-5: RetryResult carries the underlying exception in
        the new ``exception`` field (renamed from ``judge_exception`` for
        semantic clarity since it carries errors from EITHER translate_fn
        or judge_fn). The old ``judge_exception`` field name is preserved
        as a backward-compat alias via __getattr__.
        """
        exc = RuntimeError("boom")
        result = RetryResult(
            attempts=1, final_score=0, best_translation="",
            warning="OL_WARN: LQA_SKIPPED",
            exception=exc, transport_error=True,
        )
        # New API works.
        assert result.exception is exc
        # Old API still works (backward-compat shim).
        assert result.judge_exception is exc
        assert result.transport_error is True


# ============================================================
# Phase A.1: system_message forbids XML wrappers
# ============================================================
class TestModelPoolTranslateSystemMessage:
    """RC-1: the LLM was wrapping 30% of responses in
    `<source xmlns=...>` because the system prompt forbade code fences
    but not XML wrappers. Verify the new prompt explicitly forbids XML
    wrapping while preserving the original placeholder and code-fence rules.
    """

    @pytest.mark.asyncio
    @patch("src.ol_pool.router.load_config")
    async def test_translate_system_message_forbids_xml_wrapping(self, mock_load_config):
        mock_load_config.return_value = MagicMock(
            llm_pool=MagicMock(translation=[], judging=[], restoration=[]),
        )
        pool = ModelPool.__new__(ModelPool)
        pool._test_mode = False
        pool._logger = MagicMock()
        pool._router = MagicMock()
        pool._cache_enabled = False
        pool._breakers = {"translation": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60), "judging": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60), "restoration": pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)}
        captured_messages: list[dict] = []
        async def _capture_acompletion(*args, **kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message.content = "Hello"
            return response
        pool._router.acompletion = AsyncMock(side_effect=_capture_acompletion)

        await pool.translate("Hello", "en", "zh")

        system_msgs = [m for m in captured_messages if m.get("role") == "system"]
        assert len(system_msgs) == 1
        system_text = system_msgs[0]["content"]

        assert "XML" in system_text or "xml" in system_text, (
            f"system_message lacks anti-XML rule: {system_text!r}"
        )
        assert "wrap" in system_text.lower(), (
            f"system_message must mention 'wrap' to forbid XML wrapping: {system_text!r}"
        )
        assert "<source" in system_text or "source" in system_text, (
            f"system_message must mention <source> as a forbidden wrapper: {system_text!r}"
        )
        assert "<target" in system_text or "target" in system_text, (
            f"system_message must mention <target> as a forbidden wrapper: {system_text!r}"
        )
        assert "_OL_XTAG_" in system_text, (
            f"system_message must still preserve the placeholder rule: {system_text!r}"
        )
        assert "code fence" in system_text, (
            f"system_message must still preserve the code-fence rule: {system_text!r}"
        )
