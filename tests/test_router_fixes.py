"""Tests for OL router code quality fixes (Wave 4).

Covers:
- 4.2: ReDoS in _resolve_env_vars (RED→GREEN)
- 4.3: ModelPool silent failure
- 4.6: Rate limiting in ModelPool
"""
import os
import time
from unittest.mock import patch, MagicMock

import pytest

# Import the exception from the router module itself so it is the same
# class the router's `except RateLimitError` branch catches. Importing
# from litellm.exceptions instead yields conftest's stub class (a different
# object under OMNI_TEST_FAKE_LLM), which never matches.
from ol_pool.router import RateLimitError as _RateLimitError


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
    """Verify ModelPool.__init__ raises a clear error on Router init failure."""

    def test_router_init_failure_raises_init_error(self):
        """When Router() init fails, ModelPool.__init__ raises ModelPoolInitError.

        This is the new behavior (replaces the old silent fallback).
        No more silent _test_mode=True swallowing the error.
        """
        from ol_pool.router import ModelPool, ModelPoolInitError
        from ol_pool.router import _pool_cache
        import os

        # Ensure FAKE_LLM is NOT set so the short-circuit doesn't kick in
        original = os.environ.pop("OMNI_TEST_FAKE_LLM", None)
        try:
            _pool_cache.clear()
            # Patch Router to raise during construction
            # But DON'T make it a MagicMock (line 244 would short-circuit)
            with patch("ol_pool.router.load_config") as mock_load_config:
                mock_load_config.return_value = (MagicMock(), None)
                with patch("ol_pool.router.Router") as mock_router_cls:
                    mock_router_cls.side_effect = RuntimeError("Router init failed: test")

                    with pytest.raises(ModelPoolInitError) as exc_info:
                        ModelPool(config_path="/nonexistent/config.yaml")

                    # Original error is preserved via __cause__
                    assert "Router init failed" in str(exc_info.value.__cause__)
                    assert "OMNI_TEST_FAKE_LLM" in str(exc_info.value)
        finally:
            if original is not None:
                os.environ["OMNI_TEST_FAKE_LLM"] = original
            _pool_cache.clear()


# ============================================================================
# Issue #32 Part A: ModelPoolInitError on Router init failure
# ============================================================================


class TestModelPoolInitError:
    """New tests for the ModelPoolInitError exception class."""

    def test_missing_env_var_degrades_pool_instead_of_failing_init(self, monkeypatch):
        """Real-world scenario: one provider's API-key env var is unset.

        OL#99: the pool must degrade to the remaining priorities, not fail.
        Only a role that loses EVERY model to unconfigured keys is a hard
        error. Provider-agnostic: variable names are read from
        config/default.yaml's llm_pool instead of hardcoding a provider key.
        """
        import yaml
        from pathlib import Path

        from ol_pool.router import ModelPool
        from ol_pool.router import _pool_cache
        import ol_config.loader as loader_mod

        config_path = (
            Path(__file__).resolve().parents[1] / "config" / "default.yaml"
        )
        pool = yaml.safe_load(config_path.read_text(encoding="utf-8"))["llm_pool"]
        first_role = next(iter(pool))
        entries = pool[first_role]
        api_key_ref = entries[0]["api_key"]
        assert (
            isinstance(api_key_ref, str)
            and api_key_ref.startswith("${")
            and api_key_ref.endswith("}")
        ), f"first pool entry must use a ${{ENV_VAR}} reference, got {api_key_ref!r}"
        env_var = api_key_ref.strip()[2:-1]
        assert len(entries) > 1, "need a lower-priority model to degrade onto"

        # Ensure FAKE_LLM is NOT set (otherwise __init__ short-circuits).
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
        monkeypatch.delenv(env_var, raising=False)
        # Neutralize loader._load_env_file: it loads Omni_Localizer/.env via a
        # FIXED path (loader.py) and would re-introduce the popped var through
        # os.environ.setdefault, masking the missing-var path.
        monkeypatch.setattr(loader_mod, "_load_env_file", lambda: None)

        _pool_cache.clear()
        try:
            with patch("ol_pool.router.Router", MagicMock()):
                built = ModelPool(str(config_path))
            kept = [m.model for m in built._usable_by_role[first_role]]
            assert entries[0]["model"] not in kept
            assert kept, f"{first_role} must keep its configured fallbacks"
        finally:
            _pool_cache.clear()

    def test_all_env_vars_unset_for_a_role_raises_init_error(self, monkeypatch):
        """A role with no usable model left is still fail-closed (OL#99)."""
        import re
        import yaml
        from pathlib import Path

        from ol_pool.router import ModelPool, ModelPoolInitError
        from ol_pool.router import _pool_cache
        import ol_config.loader as loader_mod

        config_path = (
            Path(__file__).resolve().parents[1] / "config" / "default.yaml"
        )
        pool = yaml.safe_load(config_path.read_text(encoding="utf-8"))["llm_pool"]
        first_role = next(iter(pool))
        refs = " ".join(
            f"{entry.get('api_key') or ''} {entry.get('base_url') or ''}"
            for entry in pool[first_role]
        )
        env_vars = sorted(set(re.findall(r"\$\{(\w+)\}", refs)))
        assert env_vars, f"{first_role} must reference env vars"

        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
        for var in env_vars:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(loader_mod, "_load_env_file", lambda: None)

        _pool_cache.clear()
        try:
            with patch("ol_pool.router.Router", MagicMock()):
                with pytest.raises(ModelPoolInitError) as exc_info:
                    ModelPool(str(config_path))
            message = str(exc_info.value)
            assert first_role in message
            for var in env_vars:
                assert var in message
        finally:
            _pool_cache.clear()

    def test_fake_llm_short_circuit_still_works(self):
        """Regression: OMNI_TEST_FAKE_LLM=1 still uses _FakeModelPool, no raise."""
        from ol_pool.router import ModelPool
        from ol_pool.router import _pool_cache
        import os

        original = os.environ.get("OMNI_TEST_FAKE_LLM")
        os.environ["OMNI_TEST_FAKE_LLM"] = "1"
        try:
            _pool_cache.clear()
            pool = ModelPool("config/default.yaml")
            assert pool._test_mode is True
            assert hasattr(pool, "_fake_pool")
            assert pool._fake_pool is not None
        finally:
            if original is None:
                os.environ.pop("OMNI_TEST_FAKE_LLM", None)
            else:
                os.environ["OMNI_TEST_FAKE_LLM"] = original
            _pool_cache.clear()


# ============================================================================
# Task 4.6: Rate limiting in ModelPool
# ============================================================================


class TestModelPoolRateLimiting:
    """ModelPool must have per-role rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limit_hits_increments_on_rate_limit(self):
        """RateLimitError increments _rate_limit_hits counter."""
        import os
        from ol_pool.router import ModelPool

        original = os.environ.pop("OMNI_TEST_FAKE_LLM", None)
        try:
            with patch("ol_pool.router.load_config") as mock_load_config:
                mock_load_config.return_value = (MagicMock(), None)
                with patch("ol_pool.router.Router") as mock_router_cls:
                    async def _mock_acompletion(*args, **kwargs):
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
        finally:
            if original is not None:
                os.environ["OMNI_TEST_FAKE_LLM"] = original
