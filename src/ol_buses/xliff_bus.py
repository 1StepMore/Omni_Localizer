"""XLIFF bus for Omni-Localizer using translate-toolkit."""
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ol_buses.xliff_shield import replace_tags_with_placeholders
from ol_core.dataclass import ChannelType, TranslationContext, TranslationUnit

_logger = logging.getLogger(__name__)


# Matches a bare `&` that is NOT already the start of a known XML entity.
# Negative lookahead skips `&amp;`, `&lt;`, `&gt;`, `&quot;`, `&apos;`,
# numeric character refs `&#NNN;` and hex refs `&#xHH;` so we never
# double-escape inputs that are already entity-encoded.
_BARE_AMP_RE = re.compile(
    r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)'
)

# Matches XLIFF structural inline elements (<x/>, <bx/>, <ex/>) that must
# remain as actual XML in <target>, NOT be entity-escaped.  Used by the
# tag-aware escape helper so that restore_tags output is handled correctly.
_XLIFF_INLINE_TAG_RE = re.compile(r'<(?:x|bx|ex)\s[^>]*/>')


def _escape_xml_entities(text: str) -> str:
    """Escape XML special characters in LLM-produced text.

    The XLIFF writer concatenates LLM target text into ``<target>`` element
    content via f-strings, so unescaped ``&``, ``<`` or ``>`` would produce
    invalid XLIFF and trip ``lxml.etree.XMLSyntaxError: xmlParseEntityRef:
    no name`` on the next parse.

    The escape is idempotent on already-escaped input: ``&amp;`` stays
    ``&amp;`` rather than becoming ``&amp;amp;``.

    Order matters: ``&`` is escaped first (so we don't accidentally rewrite
    ``&lt;`` produced by the subsequent step), then ``<``/``>``.
    """
    if not text:
        return text
    text = _BARE_AMP_RE.sub('&amp;', text)
    text = text.replace('<', '&lt;').replace('>', '&gt;')
    return text


def _escape_xml_entities_preserving_xliff_tags(text: str) -> str:
    """Escape XML entities but leave XLIFF inline tags (<x/>, <bx/>, <ex/>) as-is.

    After ``restore_tags()`` puts structural XLIFF elements back into the
    text, we must entity-escape user-visible content (``<code>``, ``&``)
    while preserving the structural tags as valid XML.
    """
    if not text:
        return text
    parts: list[str] = []
    last_end = 0
    for m in _XLIFF_INLINE_TAG_RE.finditer(text):
        parts.append(_escape_xml_entities(text[last_end:m.start()]))
        parts.append(m.group(0))
        last_end = m.end()
    parts.append(_escape_xml_entities(text[last_end:]))
    return ''.join(parts)


def _ensure_target_tags(content: str) -> str:
    """Normalize XLIFF so every trans-unit has <target></target>.

    OPP-generated XLIFF files contain <source> elements without <target>.
    Subsequent runs may produce <target/> (self-closing) or <target></target>
    (already normalized).  write_target_back() requires the open-close form
    <target>...</target> for regex replacement, so this function handles all
    three cases:

    1. Self-closing <target/>  →  <target></target>
    2. No <target> at all      →  inject <target></target>
    3. Already <target>...</target>  →  leave unchanged

    Args:
        content: XLIFF file content as string

    Returns:
        Content where every trans-unit has <target></target>
    """
    import re

    # Step 1: convert self-closing <target/> to <target></target>
    # write_target_back's regex requires a closing </target> tag.
    content = re.sub(r'<target\s*/>', '<target></target>', content)

    # Step 2: inject <target></target> for trans-units that still lack one
    # Uses negative lookahead (?!\s*<target) to ensure no target comes after source
    source_only_pattern = re.compile(
        r'(<trans-unit[^>]*id="([^"]+)"[^>]*>.*?</source>)(?!\s*<target)',
        re.DOTALL,
    )

    def insert_target(m: re.Match) -> str:
        return m.group(1) + '<target></target>'

    return source_only_pattern.sub(insert_target, content)


