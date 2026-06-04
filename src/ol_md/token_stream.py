class TokenPositionTracker:
    def __init__(self, tokens: list):
        self.tokens = self._flatten(tokens)

    @staticmethod
    def _flatten(tokens: list) -> list:
        """Flatten token tree so children of inline/container tokens are included.

        markdown-it wraps inline content (code, images, text spans) inside an
        `inline` container token. Tests that look for self-closing inline
        tokens by iterating `tracker.tokens` need to see those children too,
        not just the container.
        """
        result = []
        for token in tokens:
            result.append(token)
            children = getattr(token, 'children', None)
            if children:
                result.extend(TokenPositionTracker._flatten(children))
        return result

    def validate_balance(self) -> bool:
        return sum(t.nesting for t in self.tokens) == 0

    @staticmethod
    def rebuild(tokens: list, units: list) -> str:
        """Rebuild markdown from markdown-it tokens, substituting translations.

        Walks the token stream and:
        - Replaces `inline` container content with the corresponding unit's
          target_text (falling back to original content if no unit remains).
        - Emits structural markup for `heading_open` (the `#` prefix) and
          `fence` blocks (the ``` fences with info string) so the rebuilt
          markdown retains its structural shape.
        - Emits a newline after paragraph/heading closes for readability.
        """
        result_parts: list[str] = []
        unit_index = 0
        for token in tokens:
            token_type = getattr(token, 'type', None)

            if token_type == 'inline' and getattr(token, 'content', ''):
                if unit_index < len(units):
                    target = units[unit_index].target_text
                    result_parts.append(target if target else token.content)
                    unit_index += 1
                else:
                    result_parts.append(token.content)

            elif token_type == 'heading_open':
                markup = getattr(token, 'markup', '') or ''
                if markup:
                    result_parts.append(markup + ' ')

            elif token_type == 'fence':
                info = getattr(token, 'info', '') or ''
                content = getattr(token, 'content', '') or ''
                result_parts.append(f"```{info}\n{content}```")

            elif token_type in ('paragraph_close', 'heading_close'):
                result_parts.append('\n')

            else:
                content = getattr(token, 'content', '')
                if content:
                    result_parts.append(content)

        return ''.join(result_parts)
