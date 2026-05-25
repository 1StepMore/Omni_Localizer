# OPP 改进计划

> **核心原则**：OPP 只做"是什么"（结构信息），不做"怎么做"（切分决策）。
> 切分策略由 Pipeline/OLL 决定。

---

## 目标

为 OPP 添加**结构化元信息能力**，为下游 Pipeline/OLL 提供可复用的基础信息：

1. **ParagraphData.chapter** - 段落所属章节（EPUB spine 顺序已知）
2. **Chunk 结构定义** - 标准化的 chunk 元信息接口（OPP 定义结构，不做切分）
3. **GlossaryGenerator** - 通用术语提取（regex + jieba，与语言/领域无关）

---

## 用户确认的决策

| 决策点 | 选择 |
|--------|------|
| chapter 元信息 | EPUB spine 顺序 → 每个 ParagraphData 携带 chapter 字段 |
| Glossary 范围 | Regex（英文）+ jieba（中文） |
| 切分策略 | **OPP 不做切分决策**，只提供结构信息 |
| OPP-OLL 集成 | OPP 提供结构信息，OLL 自己决定如何使用 |

---

## 新增模块设计

### 1. ParagraphData.chapter 字段（修改）

```python
# src/opp/utils/dataclasses.py
@dataclass
class ParagraphData:
    text: str
    style: str                          # e.g., "Heading 1", "Normal"
    level: Optional[int]                # Heading 级别（1-6）
    chapter: Optional[str] = None       # 章节名（新增）
    runs: List[RunData] = field(default_factory=list)
```

**实现步骤**：
1. EPUB extractor 的 `_extract_chapters()` 返回带 chapter 的 ParagraphData
2. PDF extractor 已有 `_detect_heading_level()`，扩展为返回 chapter
3. 其他格式：无章节，chapter = null

---

### 2. Chunk 结构定义（新增）

```python
# src/opp/chunker.py
@dataclass
class Chunk:
    """Chunk 元信息结构（OPP 定义结构，Pipeline 填充数据）"""
    index: int                           # 块序号
    title: Optional[str]                 # 章节名（来自 ParagraphData.chapter）
    start_char: int                      # 在原文中的起始位置
    end_char: int                        # 结束位置
    char_count: int                      # 字符数
    source_md5: str                      # 用于缓存判断

@dataclass
class ChunkedResult:
    """Chunk 元信息集合（不包含文本，按需由 Pipeline 填充）"""
    chunks: List[Chunk]
    total_chars: int
    estimated_chunks: int
    metadata: DocumentMetadata

class ChunkMetaBuilder:
    """
    根据 ParagraphData 列表构建 Chunk 元信息
    只负责构建元信息，不做切分决策
    """
    def build(self, paragraphs: List[ParagraphData],
              source_md5: str) -> ChunkedResult:
        """按 chapter 分组，构建 Chunk 元信息列表"""
```

**注意**：这里只有**结构定义**，没有切分逻辑。切分由 Pipeline/OLL 自己决定。

---

### 3. GlossaryGenerator (`src/opp/glossary_generator.py`)

```python
@dataclass
class Term:
    """术语结构"""
    source: str                         # 源语言术语
    translation: str = ""               # 译文（待填充）
    context: str = ""                    # 上下文句子
    frequency: int = 0                   # 出现频率
    position: tuple[int, int] = (0, 0)  # 在原文中的位置 [start, end]

class GlossaryGenerator:
    """
    从源文档提取高频术语（通用，与语言/领域无关）
    - 英文：正则提取（专有名词、全大写、词首大写）
    - 中文：jieba 分词 + 词性标注
    """
    def generate(self, text: str, source_lang: str, top_k: int = 50) -> List[Term]:
        """
        1. 按语言选择提取策略
        2. 提取重复出现的专有名词
        3. 按频率排序，输出 top_k
        """
```

---

## 实施顺序

### Phase 1: 基础元信息（最高优先级）

