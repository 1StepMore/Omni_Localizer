# OL 改进计划：Frontmatter 支持

**版本**: v1.0
**目标**: 为 OL 输出添加可解析的元数据头，便于下游 ORF 追踪
**生效日期**: 2026年5月

---

## 1. 背景与目标

### 1.1 为什么需要这个改动

当前 OL 的输出（MD 和 XLIFF）**不包含任何元数据**：
- 源语言、目标语言未嵌入输出文件
- 无法知道这是哪个文件的翻译结果
- 下游 ORF 读取 OL 输出时，无法确定源格式和翻译上下文

### 1.2 改动范围

| 改动项 | 文件 | 优先级 |
|--------|------|--------|
| MD 输出添加 YAML frontmatter | `ol_cli.py` | 🟡 中 |
| XLIFF 输出添加 note 头 | `ol_xliff/` | 🟢 低 |

---

## 2. 方案：MD 输出 Frontmatter

### 2.1 目标

在 OL 翻译后的 MD 文件**开头**添加 YAML frontmatter，记录：
- `source_lang`: 源语言
- `target_lang`: 目标语言
- `original_file`: 原始输入文件名
- `processor`: "OL"
- `version`: OL 版本
- `translated_at`: 翻译时间（ISO 8601）

### 2.2 注入点

**文件**: `/mnt/d/贯维/Omni_Localizer/src/ol_cli.py`
**函数**: `_translate_md_async()` 或 `translate_md()`
**位置**: 在 `output_file.write_text()` 调用之前（约 line 124）

### 2.3 实现代码

在 `ol_cli.py` 顶部添加常量：

```python
# ========== OL Frontmatter 支持 ==========

from datetime import datetime, timezone

def _generate_frontmatter(
    source_lang: str,
    target_lang: str,
    original_filename: str,
    ol_version: str = "0.1.0",
) -> str:
    """生成 YAML frontmatter 头

    Args:
        source_lang: 源语言代码 (ISO 639-1)
        target_lang: 目标语言代码 (ISO 639-1)
        original_filename: 原始输入文件名
        ol_version: OL 版本号

    Returns:
        YAML frontmatter 字符串，包含前导和尾随 ---
    """
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

    frontmatter_lines = [
        "---",
        f"source_lang: {source_lang}",
        f"target_lang: {target_lang}",
        f"original_file: {original_filename}",
        'processor: "OL"',
        f'version: "{ol_version}"',
        f"translated_at: {timestamp}",
        "...",
        "",
    ]

    return "\n".join(frontmatter_lines)


def _get_ol_version() -> str:
    """获取 OL 版本号"""
    try:
        from ol import __version__
        return __version__
    except ImportError:
        return "0.1.0"
```

找到 `translate_md()` 函数中输出写入的位置，修改：

**修改前（约 line 124）**:
```python
output_file.write_text(repaired, encoding="utf-8")
```

**修改后**:
```python
# 生成带 frontmatter 的输出
frontmatter = _generate_frontmatter(
    source_lang=src_lang,
    target_lang=tgt_lang,
    original_filename=input_path.name,
    ol_version=_get_ol_version(),
)

# 可选：检测是否已有 frontmatter（避免重复添加）
if repaired.strip().startswith('---'):
    # 已有 frontmatter，跳过添加
    output_content = repaired
else:
    output_content = frontmatter + repaired

output_file.write_text(output_content, encoding="utf-8")
```

### 2.4 预期输出

**输入**: `spec.md`
```markdown
# User Manual

This is the content to translate.
```

**输出**: `spec_zh.md`
```yaml
---
source_lang: en
target_lang: zh
original_file: spec.md
processor: "OL"
version: "0.1.0"
translated_at: 2026-05-22T15:00:00Z
...

# 用户手册

这是要翻译的内容。
```

### 2.5 边界情况处理

| 情况 | 处理方式 |
|------|----------|
| 输入 MD 已有 frontmatter | 检测到 `---` 开头，跳过添加 |
| 输入 MD 以 `---` 开头但不是 YAML | 添加新 frontmatter（保留原有内容） |
| 文件写入失败 | 记录错误，不添加 frontmatter，写入原始翻译结果 |
| 版本获取失败 | 使用默认 "0.1.0" |

