from ol_md.pipeline import MDRepairPipeline


class TestRepairPipeline:
    def test_l1_stop_cascade(self):
        pipeline = MDRepairPipeline()
        result = pipeline.repair('text \x00OL_CODE_0000\x00 end', 'original', {'CODE_0000': 'code'})
        assert 'OL_CODE_0000' in result

    def test_l4_fallback(self):
        pipeline = MDRepairPipeline()
        result = pipeline.repair('text end', 'original \x00OL_CODE_0000\x00', {'CODE_0000': 'code'})
        assert 'OL_WARN' in result


class TestShieldValueAwareCompleteness:
    """T13-02 回归：MD 通道先 unshield 再 repair，判据必须是「键名或原值」。

    修复前 is_complete()/missing 只查键名（image_0000），而 unshield 之后正文里
    只剩原值（![Image 1](a.png)），于是 shield_map 非空时永远判「不完整」，
    一路升级到 Level 4 把每个受保护内容再追加一遍 —— 表现为图片/图注数量翻倍。
    """

    IMG = "![Image 1](a.png)"

    def test_is_complete_accepts_restored_original_value(self):
        pipeline = MDRepairPipeline()
        assert pipeline.is_complete(f"正文 {self.IMG}", {"image_0000": self.IMG})

    def test_is_complete_rejects_truly_missing_entry(self):
        pipeline = MDRepairPipeline()
        assert not pipeline.is_complete("正文", {"image_0000": self.IMG})

    def test_restored_image_is_not_duplicated(self):
        pipeline = MDRepairPipeline()
        text = f"正文\n\n{self.IMG}\n\n结尾"
        result = pipeline.repair(text, text, {"image_0000": self.IMG})
        assert result.count(self.IMG) == 1, (
            f"图片引用被重复插入：{result!r}；1 个引用进 → 应 1 个引用出"
        )
        assert "OL_WARN" not in result

    def test_genuinely_missing_image_is_still_appended(self):
        pipeline = MDRepairPipeline()
        result = pipeline.repair("正文无图", "原文有图", {"image_0000": self.IMG})
        assert self.IMG in result
        assert "OL_WARN" in result


class TestSequentialPathMarkerForm:
    """#244 D1 回归：sequential 路径（CI concurrency=1）的图片翻倍复现。

    translate_md.py 的主路径在 unshield 之前调 repair()，此时正文里是标记
    形态（[OL:IMG:0000]）。is_complete 非严格判据只查裸键名（image_0000），
    它永远不是 [OL:IMG:0000] 的子串 → 恒判「不完整」→ 一路升级到 Level 4
    把原值追加 → unshield 还原正文标记后 2 正文 + 2 追加 = 4（CI 夜跑
    src=2 out=4 确定性翻倍的机制链）。修复后：标记形态命中即视为未丢失，
    不再升级 level4。
    """

    IMG1 = "![Image 1](./source_images/source_image_1.png)"
    IMG2 = "![Image 2](./source_images/source_image_2.png)"
    MAP = {
        "image_0000": "![Image 1](./source_images/source_image_1.png)",
        "image_0001": "![Image 2](./source_images/source_image_2.png)",
    }

    def _marker_text(self) -> str:
        # sequential 路径 repair() 的真实输入形态：LLM 译文 + 未还原标记
        return (
            "Body one.\n\n[OL:IMG:0000]\n\nBody two.\n\n[OL:IMG:0001]\n\n"
            "## Images\n\n[OL:IMG:0000]\n[OL:IMG:0001]"
        )

    def test_is_complete_accepts_marker_form(self):
        from ol_md.shield import _key_to_marker

        assert _key_to_marker("image_0000") == "[OL:IMG:0000]"
        pipeline = MDRepairPipeline()
        assert pipeline.is_complete(self._marker_text(), self.MAP), (
            "标记形态 [OL:IMG:xxxx] 在文中时应视为受保护内容未丢失"
        )

    def test_repair_before_unshield_does_not_duplicate(self):
        # 复现 CI 翻倍的最小序列：repair(标记文本) → unshield
        from ol_md.shield import unshield_markdown

        pipeline = MDRepairPipeline()
        repaired = pipeline.repair(self._marker_text(), "original", self.MAP)
        restored = unshield_markdown(repaired, self.MAP)
        assert restored.count(self.IMG1) == 1, (
            f"图片 1 被重复插入：{restored.count(self.IMG1)} 次；2 refs 进 → 应 2 refs 出"
        )
        assert restored.count(self.IMG2) == 1, (
            f"图片 2 被重复插入：{restored.count(self.IMG2)} 次；2 refs 进 → 应 2 refs 出"
        )


class TestImageRefIntegritySelfCheck:
    """#244 F3 回归：unshield 恢复后自检治愈模型破坏的图片路径（T13-02b）。

    实测投毒签名（缓存 ffe2f7d4，2026-11-05 产出）：路径下划线被剥
    （source_images/source_image_1.png → sourceimages/sourceimage_1.png）
    且目标语言文本被粘进 URL（…png不至于）→ 不可解析 → 回填丢图（out=1）。
    自检把 basename（仅字母数字口径）仍能对上 shield 原件的 ref 修回原值。
    """

    ORIG1 = "![Image 1](./source_images/source_image_1.png)"
    ORIG2 = "![Image 2](./source_images/source_image_2.png)"
    MAP = {"image_0000": ORIG1, "image_0001": ORIG2}

    def test_exact_refs_pass_untouched(self):
        from ol_md.shield import restore_image_ref_integrity

        text = f"正文\n\n{self.ORIG1}\n{self.ORIG2}"
        assert restore_image_ref_integrity(text, self.MAP) == text

    def test_mangled_ref_with_garbage_suffix_is_healed(self):
        from ol_md.shield import restore_image_ref_integrity

        mangled = "![Image 1](./sourceimages/sourceimage_1.png不至于)"
        text = f"正文\n\n{mangled}\n{self.ORIG2}"
        out = restore_image_ref_integrity(text, self.MAP)
        assert out.count(self.ORIG1) == 1
        assert "不至于" not in out
        assert out.count(self.ORIG2) == 1

    def test_underscore_stripped_ref_is_healed(self):
        from ol_md.shield import restore_image_ref_integrity

        text = f"正文\n\n{self.ORIG1}\n![Image 2](./sourceimages/sourceimage_2.png)"
        out = restore_image_ref_integrity(text, self.MAP)
        assert out.count(self.ORIG2) == 1

    def test_unmatchable_ref_left_alone(self):
        from ol_md.shield import restore_image_ref_integrity

        text = "正文\n\n![?](./nowhere/ghost.png)"
        assert restore_image_ref_integrity(text, self.MAP) == text

    def test_non_image_shield_map_is_noop(self):
        from ol_md.shield import restore_image_ref_integrity

        text = "正文 [OL:CODE:0000] 尾"
        assert restore_image_ref_integrity(text, {"code_0000": "x = 1"}) == text
