"""Tests for OL#10: restore_tags must run BEFORE _escape_xml_entities.

When shield_map content contains HTML special chars (<, >, &), the order
of operations matters: restore first (substitute markers with original
content), then escape (convert special chars to XML entities). Reversing
the order produces invalid XLIFF with raw HTML in <target>.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ol_buses.xliff_bus import write_target_back
from ol_core.dataclass import ChannelType, TranslationContext, TranslationUnit

_MINIMAL_XLIFF = """\
<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="test.docx" source-language="en" target-language="zh">
    <body>
      <trans-unit id="u1">
        <source>Placeholder source</source>
        <target></target>
      </trans-unit>
    </body>
  </file>
</xliff>
"""

_TARGET_RE = re.compile(r'<target>(.*?)</target>', re.DOTALL)


def _raw_target_text(xliff_content: str) -> str:
    """Extract raw <target> inner XML (before entity decoding)."""
    m = _TARGET_RE.search(xliff_content)
    if m:
        return m.group(1)
    raise AssertionError("<target> not found in XLIFF")


def _build_ctx(
    target_text: str,
    shield_map: dict[str, str] | None = None,
    source_text: str = "Placeholder source",
) -> TranslationContext:
    return TranslationContext(
        file_path="/tmp/test.xliff",
        channel_type=ChannelType.XLIFF,
        original_full_text=_MINIMAL_XLIFF,
        units=[
            TranslationUnit(
                unit_id="u1",
                source_text=source_text,
                target_text=target_text,
                shield_map=shield_map or {},
                metadata={},
            ),
        ],
    )


class TestRestoreThenEscapeOrder:
    """OL#10: restore_tags must precede _escape_xml_entities."""

    def test_html_in_shield_map_produces_entities(self, tmp_path: Path) -> None:
        """HTML content from shield_map is escaped to &lt; &gt; in output."""
        ctx = _build_ctx(
            target_text="See {{_OL_XTAG_code_1_}} here",
            shield_map={"code_1": "<code>foo</code>"},
        )
        out = tmp_path / "out.xliff"
        write_target_back(ctx, str(out))
        raw = _raw_target_text(out.read_text())

        assert "&lt;code&gt;foo&lt;/code&gt;" in raw
        assert "<code>foo</code>" not in raw

    def test_no_shield_map_still_escapes(self, tmp_path: Path) -> None:
        """Without shield_map, _escape_xml_entities still runs on target."""
        ctx = _build_ctx(
            target_text="R&D <testing> done",
            shield_map={},
        )
        out = tmp_path / "out.xliff"
        write_target_back(ctx, str(out))
        raw = _raw_target_text(out.read_text())

        assert "R&amp;D" in raw
        assert "&lt;testing&gt;" in raw
        assert "<testing>" not in raw

    def test_chinese_with_html_chars_escaped(self, tmp_path: Path) -> None:
        """Chinese translation with shield_map content containing < is escaped."""
        ctx = _build_ctx(
            target_text="翻译 {{_OL_XTAG_x_1_}} 完成",
            shield_map={"x_1": "<em>重点</em>"},
        )
        out = tmp_path / "out.xliff"
        write_target_back(ctx, str(out))
        raw = _raw_target_text(out.read_text())

        assert "&lt;em&gt;重点&lt;/em&gt;" in raw
        assert "<em>重点</em>" not in raw

    def test_empty_target_falls_back_to_source(self, tmp_path: Path) -> None:
        """Empty target_text falls back to source text (ULTRAREADY-FIX)."""
        ctx = _build_ctx(target_text="", shield_map={})
        out = tmp_path / "out.xliff"
        write_target_back(ctx, str(out))
        raw = _raw_target_text(out.read_text())

        assert "Placeholder source" in raw

    def test_ampersand_in_shield_map_escaped(self, tmp_path: Path) -> None:
        """Shield map content with & is escaped to &amp; in output."""
        ctx = _build_ctx(
            target_text="See {{_OL_XTAG_ent_1_}}",
            shield_map={"ent_1": "AT&T"},
        )
        out = tmp_path / "out.xliff"
        write_target_back(ctx, str(out))
        raw = _raw_target_text(out.read_text())

        assert "AT&amp;T" in raw

    def test_mixed_xliff_tags_and_html_shield(self, tmp_path: Path) -> None:
        """XLIFF inline tag + HTML shield: both restored then escaped."""
        ctx = _build_ctx(
            target_text="{{_OL_XTAG_x_1_}} and {{_OL_XTAG_code_1_}}",
            shield_map={
                "x_1": '<x id="1"/>',
                "code_1": "<code>test</code>",
            },
        )
        out = tmp_path / "out.xliff"
        write_target_back(ctx, str(out))
        raw = _raw_target_text(out.read_text())

        assert '<x id="1"/>' in raw
        assert "&lt;code&gt;test&lt;/code&gt;" in raw
        assert "<code>test</code>" not in raw

    def test_output_is_valid_xml(self, tmp_path: Path) -> None:
        """The written XLIFF file must be parseable as valid XML."""
        ctx = _build_ctx(
            target_text="A & B < C > D {{_OL_XTAG_x_1_}}",
            shield_map={"x_1": '<x id="1" type="bold"/>'},
        )
        out = tmp_path / "out.xliff"
        write_target_back(ctx, str(out))

        ET.fromstring(out.read_text())

    def test_bug_regression_html_in_shield_map(self, tmp_path: Path) -> None:
        """Regression: the old buggy order would put raw HTML in <target>.

        Before the fix, _escape_xml_entities ran FIRST on placeholder text
        (no HTML in it), then restore_tags substituted shield markers with
        ORIGINAL (unescaped) content. This produced invalid XLIFF.
        """
        ctx = _build_ctx(
            target_text="{{_OL_XTAG_code_1_}}",
            shield_map={"code_1": "<b>bold</b> & <i>italic</i>"},
        )
        out = tmp_path / "out.xliff"
        write_target_back(ctx, str(out))
        raw = _raw_target_text(out.read_text())

        assert "&lt;b&gt;bold&lt;/b&gt; &amp; &lt;i&gt;italic&lt;/i&gt;" in raw
        assert "<b>bold</b>" not in raw
        assert " & " not in raw
