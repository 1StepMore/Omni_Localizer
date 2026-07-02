"""T2.2 regression tests.

Verifies that ``ModelPool.translate()`` accepts a
``system_message_override`` keyword argument. When the override is
provided, the LLM system message is replaced with the custom string.
The default behavior (no override) is unchanged.
"""
from __future__ import annotations

import asyncio
import inspect
import os
from pathlib import Path

os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

import pytest

from ol_pool.router import ModelPool


_CONFIG_PATH = str(
    Path(__file__).resolve().parents[1] / "config" / "default.yaml"
)


@pytest.fixture
def pool():
    from ol_pool import router as router_module
    router_module._pool_cache.clear()
    return ModelPool(_CONFIG_PATH)


class TestSystemMessageOverrideSignature:
    """Pin the new parameter exists on the public signature."""

    def test_translate_signature_has_system_message_override(self, pool):
        sig = inspect.signature(pool.translate)
        assert "system_message_override" in sig.parameters, (
            "ModelPool.translate() must accept 'system_message_override' "
            "kwarg (T2.2 — used by Polish pass to avoid system-message conflict)"
        )

    def test_translate_signature_default_is_none(self, pool):
        sig = inspect.signature(pool.translate)
        param = sig.parameters["system_message_override"]
        assert param.default is None, (
            f"system_message_override must default to None, got {param.default!r}"
        )


class TestSystemMessageOverrideRuntime:
    """Verify the parameter is accepted at runtime without TypeError."""

    def test_translate_with_override_does_not_raise(self, pool):
        """Passing a custom override must not raise TypeError."""
        result = asyncio.run(
            pool.translate(
                "Hello world", "en", "zh",
                context=None,
                system_message_override="Custom system message for testing",
            )
        )
        assert isinstance(result, str)
        assert result  # non-empty

    def test_translate_without_override_unchanged(self, pool):
        """Default behavior (no override) is unchanged."""
        result = asyncio.run(pool.translate("Hello", "en", "zh", context=None))
        assert isinstance(result, str)
        assert result

    def test_translate_with_empty_override_uses_default(self, pool):
        """Empty string override is treated as 'no override' (None)."""
        result = asyncio.run(
            pool.translate(
                "Hello", "en", "zh", context=None,
                system_message_override="",
            )
        )
        assert isinstance(result, str)


class TestSystemMessageOverrideIsApplied:
    """Deeper test: verify the override is actually used in the system message.

    Uses monkey-patching to capture the messages payload sent to the LLM.
    FAKE_LLM mode short-circuits before message construction, so this test
    temporarily disables _test_mode and uses a mock router.
    """

    def test_override_replaces_default_system_message(self, monkeypatch):
        """When override is set, the LLM receives the custom system message."""
        import pybreaker

        from ol_pool import router as router_module
        router_module._pool_cache.clear()

        captured_messages: list[list[dict]] = []

        class _MockMessage:
            def __init__(self, content: str) -> None:
                self.content = content

        class _MockChoice:
            def __init__(self, content: str) -> None:
                self.message = _MockMessage(content)

        class _MockResponse:
            def __init__(self, content: str) -> None:
                self.choices = [_MockChoice(content)]

        class _MockRouter:
            async def acompletion(self, *args, **kwargs):
                msgs = kwargs.get("messages") or (args[0] if args else [])
                captured_messages.append(list(msgs))
                return _MockResponse("out")

        # Circuit breaker required when _test_mode is False
        pool = ModelPool(_CONFIG_PATH)
        pool._test_mode = False
        pool._router = _MockRouter()
        pool._cache_enabled = False
        pool._cache = None  # type: ignore[assignment]
        pool._breakers = {
            role: pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60, name=role)
            for role in ("translation", "judging", "restoration", "profiling")
        }

        custom_msg = "You are a consistency checker for translated documents."
        asyncio.run(
            pool.translate(
                "Hello", "en", "zh",
                context=None,
                system_message_override=custom_msg,
            )
        )

        assert len(captured_messages) == 1
        msgs = captured_messages[0]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == custom_msg

    def test_no_override_uses_default_system_message(self, monkeypatch):
        """When override is None, the LLM receives the default system message."""
        import pybreaker

        from ol_pool import router as router_module
        router_module._pool_cache.clear()

        captured_messages: list[list[dict]] = []

        class _MockMessage:
            def __init__(self, content: str) -> None:
                self.content = content

        class _MockChoice:
            def __init__(self, content: str) -> None:
                self.message = _MockMessage(content)

        class _MockResponse:
            def __init__(self, content: str) -> None:
                self.choices = [_MockChoice(content)]

        class _MockRouter:
            async def acompletion(self, *args, **kwargs):
                msgs = kwargs.get("messages") or (args[0] if args else [])
                captured_messages.append(list(msgs))
                return _MockResponse("out")

        pool = ModelPool(_CONFIG_PATH)
        pool._test_mode = False
        pool._router = _MockRouter()
        pool._cache_enabled = False
        pool._cache = None  # type: ignore[assignment]
        pool._breakers = {
            role: pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60, name=role)
            for role in ("translation", "judging", "restoration", "profiling")
        }

        asyncio.run(pool.translate("Hello", "en", "zh", context=None))

        assert len(captured_messages) == 1
        msgs = captured_messages[0]
        assert msgs[0]["role"] == "system"
        assert "professional translator" in msgs[0]["content"]
