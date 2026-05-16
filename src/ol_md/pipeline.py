from typing import Dict, Tuple, List
from ol_md.repair import level1_regex_clean, level2_span_align, level3_llm_restore, level4_safe_fallback


class MDRepairPipeline:
    def __init__(self, llm_restorer=None):
        self.llm_restorer = llm_restorer

    def is_complete(self, text: str, shield_map: Dict[str, str]) -> bool:
        if not shield_map:
            return True
        for placeholder_id in shield_map.keys():
            placeholder_str = f'\x00OL_{placeholder_id.upper().replace("_", "_")}\x00'
            if placeholder_str not in text and placeholder_id not in text:
                return False
        return True

    def repair(self, translated_text: str, original_text: str, shield_map: Dict[str, str]) -> str:
        current_text = translated_text

        cleaned, modified = level1_regex_clean(current_text)
        if modified:
            current_text = cleaned

        if self.is_complete(current_text, shield_map):
            return current_text

        aligned = level2_span_align(current_text, shield_map, original_text)
        if aligned != current_text:
            current_text = aligned

        if self.is_complete(current_text, shield_map):
            return current_text

        if self.llm_restorer:
            restored = level3_llm_restore(current_text, original_text, shield_map, self.llm_restorer)
            if restored != current_text:
                current_text = restored

        if self.is_complete(current_text, shield_map):
            return current_text

        missing = {k: v for k, v in shield_map.items() if f'\x00OL_{k.upper().replace("_", "_")}\x00' not in current_text}
        if missing:
            current_text = level4_safe_fallback(current_text, missing)

        return current_text