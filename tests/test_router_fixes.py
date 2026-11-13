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

    def test_missing_env_var_degrades_pool_instead_of_failing_init(self, monkeypatch, tmp_path):
        """Real-world scenario: one provider's API-key env var is unset.

        OL#99: the pool must degrade to the remaining priorities, not fail.
        Only a role that loses EVERY model to unconfigured keys is a hard
        error. Uses a synthetic two-provider pool because the shipped
        config/default.yaml is now Zhipu-only (OL#183); a single provider
        cannot demonstrate cross-provider degradation.
        """
        from ol_pool.router import ModelPool
        from ol_pool.router import _pool_cache
        import ol_config.loader as loader_mod

        config_path = tmp_path / "two-provider.yaml"
        entries = []
        for role in ("translation", "judging", "restoration"):
            entries.append(
                f"  {role}:\n"
                f"  - provider: openai\n"
                f"    model: {role}-primary\n"
                f"    api_key: ${{TEST_PRIMARY_KEY}}\n"
                f"    base_url: https://primary.example/v1\n"
                f"    timeout: 120.0\n"
                f"    priority: 1\n"
                f"    role: {role}\n"
                f"  - provider: openai\n"
                f"    model: {role}-fallback\n"
                f"    api_key: ${{TEST_FALLBACK_KEY}}\n"
                f"    base_url: https://fallback.example/v1\n"
                f"    timeout: 120.0\n"
                f"    priority: 2\n"
                f"    role: {role}\n"
            )
        config_path.write_text(
            "project_id: test\nsource_lang: en\ntarget_lang: zh\nllm_pool:\n"
            + "".join(entries),
            encoding="utf-8",
        )

        # Ensure FAKE_LLM is NOT set (otherwise __init__ short-circuits).
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
        monkeypatch.delenv("TEST_PRIMARY_KEY", raising=False)
        monkeypatch.setenv("TEST_FALLBACK_KEY", "sk-test-fallback")
        # Neutralize loader._load_env_file: it loads Omni_Localizer/.env via a
        # FIXED path (loader.py) and would re-introduce the popped var through
        # os.environ.setdefault, masking the missing-var path.
        monkeypatch.setattr(loader_mod, "_load_env_file", lambda: None)

        _pool_cache.clear()
        try:
            with patch("ol_pool.router.Router", MagicMock()):
                built = ModelPool(str(config_path))
            kept = [m.model for m in built._usable_by_role["translation"]]
            assert "translation-primary" not in kept
            assert "translation-fallback" in kept, (
                "translation must keep its configured fallback"
            )
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


# ============================================================================
# OL#195: an env var set to the EMPTY string is unusable, same as unset.
# Previously `router._unresolved_env_vars` used `os.environ.get(name) is
# None`, so a var present-but-empty survived the partition filter and its
# empty api_key was sent to the provider as-is (401 / "api key not found"
# with no startup hint). doctor/precheck already treated "" as absent.
# ============================================================================


class TestEmptyEnvVarResolution:
    """OL#195: empty-string ${VAR} resolution must fail loudly at pool load."""

    def _entry(self, api_key: str, priority: int, var_suffix: str):
        from ol_config.schema import LLMModelConfig

        return LLMModelConfig(
            provider="openai",
            model=f"m{priority}-{var_suffix}",
            priority=priority,
            api_key=api_key,
            base_url="https://pool-unittest.invalid/v1",
            role="translation",
        )

    def test_unresolved_env_vars_treats_empty_as_missing(self, monkeypatch):
        from ol_pool.router import _unresolved_env_vars

        monkeypatch.setenv("OL195_EMPTY_KEY", "")
        monkeypatch.delenv("OL195_UNSET_KEY", raising=False)
        entry = self._entry("${OL195_EMPTY_KEY}", 1, "empty")

        assert _unresolved_env_vars(entry) == ["OL195_EMPTY_KEY"]

    def test_partition_skips_empty_key_model_but_keeps_healthy_one(
        self, monkeypatch,
    ):
        from ol_config.schema import LLMPoolConfig
        from ol_pool.router import partition_usable_models

        monkeypatch.setenv("OL195_EMPTY_KEY", "")
        monkeypatch.setenv("OL195_HEALTHY_KEY", "sk-healthy-not-a-real-key")
        pool = LLMPoolConfig(
            translation=[
                self._entry("${OL195_HEALTHY_KEY}", 1, "healthy"),
                self._entry("${OL195_EMPTY_KEY}", 2, "empty"),
            ],
            judging=[
                self._entry("${OL195_HEALTHY_KEY}", 1, "healthy"),
                self._entry("${OL195_EMPTY_KEY}", 2, "empty"),
            ],
            restoration=[
                self._entry("${OL195_HEALTHY_KEY}", 1, "healthy"),
                self._entry("${OL195_EMPTY_KEY}", 2, "empty"),
            ],
        )

        usable, skipped = partition_usable_models(pool)

        # The healthy priority-1 tier survives in every role; the empty-key
        # tier is skipped WITH its variable name (never its value).
        for role in ("translation", "judging", "restoration"):
            assert [m.model for m in usable[role]] == ["m1-healthy"]
        skipped_vars = {var for _r, _m, missing in skipped for var in missing}
        assert skipped_vars == {"OL195_EMPTY_KEY"}
        assert all(m.model == "m2-empty" for _r, m, _missing in skipped)

    def test_pool_init_fails_loudly_when_every_tier_is_empty_or_unset(
        self, tmp_path, monkeypatch,
    ):
        # FAKE_LLM short-circuits before load_config, so unset it to exercise
        # the real pool-load path (restored by monkeypatch afterwards).
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
        monkeypatch.setenv("OL195_EMPTY_KEY", "")
        monkeypatch.delenv("OL195_UNSET_KEY", raising=False)

        entry_tpl = (
            "    - provider: openai\n"
            "      model: {model}\n"
            "      api_key: '{api_key}'\n"
            "      base_url: https://pool-unittest.invalid/v1\n"
            "      priority: {priority}\n"
            "      role: {role}\n"
        )
        roles = {}
        for role in ("translation", "judging", "restoration"):
            roles[role] = (
                entry_tpl.format(model="a", api_key="${OL195_EMPTY_KEY}", priority=1, role=role)
                + entry_tpl.format(model="b", api_key="${OL195_UNSET_KEY}", priority=2, role=role)
            )
        config_text = "llm_pool:\n" + "".join(
            f"  {role}:\n{entries}" for role, entries in roles.items()
        )
        config_file = tmp_path / "pool_empty_keys.yaml"
        config_file.write_text(config_text, encoding="utf-8")

        from ol_pool.router import ModelPool, ModelPoolInitError

        with pytest.raises(ModelPoolInitError) as excinfo:
            ModelPool(config_path=str(config_file))

        # Both variable NAMES appear in the startup error; no values printed.
        assert "OL195_EMPTY_KEY" in str(excinfo.value)
        assert "OL195_UNSET_KEY" in str(excinfo.value)
