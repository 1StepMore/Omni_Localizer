"""MD Token Stream bus for Omni-Localizer using markdown-it-py."""
from collections.abc import Iterator
from pathlib import Path

from ol_core.dataclass import ChannelType, TranslationContext, TranslationUnit


def validate_md_structure(path: str) -> bool:
    """Validate MD file has basic structure."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding='utf-8')
        return len(content) > 0
    except Exception:
        return False

def load_md(path: str) -> TranslationContext:
    """Load MD file and create TranslationContext.

    Args:
        path: Path to MD file

    Returns:
        TranslationContext with channel_type=MD and units populated

    """
    path = Path(path)
    original_text = path.read_text(encoding='utf-8')

    tokens = parse_md_to_tokens(original_text)
    units = list(extract_translatable_tokens(tokens))

    return TranslationContext(
        file_path=str(path),
        channel_type=ChannelType.MD,
        original_full_text=original_text,
        units=units,
        glossary={},
        config={},
    )

def parse_md_to_tokens(md_text: str) -> list:
    """Parse MD text to token stream using markdown-it-py.

    Args:
        md_text: Raw markdown text

    Returns:
        List of tokens from markdown-it-py

    """
    try:
        import markdown_it
        md = markdown_it.MarkdownIt()
        return md.parse(md_text)
    except ImportError:
        # Fallback: return empty list if markdown-it-py not available
        return []

def extract_translatable_tokens(tokens) -> Iterator[TranslationUnit]:
    """Extract text content tokens for translation.

    Skips code blocks, images, links (just URL), etc.
    Yields TranslationUnit for each text paragraph/heading.
    """
    current_unit_id = 1

    for token in tokens:
        # Skip content we don't translate
        if token.type in ('fence', 'code_block', 'html_block', 'image', 'link', 'softbreak'):
            continue

        # Extract text content from token
        if hasattr(token, 'content') and token.content:
            content = token.content.strip()
            if content:
                # Shield special tokens first
                from ol_buses.md_shield import shield_special_tokens
                shielded_text, shield_map = shield_special_tokens(content)

                yield TranslationUnit(
                    unit_id=f'md_{current_unit_id}',
                    source_text=shielded_text,
                    shield_map=shield_map,
                    metadata={'token_type': token.type},
                )
                current_unit_id += 1

def rebuild_md_from_tokens(original_tokens: list, translated_units: list[TranslationUnit]) -> str:
    """Reconstruct MD with translated content.

    Args:
        original_tokens: Original markdown tokens
        translated_units: List of translated TranslationUnits

    Returns:
        Reconstructed MD text

    """
    # Simple implementation: just concatenate translated text
    # A full implementation would need to track token positions
    result_parts = []
    unit_index = 0

    for token in original_tokens:
        if hasattr(token, 'content') and token.content:
            if unit_index < len(translated_units):
                result_parts.append(translated_units[unit_index].target_text or token.content)
                unit_index += 1
            else:
                result_parts.append(token.content)
        elif hasattr(token, 'map'):
            result_parts.append(token.content if hasattr(token, 'content') else '')
        elif hasattr(token, 'content'):
            result_parts.append(token.content)

    return '\n'.join(result_parts)
