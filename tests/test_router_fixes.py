"""Tests for OL router code quality fixes (Wave 4).

Covers:
- 4.2: ReDoS in _resolve_env_vars (RED→GREEN)
- 4.3: ModelPool silent failure
- 4.6: Rate limiting in ModelPool
"""
import os
import time
import logging
from unittest.mock import patch, MagicMock

import pytest

# Import litellm exceptions at module level to avoid import-time issues
from litellm.exceptions import RateLimitError as _RateLimitError


# ============================================================================
# Task 4.2: ReDoS in _resolve_env_vars
# ============================================================================


class TestResolveEnvVarsReDoS:
    """RED→GREEN: _resolve_env_vars must not hang on nested ${...${...}...} patterns."""

    def test_resolve_env_vars_normal(self):
        """Normal case still works."""
        from ol_pool.router import _resolve_env_vars
        os.environ["TEST_KEY"] = "test_value"
        result = _resolve_env_vars("${TEST_KEY}")
        assert result == "test_value"

    def test_resolve_env_vars_no_match(self):
        """No env var pattern returns input unchanged."""
        from ol_pool.router import _resolve_env_vars
        result = _resolve_env_vars("plain text")
        assert result == "plain text"

    def test_resolve_env_vars_none(self):
        """None input returns None."""
        from ol_pool.router import _resolve_env_vars
        assert _resolve_env_vars(None) is None

    def test_resolve_env_vars_unset_raises(self):
        """Unset env var raises ValueError."""
        from ol_pool.router import _resolve_env_vars
        # Ensure the var is not set
        os.environ.pop("UNSET_VAR_THAT_SHOULD_NEVER_EXIST", None)
        with pytest.raises(ValueError, match="UNSET_VAR_THAT_SHOULD_NEVER_EXIST"):
            _resolve_env_vars("${UNSET_VAR_THAT_SHOULD_NEVER_EXIST}")

    def test_resolve_env_vars_no_redos_on_nested_patterns(self):
        """RED->GREEN: nested ${...${...}...} patterns must NOT cause exponential backtracking.

        The old regex-based implementation could be DoS'd with
        nested variable syntax. The new implementation must handle this in O(n)
        time without catastrophic backtracking.

        This test sends a long string with deeply nested ${ patterns and verifies
        it completes within a strict timeout (1 second). If it hangs, the
        implementation still has a ReDoS vulnerability.
        """
        from ol_pool.router import _resolve_env_vars

        # Craft a pathologically nested pattern that would trigger ReDoS
        # with the old regex: strings like ${outer${inner}stuff} are fine,
        # but a long string with many $ and { and no } could cause issues.
        nested = "${" * 100 + "x" + "}" * 100

        start = time.monotonic()
        # The function should raise ValueError (unset env var) or handle it
        # without hanging. The key assertion is that it completes in < 1s.
        try:
            _resolve_env_vars(nested)
        except ValueError:
            pass  # Expected: the inner var name is not a valid env var
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, (
            f"_resolve_env_vars took {elapsed:.2f}s on nested pattern — "
            f"likely ReDoS vulnerability still present"
        )

    def test_resolve_env_vars_long_deeply_nested_string(self):
        """Long string with many ${ sequences but no } must complete quickly."""
        from ol_pool.router import _resolve_env_vars

        # A long string with no closing braces — could cause backtracking
        long_input = "aaa${bbb${ccc${ddd${eee${fff${ggg${hhh${iii${jjj" * 50

        start = time.monotonic()
        try:
            result = _resolve_env_vars(long_input)
        except ValueError:
            pass  # Expected if some var is unset
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, (
            f"_resolve_env_vars took {elapsed:.2f}s on long nested input — "
            f"likely ReDoS vulnerability still present"
        )


# ============================================================================
# Task 4.3: ModelPool silent failure
# ============================================================================


class TestModelPoolSilentFailure:
    """ModelPool must log exceptions instead of silently setting _test_mode."""

    def test_router_init_failure_logs_error(self):
        """When Router() init fails, the exception must be logged at ERROR level
        with full traceback, not silently caught and hidden."""
        from ol_pool.router import ModelPool

        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                mock_router_cls.side_effect = RuntimeError("Router init failed: test")

                with patch("ol_pool.router._logger") as mock_logger:
                    pool = ModelPool(config_path="/nonexistent/config.yaml")

                    # The exception must be logged at ERROR level
                    assert mock_logger.error.called or mock_logger.exception.called, (
                        "No ERROR-level log was emitted for Router init failure"
                    )
                    # _test_mode should be True as fallback
                    assert pool._test_mode is True


# ============================================================================
# Task 4.6: Rate limiting in ModelPool
# ============================================================================


class TestModelPoolRateLimiting:
    """ModelPool must have per-role rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limit_hits_increments_on_rate_limit(self):
        """RateLimitError increments _rate_limit_hits counter."""
        from ol_pool.router import ModelPool
        from unittest.mock import AsyncMock

        with patch("ol_pool.router.load_config") as mock_load_config:
            mock_load_config.return_value = (MagicMock(), None)
            with patch("ol_pool.router.Router") as mock_router_cls:
                async def _mock_acompletion(*args, **kwargs):
                    # First call raises RateLimitError, second succeeds
                    if not hasattr(_mock_acompletion, "_call_count"):
                        _mock_acompletion._call_count = 0
                    _mock_acompletion._call_count += 1
                    if _mock_acompletion._call_count == 1:
                        raise _RateLimitError(
                            "rate limited", "test", "test",
                        )
                    mock_resp = MagicMock()
                    mock_resp.choices = [
                        MagicMock(
                            message=MagicMock(content="translated text")
                        )
                    ]
                    return mock_resp

                mock_router = MagicMock()
                mock_router.acompletion = _mock_acompletion
                mock_router_cls.return_value = mock_router

                pool = ModelPool(config_path="/nonexistent/config.yaml")
                pool._test_mode = False

                # Store original _rate_limit_hits
                hits_before = pool._rate_limit_hits.get("translation", 0)

                result = await pool.translate(
                    "hello", "en", "zh",
                )

                assert pool._rate_limit_hits.get("translation", 0) > hits_before, (
                    f"Expected rate_limit_hits to increment, got "
                    f"before={hits_before}, after={pool._rate_limit_hits}"
                )
                assert result == "translated text", (
                    f"Expected 'translated text' after retry, got {result!r}"
                )