### 2.6 验证测试

```python
# tests/test_frontmatter.py

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from ol_cli import _translate_md_async, _generate_frontmatter, _get_ol_version

def test_frontmatter_format():
    """测试 frontmatter 格式正确"""
    fm = _generate_frontmatter(
        source_lang="en",
        target_lang="zh",
        original_filename="test.md",
        ol_version="0.1.0",
    )

    assert fm.startswith("---\n")
    assert "source_lang: en" in fm
    assert "target_lang: zh" in fm
    assert 'original_file: "test.md"' in fm
    assert 'processor: "OL"' in fm
    assert 'version: "0.1.0"' in fm
    assert "translated_at:" in fm
    assert fm.endswith("\n...\n\n")

def test_frontmatter_timestamp_is_valid_iso():
    """测试时间戳是有效的 ISO 8601 格式"""
    import re
    fm = _generate_frontmatter("en", "zh", "test.md")
    # 匹配 "2026-05-22T15:00:00Z" 格式
    timestamp_match = re.search(r'translated_at: ([\dT:Z]+)', fm)
    assert timestamp_match is not None
    assert timestamp_match.group(1).endswith('Z')

def test_frontmatter_not_added_if_already_present():
    """测试如果输入已有 frontmatter 则不重复添加"""
    existing_frontmatter = """---
source_lang: fr
target_lang: de
...

# Existing content
"""

    # 模拟输入检测逻辑
    if existing_frontmatter.strip().startswith('---'):
        output = existing_frontmatter
    else:
        output = _generate_frontmatter("en", "zh", "test.md") + existing_frontmatter

    # 应该只有一个 ---
    assert output.count('---') == 1

def test_version_fallback():
    """测试版本获取失败时使用默认值"""
    version = _get_ol_version()
    assert version == "0.1.0"  # 因为 __version__ 不存在

@patch('ol_cli.ModelPool')
@patch('ol_cli.shield_markdown')
@patch('ol_cli.unshield_markdown')
async def test_translate_md_adds_frontmatter(
    mock_unshield, mock_shield, mock_pool, tmp_path
):
    """测试 translate_md 添加 frontmatter 到输出"""
    # Setup
    input_file = tmp_path / "test.md"
    input_file.write_text("# Hello\nWorld", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    mock_shield.return_value = ("# Hello\nWorld", {})
    mock_pool.return_value.translate.return_value = "# 你好\n世界"
    mock_unshield.return_value = "# 你好\n世界"

    # Execute
    result = await _translate_md_async(
        input_path=input_file,
        output_path=output_dir,
        src_lang="en",
        tgt_lang="zh",
        config_path=None,
        json_output=False,
    )

    # Assert
    output_file = output_dir / "test.md"
    assert output_file.exists()

    content = output_file.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "source_lang: en" in content
    assert "target_lang: zh" in content
    assert "# 你好" in content  # 翻译内容在 frontmatter 之后
```

---

## 3. 可选增强：XLIFF Header note

### 3.1 目标

在 XLIFF 输出中添加 `<header>` 级别的 `<note>` 元素，记录翻译元数据。

### 3.2 注入点

**文件**: `/mnt/d/贯维/Omni_Localizer/src/ol_xliff/generator.py`
**函数**: `generate_xliff_1_2()` 或 `to_bytes()`

### 3.3 实现代码

在 `XLIFFFileGenerator` 类中添加方法：

```python
def add_header_note(self, note: str, from_attr: str = "OL") -> None:
    """添加 header 级别的 note

    Args:
        note: note 内容
        from_attr: note 的 from 属性值
    """
    self.header_notes.append({"from": from_attr, "text": note})

def _build_header_xml(self) -> str:
    """构建 XLIFF header XML"""
    if not self.header_notes:
        return ""

    notes_xml = ""
    for note in self.header_notes:
        notes_xml += f'<note from="{note["from"]}">{self._escape_xml(note["text"])}</note>\n'

    return f"""
  <header>
{notes_xml}  </header>
"""
```

