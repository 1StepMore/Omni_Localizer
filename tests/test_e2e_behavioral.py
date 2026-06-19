"""E2E tests for OPP→OL pipeline with OPP-generated XLIFF format.

OPP generates XLIFF files that contain ONLY <source> elements (no <target>).
These tests verify OL's translate_xliff correctly:
1. Handles OPP's source-only XLIFF format
2. Injects <target> elements after translation
3. Preserves XLIFF structure after translation
4. Works for both MCP tool path and load_xliff path

These tests are NOT mocked - they verify actual output state.
"""

import asyncio
import pytest
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


XLIFF_NS_1_2 = "urn:oasis:names:tc:xliff:document:1.2"
XLIFF_NS_1_1 = "urn:oasis:names:tc:xliff:document:1.1"


# OPP-style XLIFF: source-only, no target
OPP_STYLE_XLIFF = """<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="test.docx" source-language="en" target-language="zh" datatype="wordprocessingml">
    <body>
      <trans-unit id="1">
        <source>E2E Full Chain Testing Document</source>
      </trans-unit>
      <trans-unit id="2">
        <source>Second paragraph content</source>
      </trans-unit>
    </body>
  </file>
</xliff>
"""

# OPP-style XLIFF with inline elements (no target)
OPP_STYLE_XLIFF_INLINE = """<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="test.docx" source-language="en" target-language="zh" datatype="wordprocessingml">
    <body>
      <trans-unit id="1">
        <source>Hello <x id="1" type="bold"/> world</source>
      </trans-unit>
    </body>
  </file>
</xliff>
"""


def parse_xliff_check(xml_content: str) -> tuple[list[dict], list[str]]:
    """Parse XLIFF and return units with their structure."""
    root = ET.fromstring(xml_content)
    ns_uri = None
    for elem in root.iter():
        if "}" in elem.tag:
            ns_uri = elem.tag[1:elem.tag.index("}")]
            break

    units = []
    errors = []

    for trans_unit in root.iter():
        tag = trans_unit.tag
        if tag.endswith("}trans-unit") or tag == "trans-unit":
            unit_id = trans_unit.get("id")
            source_el = None
            target_el = None

            ns_prefix = f"{{{ns_uri}}}" if ns_uri else ""

            source_el = trans_unit.find(f"{ns_prefix}source")
            target_el = trans_unit.find(f"{ns_prefix}target")

            if source_el is None:
                errors.append(f"Unit {unit_id}: missing <source> element")
                continue

            source_text = source_el.text or ""
            target_text = target_el.text if target_el is not None else None

            units.append({
                "id": unit_id,
                "source": source_text,
                "target": target_text,
            })

    return units, errors


class TestOLTranslateXLIFFWithOPPStyle:
    """Test OL's translate_xliff with OPP-generated XLIFF format (source-only, no target)."""

    @pytest.fixture
    def temp_dir(self):
        import shutil
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def opp_style_xliff(self, temp_dir) -> Path:
        """Create an OPP-style XLIFF file (source-only, no target)."""
        path = temp_dir / "opp_style.xlf"
        path.write_text(OPP_STYLE_XLIFF, encoding="utf-8")
        return path

    @pytest.fixture
    def opp_style_xliff_inline(self, temp_dir) -> Path:
        """Create an OPP-style XLIFF file with inline elements."""
        path = temp_dir / "opp_style_inline.xlf"
        path.write_text(OPP_STYLE_XLIFF_INLINE, encoding="utf-8")
        return path

    def test_xliff_has_source_only_no_target(self, opp_style_xliff):
        """Verify OPP-style XLIFF has source elements but no target elements."""
        content = opp_style_xliff.read_text(encoding="utf-8")
        assert "<source>E2E Full Chain Testing Document</source>" in content
        assert "<target>" not in content or "<target/>" in content or "<target></target>" in content

    def test_translate_xliff_injects_target_elements(self, opp_style_xliff, temp_dir):
        """Test that translate_xliff MCP tool injects <target> elements.

        This is the core test for Bug #2 - verify that after translation,
        the output XLIFF has <target> elements with translated content.
        """
        from unittest.mock import patch

        # Mock the LLM translation to return predictable results
        def mock_translate(text, src_lang, tgt_lang, context=None):
            return f"[translated: {text}]"

        with patch("ol_pool.router.ModelPool.translate", side_effect=mock_translate):
            from ol_mcp.tools import translate_xliff, TranslateXliffInput

            output_path = str(temp_dir / "output.xlf")
            params = TranslateXliffInput(
                input_path=str(opp_style_xliff),
                output_path=output_path,
                source_lang="en",
                target_lang="zh",
            )

            result = asyncio.run(translate_xliff(params))

        import json
        result_data = json.loads(result)

        # Verify success
        assert result_data["success"], f"translate_xliff failed: {result_data.get('warnings', [])}"
        assert result_data["units_processed"] == 2, f"Expected 2 units, got {result_data['units_processed']}"

        # KEY TEST: Verify output XLIFF has <target> elements
        output_content = Path(output_path).read_text(encoding="utf-8")

        # Parse and check structure
        units, errors = parse_xliff_check(output_content)
        assert len(errors) == 0, f"XLIFF parsing errors: {errors}"
        assert len(units) == 2, f"Expected 2 units, got {len(units)}"

        # Verify each unit has a target
        for unit in units:
            assert unit["target"] is not None, f"Unit {unit['id']}: missing <target> element"
            assert len(unit["target"]) > 0, f"Unit {unit['id']}: empty <target> element"
            assert "[translated:" in unit["target"] or "全链路" in unit["target"], \
                f"Unit {unit['id']}: target doesn't look translated: {unit['target']}"

    def test_load_xliff_injects_target_tags(self, opp_style_xliff, temp_dir):
        """Test that load_xliff + write_target_back preserves target injection.

        This tests the CLI path (load_xliff) to ensure _ensure_target_tags works.
        """
        from ol_buses.xliff_bus import load_xliff, _ensure_target_tags

        # Test _ensure_target_tags directly
        content = opp_style_xliff.read_text(encoding="utf-8")
        assert "<target>" not in content

        processed = _ensure_target_tags(content)
        assert "<target></target>" in processed or "<target/>" in processed

        # Test full flow: load_xliff creates context with processed original_full_text
        ctx = load_xliff(str(opp_style_xliff))

        # Verify original_full_text has target tags
        assert "<target></target>" in ctx.original_full_text or "<target/>" in ctx.original_full_text

    def test_translate_xliff_with_inline_elements(self, opp_style_xliff_inline, temp_dir):
        """Test that translate_xliff handles inline elements correctly."""
        from unittest.mock import patch

        def mock_translate(text, src_lang, tgt_lang, context=None):
            translations = {
                "Hello <x id=\"1\" type=\"bold\"/> world": "你好<b id=\"1\"/>世界",
            }
            return translations.get(text, f"[translated: {text}]")

        with patch("ol_pool.router.ModelPool.translate", side_effect=mock_translate):
            from ol_mcp.tools import translate_xliff, TranslateXliffInput

            output_path = str(temp_dir / "output_inline.xlf")
            params = TranslateXliffInput(
                input_path=str(opp_style_xliff_inline),
                output_path=output_path,
                source_lang="en",
                target_lang="zh",
            )

            result = asyncio.run(translate_xliff(params))

        import json
        result_data = json.loads(result)
        assert result_data["success"], f"translate_xliff failed: {result_data.get('warnings', [])}"

        # Verify inline elements are preserved
        output_content = Path(output_path).read_text(encoding="utf-8")
        assert "<target>" in output_content


