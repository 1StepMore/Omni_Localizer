"""Regression tests for ol_cli.py split.

Verifies that the CLI entry point, all subcommands, and backward-compatible
imports work after the module was split into cli/ subpackage.
"""
from __future__ import annotations

from typer.testing import CliRunner

runner = CliRunner()


class TestCLIEntryPoint:
    """Verify ol --help and basic CLI structure."""

    def test_help_output(self):
        """ol --help produces expected output with all subcommands."""
        from ol_cli import app
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Omni-Localizer" in result.stdout
        assert "translate-md" in result.stdout
        assert "translate-xliff" in result.stdout
        assert "translate-batch" in result.stdout
        assert "extract-warnings" in result.stdout

    def test_version_flag(self):
        """ol --version shows version string."""
        from ol_cli import app
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "ol version" in result.stdout

    def test_translate_md_help(self):
        """ol translate-md --help works."""
        from ol_cli import app
        result = runner.invoke(app, ["translate-md", "--help"])
        assert result.exit_code == 0
        assert "translate-md" in result.stdout or "translate" in result.stdout

    def test_translate_xliff_help(self):
        """ol translate-xliff --help works."""
        from ol_cli import app
        result = runner.invoke(app, ["translate-xliff", "--help"])
        assert result.exit_code == 0
        assert "translate-xliff" in result.stdout or "translate" in result.stdout

    def test_translate_batch_help(self):
        """ol translate-batch --help works."""
        from ol_cli import app
        result = runner.invoke(app, ["translate-batch", "--help"])
        assert result.exit_code == 0
        assert "translate-batch" in result.stdout or "translate" in result.stdout

    def test_extract_warnings_help(self):
        """ol extract-warnings --help works."""
        from ol_cli import app
        result = runner.invoke(app, ["extract-warnings", "--help"])
        assert result.exit_code == 0
        assert "extract-warnings" in result.stdout or "extract" in result.stdout


class TestBackwardCompatImports:
    """Verify all backward-compatible imports from ol_cli still work."""

    def test_import_app(self):
        from ol_cli import app
        assert app is not None

    def test_import_version(self):
        from ol_cli import __version__
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_import_exit_code(self):
        from ol_cli import ExitCode
        assert ExitCode.SUCCESS == 0

    def test_import_frontmatter_helpers(self):
        """Frontmatter helpers importable from ol_cli."""
        from ol_cli import (
            _generate_frontmatter,
            _generate_skip_frontmatter,
            _get_ol_version,
            _validate_lang_code,
            _escape_yaml_value,
            _escape_xml,
            _build_xliff_header_note,
            _inject_xliff_header,
            _extract_opp_metadata,
            _extract_request_id,
        )
        assert callable(_generate_frontmatter)
        assert callable(_get_ol_version)
        assert callable(_validate_lang_code)

    def test_import_cache_helpers(self):
        """Cache helpers importable from ol_cli."""
        from ol_cli import (
            _cache_key,
            _check_cache,
            _write_cache,
            _clear_ol_cache,
            _cache_root,
            CACHE_DIR_NAME,
        )
        assert callable(_cache_key)
        assert callable(_clear_ol_cache)
        assert isinstance(CACHE_DIR_NAME, str)

    def test_import_translate_md_helpers(self):
        """MD translation helpers importable from ol_cli."""
        from ol_cli import (
            _translate_md_async,
            _translate_md_by_paragraph,
            _translate_md_units_concurrent,
            _translate_units_concurrent,
            _translate_one_unit,
            _UnitTranslationResult,
            _set_glossary_for_next_translation,
            _consume_glossary_for_translation,
            _set_restoration_for_next_translation,
            _consume_restoration_for_translation,
            _set_glossary_max_terms_for_next_translation,
            _consume_glossary_max_terms_for_translation,
            _apply_glossary_max_terms,
            _apply_post_translate_restoration,
            _build_restoration_pool,
            _load_glossary_or_none,
            _load_env_for_cli,
            _load_dotenv,
        )
        assert callable(_translate_md_async)
        assert callable(_consume_glossary_for_translation)

    def test_import_translate_xliff_helpers(self):
        """XLIFF translation helpers importable from ol_cli."""
        from ol_cli import (
            _translate_xliff_async,
            _translate_xliff_pipelined,
        )
        assert callable(_translate_xliff_async)
        assert callable(_translate_xliff_pipelined)

    def test_import_batch_helpers(self):
        """Batch translation helpers importable from ol_cli."""
        from ol_cli import (
            _translate_batch_async,
        )
        assert callable(_translate_batch_async)

    def test_import_cli_infrastructure(self):
        """CLI infrastructure importable from ol_cli."""
        from ol_cli import (
            validate_input_file,
            ensure_output_dir,
            output_json,
            _apply_fake_llm_seam,
            is_interrupted,
            _setup_signal_handler,
            main_entry,
        )
        assert callable(validate_input_file)
        assert callable(ensure_output_dir)
        assert callable(output_json)
        assert callable(main_entry)


class TestCLISubmoduleDirectImports:
    """Verify direct imports from cli/ submodules work."""

    def test_import_from_cli_cache(self):
        from cli.cache import _cache_key, _check_cache, _clear_ol_cache
        assert callable(_cache_key)

    def test_import_from_cli_frontmatter(self):
        from cli.frontmatter import _generate_frontmatter, _validate_lang_code
        assert callable(_generate_frontmatter)

    def test_import_from_cli_translate_md(self):
        from cli.translate_md import translate_md, _translate_md_async
        assert callable(translate_md)
        assert callable(_translate_md_async)

    def test_import_from_cli_translate_xliff(self):
        from cli.translate_xliff import translate_xliff
        assert callable(translate_xliff)

    def test_import_from_cli_batch(self):
        from cli.batch import translate_batch, extract_warnings
        assert callable(translate_batch)
        assert callable(extract_warnings)