在 `generate_xliff_1_2()` 方法中，在 `<xliff>` 标签后、`<file>` 标签前插入 header：

**修改 generate_xliff_1_2() 返回的 XML 字符串构建**（约 line 59）:

```python
def generate_xliff_1_2(self) -> bytes:
    # ... existing header building ...

    notes_xml = self._build_header_xml()
    xml_parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<xliff version="{self.attributes.xliff_version}"'
        f' xmlns="{self.XLIFF_NS}">',
        notes_xml,  # 插入 header
        f'  <file original="{self._escape_xml(self.attributes.original or "")}"'
        # ... rest of method ...
    ]
    # ...
```

在 `_translate_xliff_async()` 或翻译完成后，调用：

```python
# 在 ol_cli.py 的 translate_xliff 中，翻译完成后
generator.add_header_note(
    note=f"Translated from {src_lang} to {tgt_lang} by OL",
    from_attr="OL"
)
```

### 3.4 预期 XLIFF 输出

```xml
<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <header>
    <note from="OL">Translated from en to zh by OL</note>
  </header>
  <file original="spec.md" source-language="en" target-language="zh">
    <body>
      <trans-unit id="1">
        <source>Hello</source>
        <target>你好</target>
      </trans-unit>
    </body>
  </file>
</xliff>
```

---

## 4. 风险与缓解

| 风险 | 影响 | 缓解策略 |
|------|------|----------|
| Frontmatter 干扰下游处理 | 部分工具可能不识别 `---` 块 | 使用标准 YAML，仅当 `--add-frontmatter` 启用时添加 |
| 重复添加 frontmatter | 多次翻译后有多重 `---` 块 | 检测 `---` 开头，跳过已存在的 |
| XLIFF header note 非标准 | translate-toolkit 可能不支持 | 只在 OL 内部使用，ORF 可忽略 |

---

## 5. 实施检查清单

### 阶段一：MD Frontmatter（预计 0.5 小时）

- [ ] 在 `ol_cli.py` 添加 `_generate_frontmatter()` 函数
- [ ] 添加 `_get_ol_version()` 函数
- [ ] 修改 `translate_md()` 中的 `output_file.write_text()` 逻辑
- [ ] 验证 `ol translate-md input.md` 输出包含正确的 frontmatter
- [ ] 验证输入 MD 已有 frontmatter 时不重复添加
- [ ] 添加单元测试 `tests/test_frontmatter.py`
- [ ] 运行现有测试确保无回归

### 阶段二：XLIFF Header Note（可选，预计 0.5 小时）

- [ ] 在 `ol_xliff/generator.py` 添加 `add_header_note()` 和 `_build_header_xml()` 方法
- [ ] 在 `generate_xliff_1_2()` 中插入 header XML
- [ ] 在 `ol_cli.py` 的 `translate_xliff()` 中调用 `add_header_note()`
- [ ] 验证 XLIFF 输出包含 `<header><note from="OL">...</note></header>`

---

## 6. 向后兼容性说明

| 改动 | 影响 | 缓解 |
|------|------|------|
| MD 输出新增 frontmatter | 可能有工具依赖纯 markdown | 添加 `--add-frontmatter` CLI 选项，默认启用 |
| XLIFF 新增 header note | 非标准扩展，可能被忽略 | 使用标准 `<note>` 元素，兼容 XLIFF 1.2 规范 |

---

## 7. CLI 选项建议

```python
# 在 ol_cli.py 添加新选项
@app.command()
def translate_md(
    # ... existing options ...
    add_frontmatter: bool = typer.Option(
        True,
        "--frontmatter/--no-frontmatter",
        help="Add YAML frontmatter with translation metadata to output file"
    ),
):
```

---

## 8. 未来扩展

1. **自定义 frontmatter 字段**：允许用户通过 config 添加额外字段
2. **Frontmatter 模板**：支持自定义 frontmatter 格式
3. **OML 注释格式**：除了 YAML，可选添加 HTML 注释 `<!-- OL: translated_at=... -->`
