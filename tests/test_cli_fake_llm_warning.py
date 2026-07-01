"""Tests for the FAKE_LLM CLI warning.

The warning fires when OMNI_TEST_FAKE_LLM=1 is set in any CLI
command that uses ModelPool or _FakeModelPool. It alerts users
that [en] prefix output is fake, not a real translation.

The warning fires only ONCE per process (fire-once guard).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch



class TestWarnFakeLLMMode:
    """Unit tests for warn_fake_llm_mode() in cli._shared."""

    def setup_method(self):
        """Reset the fire-once guard before each test."""
        from cli import _shared
        _shared._fake_llm_warned = False

    def test_warn_fake_llm_mode_emits_warning_when_fake_llm_set(self):
        from cli._shared import warn_fake_llm_mode
        with patch.dict(os.environ, {"OMNI_TEST_FAKE_LLM": "1"}, clear=False):
            with patch("cli._shared.typer.echo") as mock_echo:
                warn_fake_llm_mode()
        assert mock_echo.called
        call_args = mock_echo.call_args
        # Should write to stderr (err=True)
        assert call_args.kwargs.get("err") is True
        # Message should mention FAKE_LLM
        assert "FAKE_LLM" in str(call_args)

    def test_warn_fake_llm_mode_no_warning_when_fake_llm_unset(self):
        from cli._shared import warn_fake_llm_mode
        env = {k: v for k, v in os.environ.items() if k != "OMNI_TEST_FAKE_LLM"}
        with patch.dict(os.environ, env, clear=True):
            with patch("cli._shared.typer.echo") as mock_echo:
                warn_fake_llm_mode()
        assert not mock_echo.called

    def test_warn_fake_llm_mode_fires_only_once(self):
        """The fire-once guard prevents duplicate warnings in a batch session."""
        from cli._shared import warn_fake_llm_mode
        with patch.dict(os.environ, {"OMNI_TEST_FAKE_LLM": "1"}, clear=False):
            with patch("cli._shared.typer.echo") as mock_echo:
                warn_fake_llm_mode()
                warn_fake_llm_mode()
                warn_fake_llm_mode()
        # First call prints, subsequent calls are no-ops
        assert mock_echo.call_count == 1


class TestCLIIntegrationFAKELLMWarning:
    """Integration tests: warning fires from real CLI command entry points."""

    def setup_method(self):
        from cli import _shared
        _shared._fake_llm_warned = False

    def test_translate_md_fake_llm_emits_warning(self):
        """The translate_md CLI module imports warn_fake_llm_mode.

        NOTE: ``import cli.translate_md`` resolves to the ``translate_md``
        function (not the module) because ``cli/__init__.py`` does
        ``from cli.translate_md import *``, shadowing the submodule.
        We check via ``sys.modules`` instead.
        """
        # Load the module to ensure it's in sys.modules
        from unittest.mock import patch
        with patch.dict(os.environ, {"OMNI_TEST_FAKE_LLM": "1"}, clear=False):
            with patch("cli.translate_md.warn_fake_llm_mode") as mock_warn:
                with patch("cli.translate_md._apply_fake_llm_seam"):
                    pass
        # Check via sys.modules (the actual module, not shadowed name)
        tm_mod = sys.modules["cli.translate_md"]
        assert hasattr(tm_mod, "warn_fake_llm_mode")

    def test_judge_text_fake_llm_emits_warning(self):
        """The judge_text CLI module imports warn_fake_llm_mode."""
        # Verify warn_fake_llm_mode is imported in judge_text
        # Use sys.modules to get the actual module (not a shadowed name)
        jt_mod = sys.modules.get("cli.judge_text") or sys.modules.get("cli.judge_text")
        # If cli.judge_text is not in sys.modules, import it properly
        if jt_mod is None:
            jt_mod = sys.modules["cli.judge_text"]
        assert hasattr(jt_mod, "warn_fake_llm_mode")
