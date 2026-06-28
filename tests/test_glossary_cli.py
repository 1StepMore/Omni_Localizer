"""A12.1 CLI tests: --glossary flag for translate-md and translate-xliff (PR12).

TDD: written FIRST (before the production code). The test asserts that
``--glossary PATH`` is accepted by the CLI, the file is loaded, and the
``Glossary`` instance is threaded into the translation pipeline.

The test mocks the underlying translate helpers (``_translate_md_async``
and ``_translate_xliff_async``) to avoid real LLM calls. It verifies the
glossary reaches the pipeline by observing the kwargs passed to the mock
or by patching ``Glossary.load`` directly.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

if sys.platform == "win32":
    import unittest.mock
    sys.modules.setdefault("fcntl", unittest.mock.MagicMock())


import ol_cli
from ol_cli import app

runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_GLOSSARY = FIXTURES_DIR / "sample_glossary.json"


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_md(tmp_path):
    f = tmp_path / "input.md"
    f.write_text("# Title\n\nHello world.\n", encoding="utf-8")
    return f


@pytest.fixture
def sample_xliff(tmp_path):
    f = tmp_path / "input.xlf"
    f.write_text(
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
    return f


# ============================================================================
# test_glossary_cli_flag_loads_file
# ============================================================================


class TestGlossaryCLIFlagLoadsFile:
    """The --glossary flag on translate-md must accept a path and load the file."""

    def test_translate_md_glossary_flag_loads_file(self, sample_md, tmp_path, monkeypatch):
        """Invoke ``ol translate-md --glossary /tmp/glossary.json``; assert the
        Glossary was loaded (the underlying load function was called with the
        right path) and the pipeline was invoked."""
        captured: dict = {}

        async def fake_translate_md_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
            add_frontmatter=True, glossary=None, restoration_enabled=True,
        ):
            # Wave 4 (L-C1): glossary is now passed as a direct function argument.
            captured["glossary"] = glossary
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text("translated", encoding="utf-8")
            return str(output_file)

        # Copy fixture to a tmp path so the test doesn't depend on cwd.
        glossary_tmp = tmp_path / "glossary.json"
        glossary_tmp.write_text(SAMPLE_GLOSSARY.read_text(encoding="utf-8"), encoding="utf-8")

        # Patch Glossary.load so the test doesn't read the file directly; we
        # want to assert the CLI invoked the loader with the right path.
        from ol_terminology import Glossary

        real_load = Glossary.load
        loaded_paths: list[Path] = []

        def spy_load(path):
            loaded_paths.append(Path(path))
            return real_load(path)

        monkeypatch.setattr(Glossary, "load", staticmethod(spy_load))

        with patch("cli.translate_md._translate_md_async", side_effect=fake_translate_md_async):
            rc = runner.invoke(
                app,
                ["translate-md", str(sample_md), "-o", str(tmp_path / "out"),
                 "--glossary", str(glossary_tmp),
                 "--no-cache"],
            )

        assert rc.exit_code == 0, (
            f"CLI failed: rc={rc.exit_code}, output={rc.output!r}, "
            f"exception={rc.exception!r}"
        )
        # The Glossary.load was invoked with the path we passed on the CLI.
        assert loaded_paths, "Glossary.load was not invoked"
        assert loaded_paths[0].resolve() == glossary_tmp.resolve(), (
            f"Glossary.load called with {loaded_paths[0]!r}, "
            f"expected {glossary_tmp!r}"
        )
        # And the loaded Glossary was threaded into the translate pipeline
        # (via module state, not a function parameter).
        assert captured.get("glossary") is not None, (
            f"glossary was not available to _translate_md_async; "
            f"captured keys: {list(captured.keys())}"
        )
        # It is the real Glossary instance (not a dict).
        from ol_terminology import Glossary as _Glossary
        assert isinstance(captured["glossary"], _Glossary), (
            f"expected Glossary instance, got {type(captured['glossary'])}"
        )

    def test_translate_xliff_glossary_flag_loads_file(self, sample_xliff, tmp_path, monkeypatch):
        """Same check for translate-xliff: the --glossary flag is honored and
        the Glossary is loaded."""
        captured: dict = {}

        async def fake_translate_xliff_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
            glossary=None,
        ):
            # Wave 4 (L-C1): glossary is now passed as a direct function argument.
            captured["glossary"] = glossary
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text("translated", encoding="utf-8")
            return str(output_file)

        glossary_tmp = tmp_path / "glossary.json"
        glossary_tmp.write_text(SAMPLE_GLOSSARY.read_text(encoding="utf-8"), encoding="utf-8")

        from ol_terminology import Glossary

        real_load = Glossary.load
        loaded_paths: list[Path] = []

        def spy_load(path):
            loaded_paths.append(Path(path))
            return real_load(path)

        monkeypatch.setattr(Glossary, "load", staticmethod(spy_load))

        with patch("cli.translate_xliff._translate_xliff_async", side_effect=fake_translate_xliff_async):
            rc = runner.invoke(
                app,
                ["translate-xliff", str(sample_xliff), "-o", str(tmp_path / "out"),
                 "--glossary", str(glossary_tmp),
                 "--no-cache"],
            )

        assert rc.exit_code == 0, (
            f"CLI failed: rc={rc.exit_code}, output={rc.output!r}, "
            f"exception={rc.exception!r}"
        )
        assert loaded_paths, "Glossary.load was not invoked for translate-xliff"
        assert loaded_paths[0].resolve() == glossary_tmp.resolve()
        assert captured.get("glossary") is not None, (
            f"glossary was not available to _translate_xliff_async; "
            f"captured keys: {list(captured.keys())}"
        )

    def test_translate_md_no_glossary_flag_works(self, sample_md, tmp_path):
        """Sanity: --glossary is OPTIONAL. translate-md without the flag still works."""
        called: dict = {"n": 0}

        async def fake_translate_md_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
            add_frontmatter=True, glossary=None, restoration_enabled=True,
        ):
            called["n"] += 1
            called["glossary"] = glossary
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text("translated", encoding="utf-8")
            return str(output_file)

        with patch("cli.translate_md._translate_md_async", side_effect=fake_translate_md_async):
            rc = runner.invoke(
                app,
                ["translate-md", str(sample_md), "-o", str(tmp_path / "out"),
                 "--no-cache"],
            )

        assert rc.exit_code == 0
        assert called["n"] == 1
        # No glossary provided → glossary is None.
        assert called.get("glossary") is None


# ============================================================================
# A12.5: --no-glossary, --glossary-max-terms
# ============================================================================


class TestGlossaryCLINewFlags:
    """A12.5 tests: ``--no-glossary`` and ``--glossary-max-terms`` flags."""

    def test_translate_md_no_glossary_overrides_glossary_flag(
        self, sample_md, tmp_path,
    ):
        """Pass both ``--glossary`` and ``--no-glossary``; the latter wins
        (glossary is None in the pipeline)."""
        called: dict = {}

        async def fake_translate_md_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
            add_frontmatter=True, glossary=None, restoration_enabled=True,
        ):
            called["glossary"] = glossary
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text("translated", encoding="utf-8")
            return str(output_file)

        glossary_tmp = tmp_path / "glossary.json"
        glossary_tmp.write_text(
            SAMPLE_GLOSSARY.read_text(encoding="utf-8"), encoding="utf-8",
        )

        with patch("cli.translate_md._translate_md_async", side_effect=fake_translate_md_async):
            rc = runner.invoke(
                app,
                ["translate-md", str(sample_md), "-o", str(tmp_path / "out"),
                 "--glossary", str(glossary_tmp),
                 "--no-glossary",
                 "--no-cache"],
            )

        assert rc.exit_code == 0, (
            f"CLI failed: rc={rc.exit_code}, output={rc.output!r}, "
            f"exception={rc.exception!r}"
        )
        # --no-glossary wins: pipeline sees no Glossary.
        assert called.get("glossary") is None, (
            f"expected None glossary with --no-glossary, got {called.get('glossary')!r}"
        )

    def test_translate_xliff_no_glossary_overrides_glossary_flag(
        self, sample_xliff, tmp_path,
    ):
        """Same check for ``translate-xliff``."""
        called: dict = {}

        async def fake_translate_xliff_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
            glossary=None,
        ):
            called["glossary"] = glossary
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text("translated", encoding="utf-8")
            return str(output_file)

        glossary_tmp = tmp_path / "glossary.json"
        glossary_tmp.write_text(
            SAMPLE_GLOSSARY.read_text(encoding="utf-8"), encoding="utf-8",
        )

        with patch("cli.translate_xliff._translate_xliff_async", side_effect=fake_translate_xliff_async):
            rc = runner.invoke(
                app,
                ["translate-xliff", str(sample_xliff), "-o", str(tmp_path / "out"),
                 "--glossary", str(glossary_tmp),
                 "--no-glossary",
                 "--no-cache"],
            )

        assert rc.exit_code == 0, (
            f"CLI failed: rc={rc.exit_code}, output={rc.output!r}, "
            f"exception={rc.exception!r}"
        )
        assert called.get("glossary") is None

    def test_translate_md_glossary_max_terms_binds_to_glossary(
        self, sample_md, tmp_path, monkeypatch,
    ):
        """``--glossary-max-terms 3`` binds the new default on the
        glossary's ``inject_into_prompt`` so the pool picks it up."""
        glossary_tmp = tmp_path / "glossary.json"
        glossary_tmp.write_text(
            SAMPLE_GLOSSARY.read_text(encoding="utf-8"), encoding="utf-8",
        )

        from ol_terminology import Glossary
        captured: dict = {}

        real_load = Glossary.load

        def spy_load(path):
            g = real_load(path)
            captured["glossary"] = g
            return g

        monkeypatch.setattr(Glossary, "load", staticmethod(spy_load))

        async def fake_translate_md_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
            add_frontmatter=True, glossary=None, restoration_enabled=True,
        ):
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text("translated", encoding="utf-8")
            return str(output_file)

        with patch("cli.translate_md._translate_md_async", side_effect=fake_translate_md_async):
            rc = runner.invoke(
                app,
                ["translate-md", str(sample_md), "-o", str(tmp_path / "out"),
                 "--glossary", str(glossary_tmp),
                 "--glossary-max-terms", "3",
                 "--no-cache"],
            )

        assert rc.exit_code == 0, (
            f"CLI failed: rc={rc.exit_code}, output={rc.output!r}, "
            f"exception={rc.exception!r}"
        )
        assert "glossary" in captured, "Glossary.load was not called"
        glossary = captured["glossary"]
        # The CLI's _apply_glossary_max_terms bound the override on
        # the glossary's inject_into_prompt method, so the call below
        # works without passing max_terms explicitly.
        result = glossary.inject_into_prompt(
            source_text="API rendering", prompt="Translate this.",
        )
        assert "Use these terms" in result, (
            f"expected 'Use these terms' in injected prompt, got: {result!r}"
        )
        # Explicit max_terms wins (forward compat).
        result2 = glossary.inject_into_prompt(
            source_text="API rendering", prompt="Translate this.",
            max_terms=1,
        )
        terms_section = result2.split("Use these terms:")[-1]
        terms = [t for t in terms_section.split(",") if t.strip()]
        assert len(terms) <= 1, (
            f"expected at most 1 term with explicit max_terms=1, "
            f"got: {terms!r}"
        )

    def test_translate_xliff_glossary_max_terms_no_error(
        self, sample_xliff, tmp_path,
    ):
        """``--glossary-max-terms N`` on translate-xliff must be accepted
        by the CLI (no usage error). Sanity test for the new flag."""
        called: dict = {}

        async def fake_translate_xliff_async(
            input_path, output_path, config_path, src_lang, tgt_lang,
            glossary=None,
        ):
            called["n"] = called.get("n", 0) + 1
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / input_path.name
            output_file.write_text("translated", encoding="utf-8")
            return str(output_file)

        with patch("cli.translate_xliff._translate_xliff_async", side_effect=fake_translate_xliff_async):
            rc = runner.invoke(
                app,
                ["translate-xliff", str(sample_xliff), "-o", str(tmp_path / "out"),
                 "--glossary-max-terms", "7",
                 "--no-cache"],
            )

        assert rc.exit_code == 0, (
            f"CLI failed: rc={rc.exit_code}, output={rc.output!r}, "
            f"exception={rc.exception!r}"
        )
        assert called.get("n") == 1