1. 修改 `ParagraphData` dataclass，增加 `chapter` 字段
2. 修改 EPUB extractor，在 `_extract_chapters()` 中填充 chapter
3. 修改 PDF extractor，扩展 `_detect_heading_level()` 返回 chapter
4. 在 `DocumentMetadata` 中增加 `source_md5` 字段
5. 单元测试

### Phase 2: Chunk 结构定义

1. 创建 `Chunk` / `ChunkedResult` dataclass
2. 实现 `ChunkMetaBuilder.build()` - 按 chapter 分组构建元信息
3. 不实现切分逻辑（切分由 Pipeline/OLL 自己做）
4. 单元测试

### Phase 3: GlossaryGenerator

1. 实现 `Term` dataclass
2. 实现英文正则提取器
3. 实现中文 jieba 提取器 + 词性标注
4. 实现 `GlossaryGenerator.generate()`
5. 单元测试

### Phase 4: API 端点（可选）

> 注意：API 端点是提供结构信息，不是切分决策

1. 创建 `src/opp/chunk_api.py`（FastAPI）
2. `GET /chunk-meta` - 返回 ChunkedResult（基于已提取的内容）
3. `POST /glossary` - 返回术语列表
4. `GET /health` - 健康检查

---

## 验收标准

### ParagraphData.chapter
- [ ] EPUB spine 顺序 → 每个 ParagraphData.chapter 填充章节名
- [ ] PDF TOC 解析 → 每个 ParagraphData.chapter 填充章节名
- [ ] 无章节格式 → chapter = null

### Chunk 结构
- [ ] `Chunk` dataclass 包含 index/title/start_char/end_char/char_count/source_md5
- [ ] `ChunkMetaBuilder.build()` 按 chapter 分组
- [ ] 不做切分（无切分策略参数）

### GlossaryGenerator
- [ ] 英文专有名词提取（大小写规则）
- [ ] 中文术语提取（jieba 词性标注）
- [ ] 按频率排序，返回 top_k
- [ ] 每个 Term 包含 context（上下文句子）

---

## 排除范围（Scope Out）

- **不实现切分策略** - OPP 不做"怎么做"的决策
- **不实现 smart_chunk()** - 切分由 Pipeline/OLL 自己决定
- **不实现 glossary definitions** - 仅提取术语，不查定义
- **不实现跨文档术语关联**
- **不实现 chunk 质量自动修复**
- **不实现多语言术语** - 仅 source_lang

---

## 技术约束

- 依赖新增：`jieba`（中文分词）
- Python ≥ 3.10
- FastAPI 用于可选 API 端点

---

## 文件变更清单

| 操作 | 文件路径 |
|------|----------|
| 修改 | `src/opp/utils/dataclasses.py`（ParagraphData 增加 chapter 字段） |
| 修改 | `src/opp/extractors/epub.py`（填充 chapter 信息） |
| 修改 | `src/opp/extractors/pdf.py`（扩展 heading 检测返回 chapter） |
| 新增 | `src/opp/chunker.py`（Chunk 结构定义 + ChunkMetaBuilder） |
| 新增 | `src/opp/glossary_generator.py` |
| 新增 | `src/opp/chunk_api.py`（可选） |
| 新增 | `tests/test_chunker.py` |
| 新增 | `tests/test_glossary_generator.py` |
| 修改 | `pyproject.toml`（增加 jieba 依赖） |

---

## 对比：修改前 vs 修改后

| 项目 | 修改前 | 修改后 |
|------|--------|--------|
| Chunker | 实现 smart_chunk() 切分 | 只定义 Chunk 结构，不切分 |
| 切分策略 | OPP 决定（smart/chapter_first/paragraph） | OPP 不做切分决策 |
| API /chunk | 实现切分接口 | 移除或改为 /chunk-meta（只返回结构） |
| 核心价值 | OPP 做切分 + 提供术语 | OPP 只提供结构信息 |
| Pipeline/OLL 角色 | 使用 OPP 的切分结果 | 自己决定如何切分 |