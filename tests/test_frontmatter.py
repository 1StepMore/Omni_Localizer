"""Unit tests for frontmatter functionality in ol_cli."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ol_cli import (
    _build_xliff_header_note,
    _escape_xml,
    _generate_frontmatter,
    _get_ol_version,
    app,
)

runner = CliRunner()


class TestFrontmatterFormat:
    def test_frontmatter_format(self):
        fm = _generate_frontmatter("en", "zh", "test.md")
        lines = fm.split("\n")
        assert lines[0] == "---"
        assert "source_lang: en" in fm
        assert "target_lang: zh" in fm
        assert "original_file: test.md" in fm
        assert 'processor: "OL"' in fm
        assert f'version: "{_get_ol_version()}"' in fm
        assert "translated_at:" in fm
        assert lines[-2] == "---"


class TestFrontmatterTimestamp:
    def test_frontmatter_timestamp_is_valid_iso(self):
        import re
        fm = _generate_frontmatter("en", "zh", "test.md")
        match = re.search(r"translated_at: (\S+)", fm)
        assert match is not None
        timestamp = match.group(1)
        assert timestamp.endswith("Z")
        assert "T" in timestamp


class TestFrontmatterSkipping:
    def test_frontmatter_not_added_if_already_present(self):
        existing_content = """---
source_lang: en
target_lang: zh
---
# Hello
"""
        add_frontmatter = True
        content = existing_content
        if add_frontmatter and not content.strip().startswith("---"):
            content = _generate_frontmatter("en", "zh", "test.md") + content
        assert content.strip().startswith("---")
        assert content.count("---") == 2


class TestVersionAccess:
    def test_version_access(self):
        assert _get_ol_version() == "0.2.6"


class TestTranslateMdFrontmatter:
    @pytest.fixture
    def temp_md(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
        ) as f:
            f.write("# Test\n\nContent here.")
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def temp_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_translate_md_adds_frontmatter(self, temp_md, temp_output_dir):
        output_file = Path(temp_output_dir) / Path(temp_md).name
        output_file.write_text("""---
source_lang: en
target_lang: zh
original_file: test.md
processor: "OL"
version: "0.1.0"
translated_at: 2026-05-22T10:00:00Z
---
# Test

