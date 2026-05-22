

class TokenPositionTracker:
    def __init__(self, tokens: list):
        self.tokens = tokens

    def validate_balance(self) -> bool:
        return sum(t.nesting for t in self.tokens) == 0

    @staticmethod
    def rebuild(tokens: list, units: list) -> str:
        result_parts = []
        unit_index = 0
        for token in tokens:
            if hasattr(token, 'content') and token.content:
                if unit_index < len(units):
                    result_parts.append(units[unit_index].target_text or token.content)
                    unit_index += 1
                else:
                    result_parts.append(token.content)
            elif hasattr(token, 'content'):
                result_parts.append(token.content)
        return '\n'.join(result_parts)
