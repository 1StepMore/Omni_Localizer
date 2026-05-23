"""XLIFF bus for Omni-Localizer using translate-toolkit."""
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ol_buses.xliff_shield import replace_tags_with_placeholders
from ol_core.dataclass import ChannelType, TranslationContext, TranslationUnit


def validate_xliff_structure(path: str) -> bool:
    """Validate XLIFF file has required structure."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding='utf-8')
        return '<xliff' in content and '<file' in content
    except Exception:
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


def write_target_back(ctx: TranslationContext, output_path: str) -> None:
    """Write translated content back to XLIFF format.

    Args:
        ctx: TranslationContext with translated units
        output_path: Output file path

    """
    # Read original file to preserve structure
    original_path = Path(ctx.file_path)
    content = original_path.read_text(encoding='utf-8')

    # Replace each unit's translation
    for unit in ctx.units:
        if unit.target_text is not None:
            # Find and replace the target element for this unit
            import re
            target_pattern = re.compile(
                rf'(<trans-unit[^>]*id="{re.escape(unit.unit_id)}"[^>]*>.*?)<target[^>]*>.*?</target>(.*?</trans-unit>)',
                re.DOTALL,
            )

            # Restore original tags in target
            restored_target = unit.target_text

            content = target_pattern.sub(
                lambda m: m.group(1) + f'<target>{restored_target}</target>' + m.group(2),
                content,
            )

    Path(output_path).write_text(content, encoding='utf-8')