def validate_xliff_structure(path: str) -> bool:
    """Validate XLIFF file has required structure."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding='utf-8')
        return '<xliff' in content and '<file' in content
    except (OSError, UnicodeDecodeError):
        _logger.exception("Failed to read XLIFF file for validation: %s", path)
        return False


def load_xliff(path: str, glossary: dict[str, Any] | None = None) -> TranslationContext:
    """Load XLIFF file and create TranslationContext.

    Args:
        path: Path to XLIFF file (.xliff or .xlf)
        glossary: Optional glossary dict for terminology

    Returns:
        TranslationContext with channel_type=XLIFF and units populated

    """
    path = Path(path)
    original_text = path.read_text(encoding='utf-8')

    # Pre-inject target tags for OPP-generated XLIFF (which lacks <target> elements)
    original_text = _ensure_target_tags(original_text)

    # Extract translation units from XLIFF
    units = list(iterate_trans_units(path))

    return TranslationContext(
        file_path=str(path),
        channel_type=ChannelType.XLIFF,
        original_full_text=original_text,
        units=units,
        glossary=glossary or {},
        config={},
    )


def iterate_trans_units(path: Path) -> Iterator[TranslationUnit]:
    """Iterate over trans-unit elements in XLIFF file.

    Extracts source text, creates TranslationUnit with placeholder replacement.
    """
    import re

    content = path.read_text(encoding='utf-8')

    # Simple regex-based extraction for trans-unit elements
    # Pattern: <trans-unit id="..."><source>...</source>...</trans-unit>
    trans_unit_pattern = re.compile(
        r'<trans-unit[^>]*id="([^"]+)"[^>]*>(.*?)</trans-unit>',
        re.DOTALL,
    )

    source_pattern = re.compile(r'<source[^>]*>(.*?)</source>', re.DOTALL)

    for match in trans_unit_pattern.finditer(content):
        unit_id = match.group(1)
        trans_unit_content = match.group(2)

        source_match = source_pattern.search(trans_unit_content)
        if source_match:
            source_text = source_match.group(1).strip()

            # Replace XML tags with placeholders
            text_with_placeholders, shield_map = replace_tags_with_placeholders(source_text)

            yield TranslationUnit(
                unit_id=unit_id,
                source_text=text_with_placeholders,
                shield_map=shield_map,
                metadata={},
            )


def write_target_back(
    ctx: TranslationContext,
    output_path: str,
    warnings_per_unit: dict[str, list[str]] | None = None,
) -> None:
    """Write translated content back to XLIFF format.

    Args:
        ctx: TranslationContext with translated units
        output_path: Output file path
        warnings_per_unit: Optional dict mapping unit_id to a list of warning
            strings. Each warning is injected as a ``<note from="OL">...</note>``
            sibling of the unit's ``<target>`` (i.e., as a direct child of
            ``<trans-unit>``, not nested inside ``<target>``). When omitted,
            falls back to ``ctx.warnings_per_unit`` if present.

    """
    if warnings_per_unit is None:
        warnings_per_unit = ctx.warnings_per_unit
    warnings_per_unit = warnings_per_unit or {}

    content = ctx.original_full_text

    from ol_xliff.parser import HEADER_NOTE_UNIT_ID, FILE_ORIGINAL_UNIT_ID

    for unit in ctx.units:
        if unit.target_text is None:
            continue

        # ULTRAREADY-FIX (2026-06-08): fallback for empty LLM output.
        # The LLM sometimes produces just whitespace for units whose
        # source is text wrapped in inline tags (e.g. para_index_0 =
        # title "《爱上海尔》" between <bx> and <ex>). If target_text
        # is empty/whitespace, fall back to the source's text content
        # (with placeholders) so the inline tags + Chinese text still
        # appear in the output. The user at least sees the title text
        # (in Chinese) rather than a blank paragraph.
        if not unit.target_text.strip() and unit.source_text.strip():
            _logger.warning(
                f"Empty LLM target for unit {unit.unit_id}; "
                f"falling back to source text. Source={unit.source_text[:80]!r}"
            )
            unit.target_text = unit.source_text

        if unit.unit_id == HEADER_NOTE_UNIT_ID:
            header_note_pattern = re.compile(
                r'(<header\b[^>]*>.*?<note\b[^>]*>)(.*?)(</note>.*?</header>)',
                re.DOTALL,
            )
            content = header_note_pattern.sub(
                lambda m: m.group(1) + _escape_xml_entities(unit.target_text) + m.group(3),
                content,
            )
            continue

        if unit.unit_id == FILE_ORIGINAL_UNIT_ID:
            file_pattern = re.compile(
                r'(<file\b[^>]*\boriginal\s*=\s*")[^"]*(")',
            )
            content = file_pattern.sub(
                lambda m: m.group(1) + _escape_xml_entities(unit.target_text) + m.group(2),
                content,
            )
            continue

        target_pattern = re.compile(
            rf'(<trans-unit[^>]*id="{re.escape(unit.unit_id)}"[^>]*>.*?)<target[^>]*>.*?</target>(.*?</trans-unit>)',
            re.DOTALL,
        )

        from ol_buses.xliff_shield import restore_tags
        restored_target = (
            restore_tags(unit.target_text, unit.shield_map)
            if unit.shield_map
            else unit.target_text
        )
        escaped_target = _escape_xml_entities_preserving_xliff_tags(restored_target)

        unit_warnings = warnings_per_unit.get(unit.unit_id, [])
        notes_xml = ''.join(
            f'<note from="OL">{_escape_xml_entities(w)}</note>'
            for w in unit_warnings
        )

        content = target_pattern.sub(
            lambda m: m.group(1) + f'<target>{escaped_target}</target>' + notes_xml + m.group(2),
            content,
        )

    Path(output_path).write_text(content, encoding='utf-8')