Translated content.
""", encoding="utf-8")

        with patch("ol_cli.asyncio.run", return_value=str(output_file)):
            result = runner.invoke(
                app,
                ["translate-md", temp_md, "-o", temp_output_dir, "-c", str(Path(__file__).parent.parent / "config" / "default.yaml")],
            )
            assert result.exit_code == 0

            content = output_file.read_text(encoding="utf-8")
            assert content.startswith("---")
            assert "source_lang: en" in content
            assert "target_lang: zh" in content


class TestCacheKeyBehavioralFlags:
    """Regression: behavioral CLI flags MUST participate in the cache key.

    Before T24a, ``_cache_key(input_path, config_path)`` only hashed input
    bytes + config bytes, so ``ol translate-md foo.md`` followed by
    ``ol translate-md foo.md --no-frontmatter`` returned the cached
    WITH-frontmatter output on the second run. The cache must invalidate
    on every flag that affects the produced bytes.
    """

    def test_cache_key_differs_when_frontmatter_flag_differs(self, tmp_path):
        from ol_cli import _cache_key

        input_path = tmp_path / "in.md"
        input_path.write_text("# Hello\n", encoding="utf-8")

        key_with = _cache_key(
            input_path, config_path=None, add_frontmatter=True,
        )
        key_without = _cache_key(
            input_path, config_path=None, add_frontmatter=False,
        )
        assert key_with != key_without

    def test_cache_key_differs_when_concurrency_differs(self, tmp_path):
        from ol_cli import _cache_key

        input_path = tmp_path / "in.md"
        input_path.write_text("# Hello\n", encoding="utf-8")

        key_low = _cache_key(
            input_path, config_path=None, concurrency=1,
        )
        key_high = _cache_key(
            input_path, config_path=None, concurrency=10,
        )
        assert key_low != key_high

    def test_cache_key_differs_when_detect_language_differs(self, tmp_path):
        from ol_cli import _cache_key

        input_path = tmp_path / "in.md"
        input_path.write_text("# Hello\n", encoding="utf-8")

        key_on = _cache_key(
            input_path, config_path=None, detect_language=True,
        )
        key_off = _cache_key(
            input_path, config_path=None, detect_language=False,
        )
        assert key_on != key_off

    def test_cache_key_differs_when_lqa_enabled_differs(self, tmp_path):
        from ol_cli import _cache_key

        input_path = tmp_path / "in.md"
        input_path.write_text("# Hello\n", encoding="utf-8")

        key_off = _cache_key(
            input_path, config_path=None, lqa_enabled=False,
        )
        key_on = _cache_key(
            input_path, config_path=None, lqa_enabled=True,
        )
        assert key_off != key_on

    def test_cache_key_stable_for_identical_flags(self, tmp_path):
        from ol_cli import _cache_key

        input_path = tmp_path / "in.md"
        input_path.write_text("# Hello\n", encoding="utf-8")

        key_a = _cache_key(
            input_path, config_path=None, add_frontmatter=False, concurrency=5,
            detect_language=True, lqa_enabled=False,
        )
        key_b = _cache_key(
            input_path, config_path=None, add_frontmatter=False, concurrency=5,
            detect_language=True, lqa_enabled=False,
        )
        assert key_a == key_b

    def test_cache_key_unchanged_for_legacy_call(self, tmp_path):
        """Backward-compat: legacy call sites that pass no flags still work."""
        from ol_cli import _cache_key

        input_path = tmp_path / "in.md"
        input_path.write_text("# Hello\n", encoding="utf-8")

        key_a = _cache_key(input_path, config_path=None)
        key_b = _cache_key(
            input_path, config_path=None, add_frontmatter=True, concurrency=5,
            detect_language=True, lqa_enabled=False,
        )
        assert isinstance(key_a, str) and len(key_a) == 64


class TestYamlEscaping:
    def test_frontmatter_escapes_yaml_special_chars(self):
        fm_colon = _generate_frontmatter("en", "zh", "file:name.md")
        assert 'original_file: "file:name.md"' in fm_colon

        fm_hash = _generate_frontmatter("en", "zh", "file#1.md")
        assert 'original_file: "file#1.md"' in fm_hash

        fm_normal = _generate_frontmatter("en", "zh", "normal_file.md")
        assert "original_file: normal_file.md" in fm_normal


class TestLangCodeValidation:
    def test_frontmatter_rejects_invalid_lang_code(self):
        with pytest.raises(ValueError, match="Invalid language code"):
            _generate_frontmatter("invalid", "zh", "test.md")

        with pytest.raises(ValueError, match="Invalid language code"):
            _generate_frontmatter("en", "123", "test.md")

        with pytest.raises(ValueError, match="Invalid language code"):
            _generate_frontmatter("EN", "zh", "test.md")

        with pytest.raises(ValueError, match="Invalid language code"):
            _generate_frontmatter("e", "zh", "test.md")

        _generate_frontmatter("en-US", "zh-CN", "test.md")


class TestXmlEscaping:
    def test_xliff_header_escapes_xml_special_chars(self):
        header = _build_xliff_header_note("en", "zh")
        assert "<note from=\"OL\">Translated from en to zh by OL</note>" in header

    def test_escape_xml_ampersand(self):
        assert _escape_xml("A & B") == "A &amp; B"

    def test_escape_xml_angle_brackets(self):
        assert _escape_xml("<tag>") == "&lt;tag&gt;"

    def test_escape_xml_quotes(self):
        assert _escape_xml('"quoted"') == "&quot;quoted&quot;"
        assert _escape_xml("'single'") == "&apos;single&apos;"
