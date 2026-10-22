def _heading_level(token) -> int:
    """ATX depth from the token tag; setext `markup` is `=`/`-`, not a prefix."""
    tag = getattr(token, 'tag', '') or ''
    if len(tag) == 2 and tag[0] == 'h' and tag[1] in '123456':
        return int(tag[1])
    return len(getattr(token, 'markup', '') or '')


class _MarkdownWriter:
    """Line sink that stamps the active block prefixes onto every new line."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._prefixes: list[str] = []
        self._tail = ''
        self._line_start = True

    def push_prefix(self, prefix: str) -> None:
        self._prefixes.append(prefix)
        if not self._line_start:
            self._append(prefix)

    def pop_prefix(self) -> None:
        if self._prefixes:
            self._prefixes.pop()

    def write(self, text: str) -> None:
        for index, segment in enumerate(text.split('\n')):
            if index:
                self._append('\n')
            if segment:
                if self._line_start:
                    self._append(''.join(self._prefixes))
                self._append(segment)

    def ensure_newline(self) -> None:
        if not self._tail.endswith('\n'):
            self._append('\n')

    def ensure_blank_line(self) -> None:
        self.ensure_newline()
        if not self._tail.endswith('\n\n'):
            self._append('\n')

    def _append(self, piece: str) -> None:
        if not piece:
            return
        self._parts.append(piece)
        self._tail = (self._tail + piece)[-2:]
        self._line_start = piece.endswith('\n')

    def getvalue(self) -> str:
        return ''.join(self._parts)


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
        - Emits block structure: ATX heading prefixes, fenced blocks, horizontal
          rules, list markers (`- ` / `N. `, indented two spaces per nesting
          level) and blockquote prefixes (`> `, one per nesting level).
        - Separates blocks with blank lines, except inside tight lists, where
          `paragraph_close.hidden` keeps items on consecutive lines.
        """
        writer = _MarkdownWriter()
        lists: list[dict] = []
        unit_index = 0

        for token in tokens:
            token_type = getattr(token, 'type', None)

            if token_type == 'inline' and getattr(token, 'content', ''):
                if unit_index < len(units):
                    target = units[unit_index].target_text
                    writer.write(target if target else token.content)
                    unit_index += 1
                else:
                    writer.write(token.content)

            elif token_type == 'heading_open':
                level = _heading_level(token)
                if level:
                    writer.write('#' * level + ' ')

            elif token_type == 'fence':
                info = getattr(token, 'info', '') or ''
                content = getattr(token, 'content', '') or ''
                writer.write(f"```{info}\n{content}```")
                writer.ensure_blank_line()

            elif token_type == 'hr':
                writer.write('---')
                writer.ensure_blank_line()

            elif token_type in ('bullet_list_open', 'ordered_list_open'):
                ordered = token_type == 'ordered_list_open'
                start = 1
                if ordered:
                    start = (getattr(token, 'attrs', None) or {}).get('start', 1)
                lists.append({'ordered': ordered, 'next': int(start)})

            elif token_type == 'list_item_open':
                indent = '  ' * max(len(lists) - 1, 0)
                if lists and lists[-1]['ordered']:
                    marker = f"{lists[-1]['next']}. "
                    lists[-1]['next'] += 1
                else:
                    marker = '- '
                writer.write(indent + marker)

            elif token_type == 'list_item_close':
                writer.ensure_newline()

            elif token_type in ('bullet_list_close', 'ordered_list_close'):
                if lists:
                    lists.pop()
                if lists:
                    writer.ensure_newline()
                else:
                    writer.ensure_blank_line()

            elif token_type == 'blockquote_open':
                writer.push_prefix('> ')

            elif token_type == 'blockquote_close':
                writer.pop_prefix()
                writer.ensure_blank_line()

            elif token_type == 'paragraph_close':
                if getattr(token, 'hidden', False):
                    writer.ensure_newline()
                else:
                    writer.ensure_blank_line()

            elif token_type == 'heading_close':
                writer.ensure_blank_line()

            else:
                content = getattr(token, 'content', '')
                if content:
                    writer.write(content)

        return writer.getvalue()
