from ol_md.repair import (
    level1_regex_clean,
    level2_span_align,
    level3_llm_restore,
    level4_safe_fallback,
)


class MDRepairPipeline:
    def __init__(self, llm_restorer=None):
        self.llm_restorer = llm_restorer

    def _get_placeholder_str(self, key: str) -> str:
        return key

    def is_complete(self, text: str, shield_map: dict[str, str], strict: bool = False) -> bool:
        """判断 shield_map 中的受保护内容是否均已出现在 text 中。

        T13-02 修复：MD 通道的调用顺序是 ``unshield_markdown()`` → ``repair()``，
        因此 text 里应当出现的是 shield_map 的**原值**（如 ``![Image 1](a.png)``），
        而不是键名（``image_0000``）。原实现只查键名，导致 shield_map 非空时永远
        判定为「不完整」，一路升级到 Level 4，把每个受保护内容**再追加一遍**
        （图片/图注数量翻倍）。现在键名与原值任一命中即视为已恢复。

        Args:
            text: 待检查的文本（生产路径中已过 ``unshield_markdown``）。
            shield_map: 键（如 ``image_0000``）→ 原始内容（如 ``![Image 1](a.png)``）。
            strict: 为 True 时额外接受 ``{{_OL_XTAG_<key>_}}`` 占位符形式。

        Returns:
            True 表示所有受保护内容都已恢复（shield_map 为空时也返回 True）。
        """
        if not shield_map:
            return True

        # 原值命中：unshield_markdown 已把受保护内容还原回正文，视为已恢复。
        # 生产路径是 unshield → repair，正文里只会有原值、不会有键名，
        # 因此这条判据是 T13-02 的关键（原先缺席 → 永远判「不完整」→
        # 一路升级到 Level 4 把内容再追加一遍，图片/图注数量翻倍）。
        pending = {
            key: value for key, value in shield_map.items()
            if not (value and value in text)
        }

        if not strict:
            # 非严格（repair 的默认模式）：键名还在文本里，说明仍是带标记形态
            return all(key in text for key in pending)

        # 严格模式：要求键名以 {{_OL_XTAG_<key>_}} 占位符形式出现，
        # 裸键名（LLM 把标记当普通文本回显）不算恢复
        return all(f'{{{{_OL_XTAG_{key}_}}}}' in text for key in pending)

    def repair(self, translated_text: str, original_text: str, shield_map: dict[str, str]) -> str:
        current_text = translated_text

        cleaned, modified = level1_regex_clean(current_text)
        if modified:
            current_text = cleaned

        if self.is_complete(current_text, shield_map):
            return current_text

        aligned, l2_applied = level2_span_align(current_text, shield_map, original_text)
        if l2_applied and aligned != current_text:
            current_text = aligned

        if self.is_complete(current_text, shield_map):
            return current_text

        if self.llm_restorer:
            restored = level3_llm_restore(current_text, original_text, shield_map, self.llm_restorer)
            if restored != current_text:
                current_text = restored

        if self.is_complete(current_text, shield_map):
            return current_text

        # T13-02: 与 is_complete 同一判据——只有键名和原值都缺席才算真丢失。
        # 原先只查键名，unshield 已还原的内容会被判为「缺失」并在文末再追加一次。
        missing = {
            k: v for k, v in shield_map.items()
            if k not in current_text and v not in current_text
        }
        if missing:
            current_text = level4_safe_fallback(current_text, missing)

        return current_text
