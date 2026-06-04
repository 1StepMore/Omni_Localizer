"""XLIFF parser for Omni-Localizer using translate-toolkit + regex fallback."""
import re
from pathlib import Path

from ol_core.dataclass import TranslationUnit

HEADER_NOTE_UNIT_ID = '__xliff_header_note__'
FILE_ORIGINAL_UNIT_ID = '__xliff_file_original__'

# Regex patterns for inline element extraction
# XLIFF 1.x inline elements: x, bx, ex, ph, alayout
INLINE_PATTERNS = [
    # Standalone: <x id="1" type="bold"/>
    (r'<x[^>]*id="([^"]+)"[^>]*/>', 'x'),
    # Begin: <bx id="1" type="bold"/>
    (r'<bx[^>]*id="([^"]+)"[^>]*/>', 'bx'),
    # End: <ex id="1" type="bold"/>
    (r'<ex[^>]*id="([^"]+)"[^>]*/>', 'ex'),
    # Placeholder: <ph id="1" type="bold">...</ph>
    (r'<ph[^>]*id="([^"]+)"[^>]*>.*?</ph>', 'ph'),
    # Annotation layout: <alayout id="1" type="bold"/>
    (r'<alayout[^>]*id="([^"]+)"[^>]*/>', 'alayout'),
    # Mark: <mrk id="1" type="bold">...</mrk>
    (r'<mrk[^>]*id="([^"]+)"[^>]*>.*?</mrk>', 'mrk'),
    # End mark: </mrk> - handled separately
]

# XLIFF 1.x namespace pattern
XLIFF_1_NS = 'xmlns="urn:oasis:names:tc:xliff:document:1.1'
XLIFF_2_NS = 'xmlns="urn:oasis:names:tc:xliff:document:2.0'


def extract_inline_elements(text: str) -> tuple[str, dict[str, str]]:
    """Extract inline elements from XLIFF text using regex.

    Args:
        text: Raw XLIFF text with inline elements

    Returns:
        Tuple of (text_with_placeholders, shield_map)

    """
    shield_map: dict[str, str] = {}
    result = text

    # Process all inline element patterns
    for pattern, tag_type in INLINE_PATTERNS:
        regex = re.compile(pattern, re.DOTALL)
        matches = list(regex.finditer(result))

        # Process in reverse to maintain positions
        for match in reversed(matches):
            tag_id = match.group(1)
            placeholder_key = f'{tag_type}_{tag_id}'
            placeholder = f'{{{{_OL_XTAG_{placeholder_key}_}}}}'

            # Only add to shield_map if not already present
            if placeholder_key not in shield_map:
                shield_map[placeholder_key] = match.group(0)

            result = result[:match.start()] + placeholder + result[match.end():]

    # Handle standalone </mrk> end tags (mrk uses paired tags)
    mrk_end_pattern = re.compile(r'</mrk>')
    matches = list(mrk_end_pattern.finditer(result))
    for match in reversed(matches):
        placeholder = '{{_OL_XTAG_mrk_end_}}'
        shield_map['mrk_end'] = '</mrk>'
        result = result[:match.start()] + placeholder + result[match.end():]

    return result, shield_map


def detect_xliff_version(content: str) -> str:
    """Detect XLIFF version from content.

    Args:
        content: XLIFF file content

    Returns:
        '1.x', '2.0', or 'unknown'

    """
    if XLIFF_2_NS in content:
        return '2.0'
    elif XLIFF_1_NS in content or '<xliff' in content:
        return '1.x'
    return 'unknown'