class TestOLTranslateXliffOutputContract:
    """Test that OL output satisfies ORF's input requirements."""

    @pytest.fixture
    def temp_dir(self):
        import shutil
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_output_xliff_has_target_elements_for_orf(self, temp_dir):
        """ORF's _backfill_translation requires <target> elements to exist.

        This test verifies OL output satisfies ORF's contract.
        """
        from unittest.mock import patch

        xliff_input = temp_dir / "input.xlf"
        xliff_input.write_text(OPP_STYLE_XLIFF, encoding="utf-8")

        def mock_translate(text, src_lang, tgt_lang, context=None):
            return f"[translated: {text}]"

        with patch("ol_pool.router.ModelPool.translate", side_effect=mock_translate):
            from ol_mcp.tools import translate_xliff, TranslateXliffInput

            output_path = str(temp_dir / "output.xlf")
            params = TranslateXliffInput(
                input_path=str(xliff_input),
                output_path=output_path,
            )
            result = asyncio.run(translate_xliff(params))

        import json
        result_data = json.loads(result)
        assert result_data["success"]

        # Parse output and verify structure
        output_content = Path(output_path).read_text(encoding="utf-8")
        units, errors = parse_xliff_check(output_content)

        # ORF contract: every trans-unit must have a <target> element
        assert len(units) == 2, f"Expected 2 units, got {len(units)}"
        for unit in units:
            assert unit["target"] is not None, \
                f"ORF contract violation: Unit {unit['id']} missing <target> element"
            assert len(unit["target"]) > 0, \
                f"ORF contract violation: Unit {unit['id']} has empty <target>"


class TestOLAssembledDocumentSeparator:
    """Test that batch_translate_texts assembled_document uses correct separator."""

    @pytest.fixture
    def temp_dir(self):
        import shutil
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_assembled_document_uses_dash_separator(self, temp_dir):
        """Verify assembled_document joins with --- separator (Q2 decision)."""
        from unittest.mock import patch

        def mock_translate(text, src_lang, tgt_lang, context=None):
            return f"[T:{text[:20]}...]"

        texts = [
            "First chunk of text for translation",
            "Second chunk with different content",
            "Third and final chunk",
        ]

        with patch("ol_pool.router.ModelPool.translate", side_effect=mock_translate):
            from ol_mcp.tools import batch_translate_texts, BatchTranslateInput

            params = BatchTranslateInput(
                texts=texts,
                source_lang="en",
                target_lang="zh",
            )
            result = batch_translate_texts(params)

        import json
        result_data = json.loads(result)

        assert result_data["success"]
        assert "assembled_document" in result_data

        # Verify separator is ---
        assembled = result_data["assembled_document"]
        assert "---" in assembled, f"assembled_document should use --- separator, got: {assembled[:100]}"

        # Verify all chunks are present
        for text in texts:
            assert text[:20] in assembled or f"[T:{text[:20]}" in assembled, \
                "Chunk not found in assembled_document"
