"""A12.4 tests: Placeholder restoration in ol_restoration + CLI wiring (PR13).

TDD: written AFTER the production module is sketched (A12.4
"Restoration wiring"). The two tests cover the two contract points
required by the spec:

* ``test_restoration_recovers_stripped_placeholders`` — when the
  post-translate text is missing one of the placeholders the caller
  expected, the Restorer delegates to the LLM and returns the
  LLM-restored text.
* ``test_restoration_disabled_via_flag`` — when ``--no-restoration`` is
  passed to ``translate-md``, the Restorer is bypassed (no LLM call,
  text returned unchanged).

A third test (``test_restoration_no_missing_placeholders_is_noop``) is
included as a contract regression: the fast-path must not call the LLM
when no placeholders are missing.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

if sys.platform == "win32":
    import unittest.mock
    sys.modules.setdefault("fcntl", unittest.mock.MagicMock())


import ol_cli
from ol_cli import app
from ol_restoration import Restorer, extract_placeholders


runner = CliRunner()


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_GLOSSARY = FIXTURES_DIR / "sample_glossary.json"


# ============================================================================
# Fixtures
# ============================================================================


class _StubPool:
    """A minimal ``model_pool`` stub.

    The real ``ModelPool.translate`` is an async coroutine; the Restorer
    needs an object with an async ``translate(text, source_lang,
    target_lang, ...)`` method. ``AsyncMock`` is the lightest weight —
    no real network, no real config loader.
    """

    def __init__(self, response: str = "") -> None:
        # We use AsyncMock directly so the assert ``await pool.translate``
        # works seamlessly. The ``return_value`` is the string the LLM
        # "returned".
        self.translate = AsyncMock(return_value=response)
        self.calls: list[dict[str, Any]] = []

    async def _record(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append({"args": args, "kwargs": kwargs})
        return await self.translate(*args, **kwargs)


@pytest.fixture
def sample_md(tmp_path):
    f = tmp_path / "input.md"
    f.write_text(
        "Click {{_OL_XTAG_1_}} here to continue.\n",
        encoding="utf-8",
    )
    return f


# ============================================================================
# test_restoration_recovers_stripped_placeholders
# ============================================================================


class TestRestorationRecoversStrippedPlaceholders:
    """The Restorer must delegate to the LLM and return its response when
    the post-translate text is missing one or more placeholders."""

    def test_restorer_calls_llm_and_returns_response(self):
        """Direct Restorer unit test: stripped placeholder → LLM called → LLM
        response returned (which contains the placeholder restored)."""
        original = "Click {{_OL_XTAG_1_}} here to continue."
        # The LLM has stripped the placeholder; we want it back.
        translated = "Click  here to continue."
        placeholders = ["{{_OL_XTAG_1_}}"]

        # The LLM's "response" — what it should return is the translated
        # text with the placeholder re-inserted at the original position.
        llm_response = "Click {{_OL_XTAG_1_}} here to continue."

        pool = _StubPool(response=llm_response)
        # The Restorer calls ``pool.translate`` synchronously via
        # ``loop.run_until_complete`` / ``asyncio.run``; we need to be
        # inside an event loop to keep the test self-contained. The
        # Restorer handles both paths, so test the no-loop path first.
        restorer = Restorer(model_pool=pool)

        result = restorer.restore(translated, original, placeholders)

        # The LLM was called exactly once.
        assert pool.translate.await_count == 1, (
            f"expected 1 LLM call, got {pool.translate.await_count}"
        )
        # And the result is the LLM's response.
        assert result == llm_response, (
            f"expected restored text {llm_response!r}, got {result!r}"
        )
        # The LLM prompt must mention the missing placeholder so the
        # model knows what to put back.
        call_args = pool.translate.call_args
        prompt_arg = call_args.args[0] if call_args.args else call_args.kwargs.get(
            "text", call_args.kwargs.get("prompt", "")
        )
        assert "{{_OL_XTAG_1_}}" in prompt_arg, (
            f"missing placeholder {{_OL_XTAG_1_}} not in LLM prompt: {prompt_arg!r}"
        )

    def test_restorer_finds_missing_placeholders(self):
        """The Restorer must report the right ``missing`` set, even when
        only one of many placeholders is stripped."""
        original = (
            "Use {{_OL_XTAG_1_}} the API {{_OL_XTAG_2_}} for {{_OL_XTAG_3_}} now."
        )
        # Two of three placeholders survived; the LLM stripped #2.
        translated = "Use {{_OL_XTAG_1_}} the API  for {{_OL_XTAG_3_}} now."
        placeholders = [
            "{{_OL_XTAG_1_}}",
            "{{_OL_XTAG_2_}}",
            "{{_OL_XTAG_3_}}",
        ]
        pool = _StubPool(
            response="Use {{_OL_XTAG_1_}} the API {{_OL_XTAG_2_}} "
            "for {{_OL_XTAG_3_}} now.",
        )
        restorer = Restorer(model_pool=pool)

        result = restorer.restore(translated, original, placeholders)

        assert pool.translate.await_count == 1
        call_args = pool.translate.call_args
        prompt_arg = call_args.args[0] if call_args.args else call_args.kwargs.get(
            "text", call_args.kwargs.get("prompt", "")
        )
        # Only the missing placeholder should be in the "MISSING" list.
        assert "{{_OL_XTAG_2_}}" in prompt_arg
        # And the prompt must NOT list the surviving placeholders in the
        # "MISSING" block (the default template's "MISSING placeholders"
        # section is a bullet list — easiest test is to check the LLM
        # prompt didn't have a bullet for the ones that are already
        # present).
        missing_block = prompt_arg.split("MISSING placeholders to restore")[-1]
        assert "{{_OL_XTAG_1_}}" not in missing_block.split("\n\nRules:")[0]
        assert "{{_OL_XTAG_3_}}" not in missing_block.split("\n\nRules:")[0]

    def test_no_op_when_all_placeholders_present(self):
        """Regression: the fast-path must not call the LLM at all when
        every expected placeholder is already in the text."""
        text = "Use {{_OL_XTAG_1_}} the API {{_OL_XTAG_2_}} now."
        original = text
        placeholders = ["{{_OL_XTAG_1_}}", "{{_OL_XTAG_2_}}"]

        pool = _StubPool(response="UNEXPECTED")
        restorer = Restorer(model_pool=pool)

        result = restorer.restore(text, original, placeholders)

        # No LLM call — fast path.
        assert pool.translate.await_count == 0
        # And the text is returned unchanged.
        assert result == text

    def test_no_op_when_model_pool_is_none(self):
        """When the Restorer is constructed without a model_pool, the
        call is a no-op (useful for ``--no-restoration`` and for tests)."""
        text = "Use  the API  now."  # both placeholders missing
        original = "Use {{_OL_XTAG_1_}} the API {{_OL_XTAG_2_}} now."
        placeholders = ["{{_OL_XTAG_1_}}", "{{_OL_XTAG_2_}}"]

        restorer = Restorer(model_pool=None)

        result = restorer.restore(text, original, placeholders)

        # Graceful: text returned unchanged, no exception, no LLM call.
        assert result == text

    def test_no_op_when_llm_returns_empty(self):
        """Defensive: an LLM that returns empty / whitespace must not
        nuke the user's text."""
        text = "Use  the API  now."
        original = "Use {{_OL_XTAG_1_}} the API {{_OL_XTAG_2_}} now."
        placeholders = ["{{_OL_XTAG_1_}}", "{{_OL_XTAG_2_}}"]

        pool = _StubPool(response="")
        restorer = Restorer(model_pool=pool)

        result = restorer.restore(text, original, placeholders)

        assert result == text

    def test_find_missing_helper(self):
        """Direct test of the static helper — used internally but also a
        public API the CLI may want to call."""
        text = "Foo {{_OL_XTAG_1_}} bar"
        missing = Restorer.find_missing(
            text, ["{{_OL_XTAG_1_}}", "{{_OL_XTAG_2_}}"],
        )
        assert missing == ["{{_OL_XTAG_2_}}"]

    def test_extract_placeholders_helper(self):
        """The CLI uses ``extract_placeholders`` to build the placeholder
        list from a shielded source. Verify it."""
        text = (
            "Read {{_OL_XTAG_x_1_}} the {{_OL_CODE_0042_}} doc "
            "{{_OL_MATH_0007_}} now."
        )
        found = extract_placeholders(text)
        assert found == [
            "{{_OL_XTAG_x_1_}}",
            "{{_OL_CODE_0042_}}",
            "{{_OL_MATH_0007_}}",
        ]


