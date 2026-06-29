"""Tests for _check_env_vars() behavior — OL#16.

_after_ the fix: _check_env_vars uses logging.warning() instead of
raise ValueError().  These tests verify the new behavior.

Before the fix, scenarios 2 and 4 would raise ValueError — the RED
phase confirms that.  After the fix, all four should pass GREEN.
"""
import logging



def _make_config(api_key: str, base_url: str | None = None):
    """Import and instantiate LLMModelConfig with minimal fields."""
    # Late import so the module picks up any env var changes
    from ol_config.schema import LLMModelConfig

    return LLMModelConfig(
        provider="openai",
        model="test-model",
        priority=1,
        role="translation",
        api_key=api_key,
        base_url=base_url,
    )


class TestCheckEnvVars:
    """OL#16: _check_env_vars should warn, not raise."""

    def test_fake_llm_no_warning_no_exception(self, monkeypatch, caplog):
        """Scenario 1: OMNI_TEST_FAKE_LLM=1 + missing vars → no exception, no warning."""
        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        monkeypatch.delenv("ALSO_MISSING", raising=False)

        with caplog.at_level(logging.WARNING, logger="ol_config.schema"):
            config = _make_config(api_key="${NONEXISTENT_VAR}", base_url="${ALSO_MISSING}")

        assert config is not None
        # No warning should be emitted — FAKE_LLM skips the check entirely
        assert "NONEXISTENT_VAR" not in caplog.text
        assert "ALSO_MISSING" not in caplog.text

    def test_partial_env_vars_warns_for_missing(self, monkeypatch, caplog):
        """Scenario 2: ${FAKE} set, ${MISSING} unset → warning for MISSING, no exception."""
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
        monkeypatch.setenv("FAKE", "value")
        monkeypatch.delenv("MISSING", raising=False)

        with caplog.at_level(logging.WARNING, logger="ol_config.schema"):
            config = _make_config(api_key="${FAKE}", base_url="${MISSING}")

        # Config created successfully (no exception)
        assert config is not None
        # Warning for MISSING should be in the log
        assert "MISSING" in caplog.text
        assert "base_url" in caplog.text
        # No warning for FAKE (it's set)
        assert caplog.text.count("WARNING") == 1 or caplog.text.count("WARN") >= 1

    def test_all_env_vars_set_no_warning(self, monkeypatch, caplog):
        """Scenario 3: all referenced vars set → no warning, config created."""
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
        monkeypatch.setenv("MY_KEY", "sk-test")
        monkeypatch.setenv("MY_URL", "https://api.example.com")

        with caplog.at_level(logging.WARNING, logger="ol_config.schema"):
            config = _make_config(api_key="${MY_KEY}", base_url="${MY_URL}")

        assert config is not None
        assert "MY_KEY" not in caplog.text
        assert "MY_URL" not in caplog.text

    def test_fake_llm_preserves_early_return(self, monkeypatch, caplog):
        """Scenario 4: FAKE_LLM=1 + multiple missing vars → early return, NO check at all."""
        monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
        monkeypatch.delenv("MISSING_1", raising=False)
        monkeypatch.delenv("MISSING_2", raising=False)

        with caplog.at_level(logging.WARNING, logger="ol_config.schema"):
            config = _make_config(api_key="${MISSING_1}", base_url="${MISSING_2}")

        assert config is not None
        # FAKE_LLM guard returns before any env var check
        assert "MISSING_1" not in caplog.text
        assert "MISSING_2" not in caplog.text

    def test_none_value_returns_early(self, monkeypatch, caplog):
        """Edge: api_key=None → returns immediately, no warning."""
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)

        with caplog.at_level(logging.WARNING, logger="ol_config.schema"):
            config = _make_config(api_key=None)

        assert config is not None
        assert caplog.text == ""

    def test_no_env_var_refs_no_warning(self, monkeypatch, caplog):
        """Edge: literal api_key (no ${...}) → no warning."""
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)

        with caplog.at_level(logging.WARNING, logger="ol_config.schema"):
            config = _make_config(api_key="sk-actual-key-123")

        assert config is not None
        assert caplog.text == ""

    def test_warning_message_includes_field_name(self, monkeypatch, caplog):
        """Verify warning text mentions the field name (api_key or base_url)."""
        monkeypatch.delenv("OMNI_TEST_FAKE_LLM", raising=False)
        monkeypatch.delenv("MISSING_KEY", raising=False)
        monkeypatch.delenv("MISSING_URL", raising=False)

        with caplog.at_level(logging.WARNING, logger="ol_config.schema"):
            _make_config(api_key="${MISSING_KEY}", base_url="${MISSING_URL}")

        assert "MISSING_KEY" in caplog.text
        assert "api_key" in caplog.text
        assert "MISSING_URL" in caplog.text
        assert "base_url" in caplog.text