def _extract_metadata_units(content: str) -> list[TranslationUnit]:
    """Extract <header><note> and <file original="..."> as synthetic translation units.

    These metadata elements are skipped by the main trans-unit loop but are
    legitimate translatable content in many XLIFF 1.x workflows. They get
    sentinel unit_ids (HEADER_NOTE_UNIT_ID, FILE_ORIGINAL_UNIT_ID) so the
    writer can update the original elements in place.
    """
    metadata: list[TranslationUnit] = []

    header_note_pattern = re.compile(
        r'<header\b[^>]*>.*?<note\b[^>]*>(.*?)</note>.*?</header>',
        re.DOTALL,
    )
    note_match = header_note_pattern.search(content)
    if note_match:
        note_text = _unescape_xliff_text(note_match.group(1).strip())
        if note_text:
            metadata.append(TranslationUnit(
                unit_id=HEADER_NOTE_UNIT_ID,
                source_text=note_text,
                shield_map={},
                metadata={'source': 'header-note'},
            ))

    file_tag_pattern = re.compile(
        r'<file\b[^>]*\boriginal\s*=\s*"([^"]+)"',
    )
    file_match = file_tag_pattern.search(content)
    if file_match:
        original_name = file_match.group(1).strip()
        if original_name:
            metadata.append(TranslationUnit(
                unit_id=FILE_ORIGINAL_UNIT_ID,
                source_text=original_name,
                shield_map={},
                metadata={'source': 'file-original'},
            ))

    return metadata


def _unescape_xliff_text(text: str) -> str:
    return (
        text.replace('&amp;', '&')
        .replace('&lt;', '<')
        .replace('&gt;', '>')
        .replace('&quot;', '"')
        .replace('&apos;', "'")
    )


def parse_xliff_1x(content: str) -> list[TranslationUnit]:
    """Parse XLIFF 1.x format using regex fallback.

    Args:
        content: XLIFF 1.x file content

    Returns:
        List of TranslationUnit objects

    """
    units: list[TranslationUnit] = []

    # Try translate-toolkit first if available
    xliff_1_parser = None
    try:
        from translate.storage.xliff import xlifffile
        xliff_1_parser = xlifffile()
        xliff_1_parser.parse(content.encode('utf-8'))
        use_toolkit = True
    except Exception:
        use_toolkit = False

    if use_toolkit:
        # Use translate-toolkit for structural parsing
        ns = xliff_1_parser.body.tag.split('}')[0] + '}' if '}' in xliff_1_parser.body.tag else ''
        for node in xliff_1_parser.body.iter():
            local_tag = node.tag.split('}')[-1] if '}' in node.tag else node.tag
            if local_tag == 'trans-unit':
                unit_id = node.get('id', '')
                source_elem = node.find(f'{ns}source') if ns else node.find('source')
                if source_elem is None:
                    source_elem = node.find('source')

                if source_elem is not None:
                    # Get full text including inline elements as XML string
                    source_parts = []
                    if source_elem.text:
                        source_parts.append(source_elem.text)
                    for child in source_elem:
                        source_parts.append(f'<{child.tag.split("}")[-1]}')
                        for k, v in child.attrib.items():
                            source_parts.append(f' {k}="{v}"')
                        source_parts.append('/>')
                        if child.tail:
                            source_parts.append(child.tail)
                    source_text = ''.join(source_parts)

                    if source_text.strip():
                        text_with_placeholders, shield_map = extract_inline_elements(source_text)
                        units.append(TranslationUnit(
                            unit_id=unit_id,
                            source_text=text_with_placeholders,
                            shield_map=shield_map,
                            metadata={'source': 'translate-toolkit'},
                        ))
    else:
        # Regex fallback for XLIFF 1.x
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
                text_with_placeholders, shield_map = extract_inline_elements(source_text)

                units.append(TranslationUnit(
                    unit_id=unit_id,
                    source_text=text_with_placeholders,
                    shield_map=shield_map,
                    metadata={'source': 'regex'},
                ))

    return units


