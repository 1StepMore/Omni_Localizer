"""E2E-83 regression tests.

The bug: ``ModelPool.__init__`` initialized the litellm Router with
``optional_pre_call_checks=['enforce_model_rate_limits']``. This is a
litellm built-in that maintains a per-model RPM token bucket and
synchronously raises ``litellm.RouterRateLimitError`` when the
bucket is empty.

For a typical OL setup with NVIDIA free-tier models
(``requests_per_minute: 40``), a single large request (~14s, 26K
tokens) depletes most of the bucket. The NEXT request, even a small
one, gets rejected by the pre-call check before the actual LLM call
is made.

The fix: drop the ``optional_pre_call_checks`` arg. Per-model RPM
is still set in each ``litellm_params['rpm']`` entry, but the
rejection now comes from the provider's HTTP 429 (handled by the
existing translate() exponential backoff) instead of from
litellm's in-process bucket.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")



_CONFIG_PATH = str(
    Path(__file__).resolve().parents[1] / "config" / "default.yaml"
)


class TestRouterNotConfiguredWithEnforceModelRateLimits:
    """The pre-call check that causes E2E-83 must not be set on Router."""

    def test_optional_pre_call_checks_not_passed_to_router(self):
        """Capture the kwargs ModelPool passes to litellm.Router and
        assert that ``optional_pre_call_checks=['enforce_model_rate_limits']``
        is NOT among them (E2E-83 root cause)."""
        from ol_pool import router as router_mod

        with patch("ol_pool.router.Router") as MockRouter:
            MockRouter.return_value = MagicMock()
            router_mod._pool_cache.clear()
            # Force a fresh ModelPool construction under the patched Router.
            from ol_pool.router import ModelPool
            ModelPool(_CONFIG_PATH)

        # Find the call that constructed Router.
        router_call = None
        for call in MockRouter.call_args_list:
            args, kwargs = call
            if "model_list" in kwargs:
                router_call = call
                break
        assert router_call is not None, (
            f"ModelPool must construct litellm.Router. "
            f"Got calls: {MockRouter.call_args_list}"
        )
        _, kwargs = router_call
        # E2E-83 root cause: this argument was the source of the
        # fast-fail for large requests.
        bad_value = ["enforce_model_rate_limits"]
        opcc = kwargs.get("optional_pre_call_checks")
        assert opcc != bad_value, (
            f"ModelPool must not enable 'enforce_model_rate_limits' pre-call "
            f"check. E2E-83 root cause: this litellm hook maintains a per-model "
            f"token bucket and raises RouterRateLimitError synchronously, which "
            f"fast-fails large requests and triggers 10/20/40s backoffs in the "
            f"translate() retry loop. kwargs: {kwargs}"
        )


class TestLargeContentWarning:
    """A warning must be logged for unusually large requests so the
    user has visibility into why translation is slow."""

    def _make_pool(self):
        """Build a ModelPool that exercises the real translate() code
        path. The FAKE_LLM seam in ol_cli.py and the conftest's
        heavy-import blocker would otherwise short-circuit before
        our warning code runs."""
        from ol_pool.router import ModelPool
        from ol_pool import router as router_mod
        router_mod._pool_cache.clear()
        pool = ModelPool(_CONFIG_PATH)
        pool._test_mode = False
        from unittest.mock import MagicMock

        class FakeRouter:
            async def acompletion(self, *a, **kw):
                from litellm.types.utils import ModelResponse
                mr = ModelResponse()
                mr.choices = [MagicMock()]
                mr.choices[0].message.content = "[zh] " + (
                    kw.get("messages", [{}])[-1].get("content", "")
                )
                return mr

        pool._router = FakeRouter()
        return pool

    def test_large_request_logs_warning(self, caplog):
        """A 60KB+ request must produce a 'Large translation request'
        warning so callers (CLI / MCP) can show it to the user."""
        import asyncio
        import logging
        pool = self._make_pool()

        content = "Hello world. " * 15000  # ~195KB

        with caplog.at_level(logging.WARNING, logger="pool"):
            async def go():
                return await pool.translate(content, "en", "zh", context=None)
            asyncio.run(go())

        warnings = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert any("Large translation request" in w for w in warnings), (
            f"Large content must emit a 'Large translation request' "
            f"warning. Got warnings: {warnings}"
        )

    def test_small_request_does_not_warn(self, caplog):
        """A small request (<50K chars) must NOT emit the warning."""
        import asyncio
        import logging
        pool = self._make_pool()

        content = "Hello world."  # tiny

        with caplog.at_level(logging.WARNING, logger="pool"):
            async def go():
                return await pool.translate(content, "en", "zh", context=None)
            asyncio.run(go())

        warnings = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert not any(
            "Large translation request" in w for w in warnings
        ), f"Small content must NOT trigger the large-request warning. Got: {warnings}"


class TestRouterRateLimitErrorNoLongerCausesLongBackoff:
    """When RouterRateLimitError IS raised, the translate() retry
    loop must not wait the full 10/20/40s exponential backoff (the
    pre-call check used to be the source of these errors; now that
    it's removed, the rate-limit error path is reserved for real
    provider 429s which DO benefit from backoff).
    """
    def test_router_rate_limit_does_not_cause_70s_backoff(self, caplog):
        import asyncio
        import time
        from ol_pool.router import ModelPool
        from ol_pool import router as router_mod
        router_mod._pool_cache.clear()
        pool = ModelPool(_CONFIG_PATH)
        # Bypass FAKE_LLM
        pool._test_mode = False

        class FastFailRouter:
            def __init__(self):
                self.calls = 0
            async def acompletion(self, *a, **kw):
                self.calls += 1
                # Use a generic Exception to mimic RouterRateLimitError
                # since litellm is stubbed by conftest.
                raise Exception(
                    "RouterRateLimitError: Model rate limit exceeded"
                )

        fast = FastFailRouter()
        pool._router = fast
        content = "Hello world. " * 6000

        async def go():
            start = time.monotonic()
            try:
                await pool.translate(content, "en", "zh", context=None)
            except Exception:
                pass
            return time.monotonic() - start

        elapsed = asyncio.run(go())
        # Pre-fix: 10s + 20s + 40s = ~70s minimum.
        # The backoff is still in translate() (for real provider 429s)
        # so we don't expect fast-fail; we just verify it's not the
        # full 70s loop. We accept <30s as "significantly better than 70s".
        assert elapsed < 30, (
            f"Rate-limit error path should not require 70s+ of backoffs. "
            f"Elapsed: {elapsed:.1f}s. E2E-83 may have regressed."
        )
