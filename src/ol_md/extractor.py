from collections.abc import Iterator

from ol_core.dataclass import TranslationUnit


def extract_translatable_tokens(tokens, skip_urls: bool = True) -> Iterator[TranslationUnit]:
    """Extract text content tokens for translation.

    Skips:
    - Code blocks (fence)
    - Images
    - Links (just URL)
    - Softbreaks

    Warns on unknown token types.

    Args:
        tokens: List of markdown-it tokens
        skip_urls: If True, skip link URLs in alt text extraction

    Yields:
        TranslationUnit for each translatable paragraph/heading

    Raises:
        None (logs warning for unknown token types)

    """
    import warnings

    current_unit_id = 1
    known_types = {
        'paragraph_open', 'paragraph_close', 'heading_open', 'heading_close',
        'text', 'softbreak', 'hardbreak', 'code_block', 'fence', 'html_block',
        'link_open', 'link_close', 'image', 'strong_open', 'strong_close',
        'em_open', 'em_close', 's_open', 's_close', 'bullet_list_open',
        'bullet_list_close', 'ordered_list_open', 'ordered_list_close',
        'list_item_open', 'list_item_close', 'blockquote_open', 'blockquote_close',
    }

    for token in tokens:
        token_type = token.type

        # Skip content we don't translate
        if token_type in ('fence', 'code_block', 'html_block', 'image', 'softbreak'):
            continue

        # Skip link_open/link_close pairs (URL content)
        if token_type in ('link_open', 'link_close'):
            continue

        # Extract text content from token
        if hasattr(token, 'content') and token.content:
            content = token.content.strip()
            if content:
                yield TranslationUnit(
                    unit_id=f'md_{current_unit_id}',
                    source_text=content,
                    shield_map={},
                    metadata={'token_type': token_type},
                )
                current_unit_id += 1
        elif token_type not in known_types:
            # Warn on unknown token type but don't crash
            warnings.warn(f"Unknown token type: {token_type}", RuntimeWarning)


def extract_and_shield_md_units(md_text: str) -> list[TranslationUnit]:
    """Parse MD text and extract translatable units for concurrent translation.

    Each unit corresponds to an inline token's text content. Shield maps are
    empty because markdown structure (code fences, images, links) is preserved
    at the token level — only bare text reaches the LLM.

    Args:
        md_text: Raw markdown text

    Returns:
        List of TranslationUnits with source_text and empty shield_map,
        in token order for 1:1 mapping with TokenPositionTracker.rebuild().
    """
    from ol_buses.md_bus import parse_md_to_tokens
    tokens = parse_md_to_tokens(md_text)
    return list(extract_translatable_tokens(tokens))


def is_translatable(token) -> bool:
    """Check if a token type is translatable."""
    non_translatable = {
        'fence', 'code_block', 'html_block', 'image', 'link_open', 'link_close',
        'softbreak', 'hardbreak',
    }
    return token.type not in non_translatable


def get_text_content(token) -> str:
    """Extract text content from token safely."""
    if hasattr(token, 'content'):
        return token.content or ''
    return ''