def parse_xliff_2(content: str) -> list[TranslationUnit]:
    """Parse XLIFF 2.0 format.

    XLIFF 2.0 structure: <unit><segment><source>...</source></segment></unit>

    Args:
        content: XLIFF 2.0 file content

    Returns:
        List of TranslationUnit objects

    """
    units: list[TranslationUnit] = []

    # Try translate-toolkit for XLIFF 2.0 if available
    try:
        from translate.storage.xliff2 import xlifffile
        xliff_2_parser = xlifffile()
        xliff_2_parser.parse(content.encode('utf-8'))
        use_toolkit = True
    except Exception:
        use_toolkit = False

    if use_toolkit:
        for node in xliff_2_parser.body.iter():
            if node.tag == 'unit':
                unit_id = node.get('id', '')
                # XLIFF 2.0 uses <segment><source>...</source></segment>
                for segment in node.findall('segment'):
                    source_elem = segment.find('source')
                    if source_elem is not None and source_elem.text:
                        text_with_placeholders, shield_map = extract_inline_elements(source_elem.text)
                        units.append(TranslationUnit(
                            unit_id=f"{unit_id}_{segment.get('id', '0')}",
                            source_text=text_with_placeholders,
                            shield_map=shield_map,
                            metadata={'source': 'translate-toolkit', 'xliff_version': '2.0'},
                        ))
    else:
        # Regex fallback for XLIFF 2.0
        unit_pattern = re.compile(
            r'<unit[^>]*id="([^"]+)"[^>]*>(.*?)</unit>',
            re.DOTALL,
        )
        segment_pattern = re.compile(
            r'<segment[^>]*id="([^"]+)"[^>]*>(.*?)</segment>',
            re.DOTALL,
        )
        source_pattern = re.compile(r'<source[^>]*>(.*?)</source>', re.DOTALL)

        for unit_match in unit_pattern.finditer(content):
            unit_id = unit_match.group(1)
            unit_content = unit_match.group(2)

            for seg_match in segment_pattern.finditer(unit_content):
                seg_id = seg_match.group(1)
                seg_content = seg_match.group(2)

                source_match = source_pattern.search(seg_content)
                if source_match:
                    source_text = source_match.group(1).strip()
                    text_with_placeholders, shield_map = extract_inline_elements(source_text)

                    units.append(TranslationUnit(
                        unit_id=f"{unit_id}_{seg_id}",
                        source_text=text_with_placeholders,
                        shield_map=shield_map,
                        metadata={'source': 'regex', 'xliff_version': '2.0'},
                    ))

    return units


class XliffParser:
    """Parser for XLIFF files (1.x and 2.0 formats).

    Uses translate-toolkit for structural parsing when available,
    with regex fallback for inline element extraction.
    """

    def __init__(self):
        """Initialize XliffParser."""
        self._version: str | None = None

    @property
    def version(self) -> str | None:
        """Detected XLIFF version."""
        return self._version

    def parse(self, path: str) -> list[TranslationUnit]:
        """Parse XLIFF file and return translation units.

        Args:
            path: Path to XLIFF file (.xliff or .xlf)

        Returns:
            List of TranslationUnit objects with unit_id, source_text, shield_map

        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If file is not valid XLIFF

        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"XLIFF file not found: {path}")

        content = file_path.read_text(encoding='utf-8')

        # Detect version
        self._version = detect_xliff_version(content)
        if self._version == 'unknown':
            raise ValueError(f"Unable to detect XLIFF version in: {path}")

        # Parse based on version
        if self._version == '1.x':
            return parse_xliff_1x(content)
        elif self._version == '2.0':
            return parse_xliff_2(content)
        else:
            raise ValueError(f"Unsupported XLIFF version: {self._version}")

    def parse_string(self, content: str) -> list[TranslationUnit]:
        """Parse XLIFF content from string.

        Args:
            content: XLIFF file content as string

        Returns:
            List of TranslationUnit objects

        """
        self._version = detect_xliff_version(content)
        if self._version == 'unknown':
            raise ValueError("Unable to detect XLIFF version")

        if self._version == '1.x':
            return parse_xliff_1x(content)
        elif self._version == '2.0':
            return parse_xliff_2(content)
        else:
            raise ValueError(f"Unsupported XLIFF version: {self._version}")
