"""Tests for OL#47: max_tokens and finish_reason truncation detection."""
from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

from ol_pool.router import ModelPool, ModelPoolTruncationError


# conftest.py sets OMNI_TEST_FAKE_LLM=1 for all tests, which short-circuits
# translate() to return "placeholder" (fake pool path). Our tests need to
# exercise the real translate() code path, so we override that env var.
@pytest.fixture(autouse=True)
def _real_llm_translate_path():
    """Override OMNI_TEST_FAKE_LLM so translate() does NOT short-circuit."""
    old = os.environ.pop("OMNI_TEST_FAKE_LLM", None)
    os.environ["OMNI_TEST_FAKE_LLM"] = "0"
    yield
    if old is not None:
        os.environ["OMNI_TEST_FAKE_LLM"] = old
    else:
        os.environ.pop("OMNI_TEST_FAKE_LLM", None)


class TestTranslationTruncationDetection:
    """Verify that translate() detects and raises on LLM truncation."""

    @pytest.mark.asyncio
    async def test_translate_raises_on_finish_reason_length(self):
        """When finish_reason is 'length', translate() must raise
        ModelPoolTruncationError immediately (fail-fast)."""
        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                call_count = [0]

                async def _mock_acompletion(*args, **kwargs):
                    call_count[0] += 1
                    assert kwargs.get("max_tokens") == 4096, \
                        f"Expected max_tokens=4096, got {kwargs.get('max_tokens')}"
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(content="partial translation"),
                            finish_reason="length",
                        )
                    ]
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                with pytest.raises(ModelPoolTruncationError) as exc_info:
                    await pool.translate("hello", "en", "zh")

                assert "truncated" in str(exc_info.value).lower()
                # No retry for truncation — fail-fast, max_tokens=4096
                # should be sufficient for any paragraph-level text
                assert call_count[0] == 1, \
                    f"Expected 1 attempt (no retry), got {call_count[0]}"

    @pytest.mark.asyncio
    async def test_translate_succeeds_on_complete_response(self):
        """When finish_reason is 'stop', translate() returns normally."""
        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                async def _mock_acompletion(*args, **kwargs):
                    assert kwargs.get("max_tokens") == 4096, \
                        f"Expected max_tokens=4096, got {kwargs.get('max_tokens')}"
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(content="世界你好"),
                            finish_reason="stop",
                        )
                    ]
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                result = await pool.translate("hello", "en", "zh")
                assert result == "世界你好"


    @pytest.mark.asyncio
    async def test_translate_raises_on_finish_reason_stop_but_truncated(self):
        """When finish_reason is 'stop' but the output appears truncated
        (completion_tokens >= 90% of max_tokens), translate() must raise
        ModelPoolTruncationError (fail-fast)."""
        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                call_count = [0]

                async def _mock_acompletion(*args, **kwargs):
                    call_count[0] += 1
                    assert kwargs.get("max_tokens") == 4096, \
                        f"Expected max_tokens=4096, got {kwargs.get('max_tokens')}"
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(content="partial translation"),
                            finish_reason="stop",
                        )
                    ]
                    mock_resp.usage = MagicMock(
                        completion_tokens=3800,
                        prompt_tokens=100,
                        total_tokens=3900,
                    )
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                with pytest.raises(ModelPoolTruncationError) as exc_info:
                    await pool.translate("hello", "en", "zh")

                assert "truncated" in str(exc_info.value).lower()
                assert "finish_reason=stop" in str(exc_info.value)
                assert "3800" in str(exc_info.value)
                # No retry for truncation — fail-fast
                assert call_count[0] == 1, \
                    f"Expected 1 attempt (no retry), got {call_count[0]}"


class TestJudgeAndProfileMaxTokens:
    """Verify that judge() and profile() pass max_tokens correctly."""

    @pytest.mark.asyncio
    async def test_judge_passes_max_tokens(self):
        """judge() should pass max_tokens=2048 to acompletion."""
        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                async def _mock_acompletion(*args, **kwargs):
                    assert kwargs.get("max_tokens") == 2048, \
                        f"Expected max_tokens=2048, got {kwargs.get('max_tokens')}"
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(
                                content='{"score": 9, "reason": "good"}'
                            ),
                            finish_reason="stop",
                        )
                    ]
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                result = await pool.judge("hello", "world", "en", "zh")
                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_profile_passes_max_tokens(self):
        """profile() should pass max_tokens=2048 to acompletion."""
        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                async def _mock_acompletion(*args, **kwargs):
                    assert kwargs.get("max_tokens") == 2048, \
                        f"Expected max_tokens=2048, got {kwargs.get('max_tokens')}"
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(content='{"tone": "formal"}'),
                            finish_reason="stop",
                        )
                    ]
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                result = await pool.profile("some text", "en")
                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_judge_returns_fail_closed_on_truncation(self):
        """When finish_reason is 'length', judge() returns a fail-closed dict
        with accuracy/fluency/adequacy/score=0, reason='truncated', truncated=True."""
        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                async def _mock_acompletion(*args, **kwargs):
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(content='{"score": 9, "reason": "good"}'),
                            finish_reason="length",
                        )
                    ]
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                result = await pool.judge("hello", "world", "en", "zh")
                assert result == {
                    "accuracy": 0,
                    "fluency": 0,
                    "adequacy": 0,
                    "score": 0,
                    "reason": "truncated",
                    "truncated": True,
                }

    @pytest.mark.asyncio
    async def test_profile_returns_truncated_error_on_truncation(self):
        """When finish_reason is 'length', profile() returns a dict with
        error='truncated', truncated=True, transport_error=True."""
        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                async def _mock_acompletion(*args, **kwargs):
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(content='{"tone": "formal"}'),
                            finish_reason="length",
                        )
                    ]
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                result = await pool.profile("some text", "en")
                assert result == {
                    "error": "truncated",
                    "truncated": True,
                    "transport_error": True,
                }

    @pytest.mark.asyncio
    async def test_judge_normal_behavior_preserved_when_not_truncated(self):
        """When finish_reason is 'stop', judge() parses and returns normally."""
        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                async def _mock_acompletion(*args, **kwargs):
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(
                                content='{"accuracy": 85, "fluency": 90, "adequacy": 88, "score": 87}'
                            ),
                            finish_reason="stop",
                        )
                    ]
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                result = await pool.judge("hello", "world", "en", "zh")
                assert result == {"accuracy": 85, "fluency": 90, "adequacy": 88, "score": 87}

    @pytest.mark.asyncio
    async def test_profile_normal_behavior_preserved_when_not_truncated(self):
        """When finish_reason is 'stop', profile() parses and returns normally."""
        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                async def _mock_acompletion(*args, **kwargs):
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(content='{"tone": "formal", "register": "academic"}'),
                            finish_reason="stop",
                        )
                    ]
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                result = await pool.profile("some text", "en")
                assert isinstance(result, dict)
                assert result.get("tone") == "formal"
                assert result.get("register") == "academic"