# ============================================================================
# test_restoration_disabled_via_flag
# ============================================================================


class TestRestorationDisabledViaFlag:
    """``--no-restoration`` must skip the restoration LLM call entirely.

    The CLI sets module state (``_pending_restoration_enabled``) before
    calling ``asyncio.run(_translate_*_async(...))``; the async
    function consumes the flag and skips the post-translate restoration
    step. We assert this by spying on ``Restorer.restore`` itself
    (patched at the import site used by ``ol_cli``)."""

    def test_translate_md_no_restoration_skips_call(
        self, sample_md, tmp_path, monkeypatch,
    ):
        """Pass ``--no-restoration`` to ``translate-md``; assert
        ``Restorer.restore`` is never called."""
        restore_calls: list[dict] = []

        async def fake_translate_md_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
            add_frontmatter=True,
        ):
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text("translated", encoding="utf-8")
            return str(output_file)

        # Spy on the Restorer.restore method. We patch the class
        # itself so the spy catches any instantiation the CLI makes.
        real_restore = Restorer.restore

        def spy_restore(self, text, original, placeholders):
            restore_calls.append(
                {"text": text, "original": original, "placeholders": placeholders},
            )
            return real_restore(self, text, original, placeholders)

        monkeypatch.setattr(Restorer, "restore", spy_restore)

        with patch.object(ol_cli, "_translate_md_async", side_effect=fake_translate_md_async):
            rc = runner.invoke(
                app,
                ["translate-md", str(sample_md), "-o", str(tmp_path / "out"),
                 "--no-cache", "--no-restoration"],
            )

        assert rc.exit_code == 0, (
            f"CLI failed: rc={rc.exit_code}, output={rc.output!r}, "
            f"exception={rc.exception!r}"
        )
        # The Restorer was never called — CLI bypassed it.
        assert restore_calls == [], (
            f"expected no Restorer.restore calls, got {restore_calls!r}"
        )

    def test_translate_xliff_no_restoration_skips_call(
        self, tmp_path, monkeypatch,
    ):
        """Same check for ``translate-xliff``."""
        restore_calls: list[dict] = []

        sample_xliff = tmp_path / "input.xlf"
        sample_xliff.write_text(
            '<?xml version="1.0"?>\n'
            '<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">\n'
            '  <file source-language="en" target-language="zh" original="test" datatype="plaintext">\n'
            '    <body>\n'
            '      <trans-unit id="tu1">\n'
            '        <source>Hello world</source>\n'
            '        <target></target>\n'
            '      </trans-unit>\n'
            '    </body>\n'
            '  </file>\n'
            '</xliff>\n',
            encoding="utf-8",
        )

        async def fake_translate_xliff_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
        ):
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text("translated", encoding="utf-8")
            return str(output_file)

        real_restore = Restorer.restore

        def spy_restore(self, text, original, placeholders):
            restore_calls.append(
                {"text": text, "original": original, "placeholders": placeholders},
            )
            return real_restore(self, text, original, placeholders)

        monkeypatch.setattr(Restorer, "restore", spy_restore)

        with patch.object(ol_cli, "_translate_xliff_async", side_effect=fake_translate_xliff_async):
            rc = runner.invoke(
                app,
                ["translate-xliff", str(sample_xliff), "-o", str(tmp_path / "out"),
                 "--no-cache", "--no-restoration"],
            )

        assert rc.exit_code == 0, (
            f"CLI failed: rc={rc.exit_code}, output={rc.output!r}, "
            f"exception={rc.exception!r}"
        )
        assert restore_calls == [], (
            f"expected no Restorer.restore calls for translate-xliff, "
            f"got {restore_calls!r}"
        )

    def test_translate_md_with_restoration_runs_call(
        self, sample_md, tmp_path, monkeypatch,
    ):
        """Sanity / regression: WITHOUT ``--no-restoration``, the Restorer
        is called (this is the production path). The mock LLM returns a
        response that includes all the placeholders, so the post-write
        file matches."""
        # Pre-populate the source MD with placeholders so the CLI has
        # something to extract.
        sample_md.write_text(
            "Read {{_OL_CODE_0001_}} the docs.\n", encoding="utf-8",
        )

        restore_calls: list[dict] = []

        async def fake_translate_md_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
            add_frontmatter=True,
        ):
            # Pre-populate the "translated" output without placeholders
            # so the post-translate restoration step has work to do.
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text(
                "translated-without-placeholders\n", encoding="utf-8",
            )
            return str(output_file)

        real_restore = Restorer.restore

        def spy_restore(self, text, original, placeholders):
            restore_calls.append(
                {"text": text, "original": original, "placeholders": placeholders},
            )
            return real_restore(self, text, original, placeholders)

        monkeypatch.setattr(Restorer, "restore", spy_restore)

        with patch.object(ol_cli, "_translate_md_async", side_effect=fake_translate_md_async):
            rc = runner.invoke(
                app,
                ["translate-md", str(sample_md), "-o", str(tmp_path / "out"),
                 "--no-cache"],
            )

        assert rc.exit_code == 0, (
            f"CLI failed: rc={rc.exit_code}, output={rc.output!r}, "
            f"exception={rc.exception!r}"
        )
        # With restoration enabled (default), the Restorer was called.
        assert len(restore_calls) == 1, (
            f"expected exactly 1 Restorer.restore call, "
            f"got {len(restore_calls)}: {restore_calls!r}"
        )
        # And the call had the expected arguments.
        call = restore_calls[0]
        assert "{{_OL_CODE_0001_}}" in call["placeholders"], (
            f"expected {{_OL_CODE_0001_}} in placeholders, got {call['placeholders']!r}"
        )
        assert "Read {{_OL_CODE_0001_}} the docs." in call["original"]
