"""XLIFF Repair Pipeline - orchestrates 4-layer repair cascade."""

from ol_xliff.repair.level1 import level1_regex_clean
from ol_xliff.repair.level2 import level2_span_align
from ol_xliff.repair.level3 import level3_llm_restore
from ol_xliff.repair.level4 import level4_safe_fallback


class XLIFFRepairPipeline:
    """Orchestrates 4-layer repair cascade for XLIFF placeholder restoration.

    Cascade flow:
        L1: Regex clean whitespace around placeholders
        L2: Span alignment using anchor mapping
        L3: LLM restoration (if restorer provided)
        L4: Safe fallback (always completes)

    Phase 2 integration: LLM restorer is MockLLMRestorer (pass-through).
    Phase 3a integration: LiteLLMRestorer with actual LLM calls.
    """

    def __init__(self, llm_restorer=None):
        """Initialize pipeline with optional LLM restorer.

        Args:
            llm_restorer: Optional restorer object with restore_placeholders method.
                          If None, L3 is skipped in the cascade.

        """
        self.llm_restorer = llm_restorer

    def is_complete(self, text: str, shield_map: dict[str, str]) -> bool:
        """Check if all placeholders from shield_map are present in text.

        Args:
            text: Translated text to check
            shield_map: Dict mapping placeholder_id -> original_tag

        Returns:
            True if all placeholders present or shield_map is empty, False otherwise.

        """
        if not shield_map:
            return True
        for placeholder_id in shield_map:
            placeholder_str = f'{{{{_OL_XTAG_{placeholder_id}_}}}}'
            if placeholder_str not in text and placeholder_id not in text:
                return False
        return True

    def repair(self, text: str, original: str, shield_map: dict[str, str]) -> str:
        """Repair text through 4-layer cascade until complete.

        Args:
            text: Translated text with potential placeholder issues
            original: Original source text (for L2/L3 reference)
            shield_map: Dict mapping placeholder_id -> original_tag

        Returns:
            Repaired text with all placeholders restored

        """
        current_text = text

        cleaned, modified = level1_regex_clean(current_text)
        if modified:
            current_text = cleaned

        if self.is_complete(current_text, shield_map):
            return current_text

        aligned = level2_span_align(current_text, shield_map, original)
        if aligned != current_text:
            current_text = aligned

        if self.is_complete(current_text, shield_map):
            return current_text

        if self.llm_restorer:
            restored = level3_llm_restore(current_text, original, shield_map, self.llm_restorer)
            if restored != current_text:
                current_text = restored

        if self.is_complete(current_text, shield_map):
            return current_text

        missing = {
            k: v for k, v in shield_map.items()
            if f'{{{{_OL_XTAG_{k}_}}}}' not in current_text
        }
        if missing:
            current_text = level4_safe_fallback(current_text, missing)

        return current_text
