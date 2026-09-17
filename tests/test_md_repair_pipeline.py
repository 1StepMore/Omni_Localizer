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
