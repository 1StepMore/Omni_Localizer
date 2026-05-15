Omni-Localizer (OL) 开发计划 - 纯粹翻译与自动化质控版
文档信息
版本: v6.4-Optimized (数据结构设计优先 + Mock接口定义版)
架构: MD原生通道（Token Stream重建） + XLIFF传统通道（translate-toolkit） + 双核LQA防线（COMET+openevalkitJudge+openevalkitScorer） + LiteLLM弹性模型池 + hypomnema TMX + span-aligner锚点映射 + 零干预流水线
核心原则:
绝不重复造轮子：XLIFF操作基于translate-toolkit，MD操作基于markdown-it-py，模型路由基于LiteLLM，TM基于hypomnema，语义对齐基于span-aligner。不负责格式转换（非MD/XLIFF拒收）。
成熟轮子优先：自研仅用于核心价值（四层语义修复、通道封装），其余均采用业界验证的成熟库，实现"成熟轮子+胶水代码"架构。
鲁棒性至上：废除脆弱的AST原位覆写，采用结构化重建与原子化操作；任何异常绝不阻塞流水线，采用自动修复与降级打标机制。
大脑冗余与弹性：建立多模型池退避机制，翻译与质检引擎均配置主备模型，单点 API 故障绝不阻塞流水线，自动降级至顺位模型确保业务连续性。
质量对标传统CAT：建立确定性规则（数字、标签、术语）的硬性防线，辅以LLM评估与自动重试，确保产物可靠性。
自动化至上（零干预）：OL只做“读取 -> 翻译 -> 质检 -> 自动修复/降级 -> 写出”，全流程批处理无阻塞，以“标签溯源+离线报告”替代“交互式中断”。
报告驱动闭环：离线报告不仅是统计，更是精准的“手术刀”，提供双向溯源与待审校文件提取，实现批量翻译与定点精校的分离。
职责边界清晰：OL只做翻译，确保输入输出格式绝对一致（MD进MD出，XLIFF进XLIFF出）。

> **修订说明**：本文档在原版基础上新增"标签词汇表"和"关键技术方案设计摘要"两个章节（短期改进）；将原Phase 3拆分为Phase 3a（路由+模型池+并发基座）和Phase 3b（LQA+TM+断点续传）以降低单阶段复杂度（中 期改进）。原版已备份为 `OL_DD_Vibe_Phase版+语言质量.md.bak`。

## 标签词汇表（统一打标体系）

| 标签 | 用途 | 落点 |
|------|------|------|
| `OL_WARN: Tag_auto_appended` | 占位符/标签丢失，安全落点至句末 | MD: `<!-- OL_WARN: Tag_auto_appended -->` / XLIFF: `<note from="OL">Tag auto-appended at end</note>` |
| `OL_WARN: Low_Score` | LLM评估低分，采用次优解 | 直接注入原文 |
| `OL_WARN: Term_miss` | 术语未命中 | 记录离线报告，不阻塞 |
| `OL_WARN: Fallback` | 模型池Failover事件 | 记录离线报告 |

> **原则**：所有OL_WARN标签均为"放行+记录"模式，绝不阻塞流水线。流水线退出码始终为0（成功），警告详情见离线报告。

## 成熟轮子选型清单（v6.2增强版）

> 以下为已调研验证的成熟开源库，用于替代自研模块，实现"成熟轮子+胶水代码"的低自研架构。

| 领域 | 库名 | 版本 | 最后更新 | 用途 | PyPI/GitHub |
|------|------|------|----------|------|-------------|
| **LLM路由+Failover** | LiteLLM | 1.84.0 | **2026-05-14** | 统一API网关、100+provider、Router自动Failover | pypi.org/project/litellm |
| **成本优化+智能路由** | AgentFuse | 0.2.2 | 2026-03-29 | 双层语义缓存、智能降级、渐进式预算 | pypi.org/project/agentfuse-runtime |
| **LLM语义评估（主）** | **openevalkit** | **0.1.7** | **2026** | Scorer→Judge两层架构、Rubric可自定义、LiteLLM原生、EnsembleJudge多模型投票、智能缓存 | pypi.org/project/openevalkit |
| **LLM语义评估（参考）** | judges | 0.1.1 | 2025-06-25 | ⚠️ 已归档（Databricks存档），仅作参考不再使用 | pypi.org/project/judges |
| **翻译质量评估** | COMET | 2.2.7 | **2025-09-01** | 无参考评估(XCOMET)、错误span检测(MQM) | github.com/Unbabel/COMET |
| **翻译记忆库(TMX)** | hypomnema | 0.8 | **2026-04-09** | 流式处理、零依赖、类型安全、TMX 1.4b完整 | pypi.org/project/hypomnema |
| **词对齐+锚点映射（主）** | **span-aligner** | 0.3.2 | **2026-02-26** | 专为span映射设计，跨语言标注投影，支持mBERT/LaBSE | pypi.org/project/span-aligner |
| **词对齐+锚点映射（备）** | **VectorAlign** | 0.2.2 | 2026-01-04 | SimAlign精神继承者，支持LaBSE/mBERT | pypi.org/project/vectoralign |
| **词对齐+锚点映射（精）** | **AccAlign** | - | 2023-10-25 | AER 16.1% SOTA，LaBSE微调，zero-shot | github.com/sufenlp/AccAlign |
| **语义相似度** | sentence-transformers | 5.4.1 | **2026-04-14** | 100+语言、15K+预训练模型、语义搜索 | pypi.org/project/sentence-transformers |

> **自研比例优化**：原计划自研 ~60%，调整为 ~30%。主要自研集中在四层语义修复核心逻辑和通道封装胶水。
> **Level 2锚点映射说明**：主选span-aligner（最新，专为span映射设计），备选VectorAlign（更简单），精选用AccAlign（AER最低）。若均失效则退化为正则+N-gram自研方案。

## 关键技术方案设计摘要

### 四层语义感知修复算法（Phase 1/2核心）

```
Level 1 - 正则清洗：清理LLM在占位符周围插入的非法空格、换行、标点
         实现：基于占位符格式的反向正则（如 {{_OL_TAG_\d+_}} 周围不允许有空白字符）

Level 2 - 上下文锚点映射：基于span-aligner词对齐 + sentence-transformers语义验证
         在原文中找到占位符前后的"实词"（名/动/形容词）作为锚点，
         在译文中定位对应位置，将占位符插回
         实现：span-aligner的SpanProjector做跨语言span投影，VectorAlign做双向对齐交叉验证
         备选：AccAlign（LaBSE微调，AER 16.1% SOTA）或退化至N-gram正则匹配

Level 3 - LLM微调重插：将原句（有占位符的原文）单独发给LLM，要求"仅返回原占位符位置"
         Prompt模板："Restore these placeholders to their exact positions: [原句]"
         实现：调用LiteLLM统一接口，选择专用小模型（gpt-4o-mini），仅返回带占位符的句子

Level 4 - 安全落点兜底：将占位符合并追加至句末，注入OL_WARN标签
         实现：原文Fallback，标记该段落需要人工复核
```

### LLM语义评估流程（异步离线 + 反馈重试 + 格式保护）

> openevalkit Judge 调用 LLM API 进行评分，采用异步离线模式。**默认及格线：7/10（可配置）**
> **新增：格式保护维度（占位符/变量/转义字符完整性）**

**时序图**：
```
T1 批量翻译阶段
    ├── 原文1 → LiteLLM翻译(第1次) → 候选A
    ├── 原文2 → LiteLLM翻译(第1次) → 候选B
    └── 原文3 → LiteLLM翻译(第1次) → 候选C

T2 批量评分阶段（openevalkit预过滤 → openevalkit.Judge细粒度打分，并行，无阻塞）
    ├── openevalkit.Scorer快速评分(A) → BLEU=0.85 ≥0.7阈值 ✅ → 直接放行
    ├── openevalkit.Scorer快速评分(B) → BLEU=0.42 <0.7阈值 ❌ → 触发openevalkit.Judge细粒度打分
    │   └── openevalkit.Judge打分(B) → 6/10 <7 ❌ → 触发重翻
    └── openevalkit.Scorer快速评分(C) → RegexMatch=Pass ✅ → 直接放行

T3 重翻阶段（仅对openevalkit.Judge标记为不及格的段落，并行）
    └── 原文2 → LiteLLM翻译(第2次) → 候选B'

T4 重新批量评分阶段（openevalkit预过滤 → openevalkit.Judge细粒度打分，并行）
    └── openevalkit.Scorer快速评分(B') → BLEU=0.55 <0.7阈值 ❌ → 触发openevalkit.Judge细粒度打分
        └── openevalkit.Judge打分(B') → 7/10 ≥7 ✅ → 勉强及格，采用

T5 第2次重翻阶段（如T4仍不及格）
    └── 原文2 → LiteLLM翻译(第3次) → 候选B''

T6 最终评分+兜底
    └── openevalkit.Judge打分(B'') → 4/10 <7 ❌
        → 3次均<7，采用最高分版本(B'=7/10)
        → 注入 OL_WARN: Low_Score

T7 格式保护校验（所有放行译文）
    └── FormatPreservationScorer校验占位符/变量/转义字符
        → 发现丢失 → 触发四层语义感知修复
        → 修复失败 → 落点至句末 + OL_WARN: Tag_auto_appended

流水线继续处理下一批，不阻塞
```

**Scorer vs Judge 输出格式说明**：
- **Scorer（快速预过滤）**：返回归一化分数（0-1），如 BLEU、ROUGE、FuzzyMatch；或返回 Pass/Fail，如 RegexMatch、ContainsKeywords、JSONValid
- **Judge（细粒度评估）**：返回 0-10 的 LLM 评估分数，基于 Rubric 的 criteria + weights 聚合
- **阈值配置**：Scorer 默认阈值 0.7（可配置），Judge 默认及格线 7/10（可配置）

**实现要点**：
- 批量翻译/评分阶段，所有原文/译文并行调用LiteLLM/openevalkit，无阻塞
- **并发限制**：批量翻译最多 10 个并发请求（可配置），批量评分最多 5 个并发 Judge 调用（可配置），超出时自动排队
- 重翻决策在**当前批次内串行**：等所有评分返回后，再决定哪些需要重翻（因为必须先知道评分才能决策）
- 不同批次之间互不阻塞：当前批次在重翻时，下一批次可以开始翻译
- openevalkit.Judge支持批量并行评分，实际是同时发起多个LLM请求
- 最多重翻2次，共3次翻译机会
- 3次均<及格线 → 采用最高分 + OL_WARN: Low_Score，绝不阻塞
- **格式保护**：所有放行译文需经过FormatPreservationScorer校验，发现占位符/变量/转义字符丢失时触发四层语义修复

**时序图补充说明**：
- 图中T1→T2→T3→T4→T5→T6是**单个批次**的完整流程
- 下一批次可在上一批次重翻阶段开始新翻译，实现流水线并行

**双核LQA的角色分工**：
```
核1 - 确定性规则QA（regex数字/术语/标签）：
  - 一票否决，发现问题直接打标放行，不重翻

核2 - LLM语义评估（openevalkit.Judge评分 + 反馈重试）：
  - openevalkit.Scorer做规则快速预过滤（Scorer层，快速判断是否及格）
  - openevalkit.Judge做细粒度裁判（Judge层，对openevalkit.Scorer标记为"存疑"的译文打分）
  - 评分<及格线 → 触发重翻（最多2次）
  - 3次均失败 → 最高分+标签

核3 - 格式保护（FormatPreservationScorer）：
  - 所有放行译文必须通过格式保护校验
  - 检测占位符/变量/转义字符完整性
  - 发现丢失触发四层语义修复（Phase 1/2）
  - 修复失败则落点至句末 + OL_WARN: Tag_auto_appended

openevalkit与openevalkit.Judge协作流程：
  1. openevalkit.Scorer 快速评分（如 BLEU=0.85 ≥ 0.7阈值 → 直接放行）
  2. 若 Scorer 评分<阈值 → openevalkit.Judge 细粒度打分（如 6/10 < 7 及格线）
  3. 若 Judge 评分仍<及格线 → 触发重翻流程
  4. 放行前 → FormatPreservationScorer 校验格式完整性

COMET定位（Phase 3b集成）：
  - 作为可选的第三核，提供无参考翻译质量评估
  - 与openevalkit.Judge互补：Judge评估流畅度/准确度，COMET评估语义相似度/MQM错误类型
  - 通过LiteLLM CLI方式调用

**judges替换说明**（v6.3）：
  - judges 0.1.1已于2025-06-25被Databricks归档（Archived: true），不再维护
  - 替换为openevalkit原生Scorer→Judge两层架构，完全兼容LiteLLM
  - openevalkit.Judge支持Rubric自定义（4个criteria：adequacy/fluency/terminology_consistency/format_preservation）
  - 支持EnsembleJudge多模型投票，提升评分稳定性
  - 智能缓存机制避免重复API调用
```

### 占位符ID生成策略

| 场景 | 格式 | 示例 |
|------|------|------|
| MD代码块 | `{{_OL_CODE_{uid}_}}` | `{{_OL_CODE_a1b2c3_}}` |
| MD公式 | `{{_OL_MATH_{uid}_}}` | `{{_OL_MATH_d4e5f6_}}` |
| XLIFF内嵌标签 | `{{_OL_XTAG_{uid}_}}` | `{{_OL_XTAG_g7h8i9_}}` |

- ID生成：基于`hash(content + timestamp + random)`取前8位
- 冲突处理：检测到冲突时追加2位序号（01-99）
- 多语言兼容：ID不包含语言信息，翻译前后ID一致

### TM（翻译记忆库）优先级策略

> 基于 **hypomnema** (TMX 1.4b) 实现，支持流式读写GB级TMX文件

```
1. 精确匹配（100%）：直接复用，不走LLM
2. 模糊匹配（≥85%相似度，基于sentence-transformers语义相似度）：展示候选，用户可指定是否复用
3. 无匹配：走正常翻译流程，翻译后存入TMX

完整流程（含术语约束）：
  a) 翻译时注入术语引擎约束（术语是强制约束，TM是参考）
  b) 翻译后验证术语命中率
  c) 术语未命中 → 打标放行（OL_WARN: Term_miss）→ 存入TMX
```

- 术语引擎 vs TM冲突：以术语引擎为准（术语是强制约束，TM是参考）
- 增量更新：新翻译自动入库TMX，定时全量去重
- 并发安全：多Worker并发写入hypomnema TMX，无数据丢失

Phase 0: 基础设施与双总线基座 + 数据结构设计
📋 Phase 0 执行计划（优化版：数据结构先行 + Mock接口定义）
1. 概述与目标
搭建项目仓库结构，配置CI/CD流水线。
确立双总线基座：MD通道基于markdown-it-py，XLIFF通道基于translate-toolkit，互不干扰。
建立严格的输入格式校验：非 .md 或 .xliff 文件直接拒绝，不尝试任何自动转换。
确立基于配置文件（YAML）的模型池与项目配置规范，建立配置加载与校验基座。
从旧版Localizer提取并重构核心模块，建立依赖图。

**Phase 0 核心新增目标**（工欲善其事必先利其器）：
a) **数据结构设计**：定义贯穿整个翻译流程的核心数据结构（TranslationContext, RepairContext, EvaluationResult），为 Phase 1/2/3 铺路
b) **Mock接口定义**：定义 Level 3 LLM重插 的抽象接口（LLMRestorer），Phase 1/2 使用 Mock 实现，Phase 3a 集成真实 LiteLLM
c) **数据流契约**：明确数据结构在各 Phase 之间的传递关系，确保 Phase 1/2 开发时不依赖不存在的接口

2. 任务分解（优化后）

**任务组A：项目结构与依赖（0.5天）**
- 项目仓库结构初始化（pyproject.toml, src/, tests/）
- poetry 依赖配置（含 transformers 版本锁定）
- CI/CD 流水线配置

**任务组B：双总线基座（0.75天）**
- XLIFF 总线（translate-toolkit）
- MD Token Stream 基座（markdown-it-py）
- 输入格式守卫

**任务组C：数据结构设计（0.5天，新增）**
- TranslationContext：贯穿整个翻译流程的上下文对象
- RepairContext：四层语义修复的上下文（含 original_text）
- EvaluationResult：评估结果数据结构
- 数据结构序列化测试（用于检查点恢复）

**任务组D：Mock接口定义（0.5天，新增）**
- LLMRestorer 抽象接口定义
- MockLLMRestorer 实现（Phase 1/2 使用）
- LiteLLMRestorer 接口预留（Phase 3a 实现）
- Mock 接口契约测试
2. 工具矩阵
| 环节 | 工具 | 职责 | 备注 |
|------|------|------|------|
| 项目结构 | poetry + pyproject.toml | Python包管理、依赖锁定 | 核心基础设施 |
| XLIFF 解析与操作 | translate-toolkit (xliff/xliff2) | XLIFF 1.2/2.0的读写、遍历、修改 | 核心轮子 |
| MD AST 解析与渲染 | markdown-it-py | Markdown Token Stream解析与反向渲染 | 核心轮子 |
| 配置管理 | pydantic + PyYAML | 模型池、术语、提示词等配置的解析与强类型校验 | 核心基础设施 |
| CLI 入口 | typer | 命令行构建 | Phase 4实现 |
| 测试框架 | pytest | 单元测试、集成测试 | |
| 数据结构定义 | 自研（dataclass） | TranslationContext, RepairContext, EvaluationResult | **新增：数据结构设计** |
| LLM Mock接口 | 自研（abc） | LLMRestorer抽象类 + Mock实现 | **新增：Mock接口定义** |
| 依赖冲突检测 | poetry + pip-audit | 版本锁定、冲突检测、漏洞扫描 | |

### 核心数据结构设计（Phase 0 新增）

> 数据结构是 Phase 1/2/3 的共同契约。在 Phase 0 明确定义，避免后续集成时发现接口不匹配。

```python
# src/ol_core/dataclass.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

class ChannelType(Enum):
    MD = "md"
    XLIFF = "xliff"

@dataclass
class TranslationUnit:
    """
    单个翻译单元
    
    注意：source_text 不含占位符（占位符已替换为 {{_OL_TAG_xxx_}} 格式）
    原始占位符信息保存在 shield_map 中
    """
    unit_id: str
    source_text: str                    # 原文（占位符已替换为ID）
    target_text: Optional[str] = None    # 译文
    shield_map: Dict[str, str] = field(default_factory=dict)  # 占位符ID → 原始标记
    metadata: Dict = field(default_factory=dict)

@dataclass
class TranslationContext:
    """
    贯穿整个翻译流程的上下文对象
    
    Phase 0 定义，Phase 1/2/3 使用。
    保存所有翻译所需元数据，特别是 original_full_text（用于 Level 3 LLM重插）。
    
    数据流：
        Phase 0: TranslationContext 创建（仅结构）
        Phase 1/2: TranslationContext.fill_units() 填充 units
        Phase 3a: TranslationContext 作为参数传入评估流程
        Phase 3b: TranslationContext 可序列化存入检查点
    """
    file_path: str                               # 源文件路径
    channel_type: ChannelType                    # MD 或 XLIFF
    original_full_text: str                       # 完整原文（含占位符），用于 Level 3
    units: List[TranslationUnit] = field(default_factory=list)  # 翻译单元列表
    glossary: Dict[str, str] = field(default_factory=dict)       # 术语表
    config: Dict = field(default_factory=dict)                  # 配置快照
    
    def get_unit_by_id(self, unit_id: str) -> Optional[TranslationUnit]:
        """根据 unit_id 获取翻译单元"""
        for unit in self.units:
            if unit.unit_id == unit_id:
                return unit
        return None
    
    def to_json(self) -> dict:
        """序列化（用于检查点恢复）"""
        return {
            "file_path": self.file_path,
            "channel_type": self.channel_type.value,
            "original_full_text": self.original_full_text,
            "units": [
                {
                    "unit_id": u.unit_id,
                    "source_text": u.source_text,
                    "target_text": u.target_text,
                    "shield_map": u.shield_map,
                    "metadata": u.metadata
                }
                for u in self.units
            ],
            "glossary": self.glossary,
            "config": self.config
        }
    
    @classmethod
    def from_json(cls, data: dict) -> "TranslationContext":
        """反序列化（从检查点恢复）"""
        return cls(
            file_path=data["file_path"],
            channel_type=ChannelType(data["channel_type"]),
            original_full_text=data["original_full_text"],
            units=[TranslationUnit(**u) for u in data["units"]],
            glossary=data.get("glossary", {}),
            config=data.get("config", {})
        )

@dataclass
class RepairContext:
    """
    四层语义修复的上下文
    
    Level 1/2/4 仅需 shield_map
    Level 3 需要 original_text（从 TranslationContext.original_full_text 获取）
    """
    unit_id: str
    shield_map: Dict[str, str]               # 占位符ID → 原始标记
    original_text: str                        # Level 3 专用：含占位符的原文
    anchor_words: List[str] = field(default_factory=list)  # Level 2 锚点词
    max_retries: int = 3

@dataclass
class EvaluationResult:
    """
    评估结果
    
    Scorer 评分：归一化分数（0-1），如 BLEU、RegexMatch
    Judge 评分：0-10 的 LLM 评估分数
    """
    unit_id: str
    # Scorer 层（快速预过滤）
    scorer_scores: Dict[str, float] = field(default_factory=dict)
    # Judge 层（细粒度评估）
    judge_scores: Dict[str, float] = field(default_factory=dict)
    # 格式保护
    format_preserved: bool = True
    format_errors: List[str] = field(default_factory=list)
    # 警告
    warnings: List[str] = field(default_factory=list)
    
    @property
    def passed_scorer(self) -> bool:
        """Scorer 预过滤是否通过"""
        # 默认阈值 0.7
        return all(score >= 0.7 for score in self.scorer_scores.values())
    
    @property
    def judge_overall_score(self) -> float:
        """Judge 综合分数（加权平均）"""
        if not self.judge_scores:
            return 0.0
        return sum(self.judge_scores.values()) / len(self.judge_scores)
```

### Mock接口设计（Phase 0 新增）

> Level 3 LLM重插 在 Phase 1/2 是 Mock 状态。Phase 0 定义接口契约，确保 Phase 3a 集成时不破坏已有代码。

```python
# src/ol_core/interfaces.py

from abc import ABC, abstractmethod
from typing import Dict

class LLMRestorer(ABC):
    """
    Level 3 LLM重插的抽象接口
    
    Phase 0: 定义接口
    Phase 1/2: 使用 MockLLMRestorer
    Phase 3a: 使用 LiteLLMRestorer（真实 LiteLLM 调用）
    """
    
    @abstractmethod
    def restore_placeholders(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        """
        在译文中恢复占位符位置
        
        Args:
            translated_text: LLM翻译后的文本（可能丢失占位符）
            original_text: 原始原文（含占位符），用于定位
            shield_map: 占位符ID → 原始标记的映射
            
        Returns:
            占位符已恢复到正确位置的文本
            
        Raises:
            RestoreFailedError: 恢复失败（触发 Level 4 安全落点）
        """
        pass

class MockLLMRestorer(LLMRestorer):
    """
    Phase 1/2 使用的 Mock 实现
    
    简单逻辑：不做任何恢复，直接返回 translated_text
    Level 1/2/4 会处理占位符恢复，此 Mock 仅保证接口存在
    """
    
    def restore_placeholders(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        # Phase 1/2: 占位符恢复依赖 Level 1/2/4
        # 此 Mock 仅保证接口存在，不做实际恢复
        return translated_text

class LiteLLMRestorer(LLMRestorer):
    """
    Phase 3a 真实实现
    
    调用 LiteLLM，使用专用 prompt 恢复占位符位置
    """
    
    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.0):
        self.model = model
        self.temperature = temperature
        
    def restore_placeholders(
        self,
        translated_text: str,
        original_text: str,
        shield_map: Dict[str, str]
    ) -> str:
        """
        真实 LiteLLM 调用示例：
        
        prompt = f"""Restore these placeholders to their exact positions in the translation.
        
Original text with placeholders:
{original_text}

Current translation (placeholders may be missing or moved):
{translated_text}

Placeholders to restore:
{list(shield_map.values())}

Return the translation with all placeholders restored to their correct positions.
Only return the restored translation, nothing else."""

        response = litellm.completion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature
        )
        return response.choices[0].message.content
``` |

### 依赖选型说明（重要）

| 库 | 版本 | 用途 | 冲突说明 |
|---|---|---|---|
| **LiteLLM** | ^1.84.0 | LLM统一路由（翻译+评估） | 内置backoff，不单独安装tenacity |
| **AgentFuse** | ^0.2.2 | 成本优化+语义缓存 | 与LiteLLM Router分工：Router负责Failover，AgentFuse负责成本 |
| **openevalkit** | ^0.1.7 | LLM评估裁判层（Scorer→Judge两层） | 通过LiteLLM接口调用，不独立配置API；Rubric自定义criteria；EnsembleJudge多模型投票 |
| **COMET** | ^2.2.7 | 翻译质量评估 | 自带虚拟环境隔离，Phase 3集成 |
| **hypomnema** | ^0.8 | TMX翻译记忆库 | 流式处理，无依赖冲突 |
| **span-aligner** | ^0.3.2 | 词对齐（主） | 依赖transformers，版本统一锁定 |
| **VectorAlign** | ^0.2.2 | 词对齐（备） | 同上 |
| **sentence-transformers** | ^3.0.0 | 语义相似度 | 统一transformers版本^4.41.0 |

> **版本锁定策略**：所有依赖transformers的库统一使用transformers ^4.41.0，由poetry自动解决依赖。
> **LiteLLM职责边界**：LiteLLM Router负责所有LLM调用（翻译+评估），openevalkit通过LiteLLM接口，不独立管理API Key。

🧪 UTDD - 单元测试驱动（本Phase要写的测试，优化版）

测试交付物:
- tests/test_xliff_bus.py
- tests/test_md_tokenizer.py
- tests/test_dependency_graph.py
- tests/test_input_guard.py
- tests/test_config_loader.py (新增)
- tests/test_dependency_resolver.py (新增)
- tests/test_format_preservation.py (新增)
- **tests/test_translation_context.py (新增，数据结构)**
- **tests/test_repair_context.py (新增，数据结构)**
- **tests/test_llm_restorer_interface.py (新增，Mock接口契约)**

| 核心函数 | 正常输入用例 | 边界值用例 | 异常输入用例 |
|----------|-------------|------------|--------------|
| XLIFF 总线 (基于 translate-toolkit) | | | |
| load_xliff(path) | 加载标准XLIFF 1.2/2.0 | 加载含10000+翻译单元的大文件 | 加载损坏的XML；加载非XLIFF格式文件 |
| iterate_trans_units(xliff_file) | 遍历所有trans-unit | 遍历含内嵌标签<x/>, <bx/>的复杂单元 | 单元source为空；单元ID重复 |
| write_target_back(...) | 写入翻译文本并更新state | 写入含内嵌标签的target | 写入空target；unit_id不存在 |
| MD 基础设施 | | | |
| parse_md_to_tokens(md_text) | 解析标准GFM文档为Token Stream | 解析含Frontmatter、数学公式、脚注的MD | 无效UTF-8编码 |
| 输入守卫 | | | |
| validate_input_format(file_path) | 识别.md和.xliff为合法输入 | 无后缀但内容为MD的文件 | 输入.docx, .json等不支持格式（直接拒绝抛出异常） |
| 配置加载 (新增) | | | |
| load_config(path) | 加载含2个翻译+2个质检模型的合法YAML | 配置中仅1个翻译模型(降级为无备份模式) | 配置文件缺失；模型列表为空；API Key格式错误（硬性拦截） |
| 依赖解析 (新增) | | | |
| resolve_dependencies() | poetry install成功，无冲突 | 跨版本依赖冲突 | transformers版本冲突；LiteLLM与tenacity冲突；关键库缺失 |
| 数据结构 (新增) | | | |
| TranslationContext.to_json() | 序列化为dict | 包含大量units的序列化 | 空units；特殊字符转义 |
| TranslationContext.from_json() | 从dict反序列化 | 正常反序列化 | 损坏的JSON；字段缺失 |
| RepairContext创建 | 包含original_text | original_text为空 | - |
| Mock接口 (新增) | | | |
| MockLLMRestorer.restore_placeholders() | 返回translated_text不变 | - | - |
| LLMRestorer接口契约 | 抽象方法签名正确 | 实现类继承正确 | 实现类缺少方法 |
| 格式保护校验 (新增) | | | |
| FormatPreservationScorer | 占位符完整保留 | 占位符被修改（如 {{name}} → {name}）；转义字符保留（\n） | 占位符丢失；格式错误；ID冲突 |
✅ ATDD - 验收测试驱动（本Phase的验收标准）
正常流程验收标准: translate-toolkit 成功加载并操作所有标准XLIFF样本（覆盖率100%）。markdown-it-py 成功解析所有标准GFM样本，无崩溃。依赖图构建时间 ≤ 100ms（100文件项目）。配置文件加载且 Pydantic 校验通过。
❌ 异常流程验收标准: XLIFF加载失败时，必须抛出明确的异常。MD解析遇到严重语法错误时优雅降级，记录警告，不崩溃。遇到不支持的格式或致命配置缺失，直接抛出硬性错误拦截。
🔲 边界条件验收标准: 单个XLIFF文件翻译单元上限为100,000（超出触发警告并建议拆分）。单个MD文件Token上限为500,000（超出自动拆分为多个子任务并行处理，结果合并后输出）。
🔧 依赖验证标准 (Phase 0 优化版):
- [ ] `poetry install --no-interaction` 成功，无版本冲突警告
- [ ] `poetry check --no-isolation` 通过，依赖图无断裂
- [ ] **基础功能验证通过**：
    - `LiteLLM` - `litellm.completion(model="openai/gpt-4o-mini", messages=[{"role": "user", "content": "test"}], timeout=10)` 连通性测试
    - `translate-toolkit` - `xliff2json()` 解析标准XLIFF 1.2样本
    - `markdown-it-py` - `markdown_it.parse()` 标准GFM样本
    - `span-aligner` - `import span_aligner` 成功加载
    - `hypomnema` - `hypomnema.TMXFile` 打开标准TMX样本
    - `openevalkit` - `from openevalkit import evaluate` 成功导入
- [ ] **数据结构接口验证**：
    - `TranslationContext` 可序列化/反序列化（JSON格式）
    - `RepairContext` 包含 original_text 字段
    - `LLMRestorer` 抽象类可被子类继承
- [ ] 无已知漏洞（`pip-audit` 无高危漏洞）
- [ ] Python >= 3.10 环境验证通过
🎯 BDD - 行为驱动场景
场景1：XLIFF总线基础验证：Given 用户提供标准manual.xlf -> When 系统加载 -> Then 成功遍历并读写。
场景2：非法格式强力拦截：Given 用户误传manual.docx -> When 校验 -> Then 立即阻断报错，提示使用OPP转换。
🔄 TDD - 测试驱动开发循环
🔴 红(测试失败) -> 🟢 绿(编写代码通过) -> 🔄 重构(优化结构)

Phase 1: MD原生通道（Token Stream重建 + 极致标记保护 + 语义感知修复）
📋 Phase 1 执行计划
1. 概述与目标
废除AST原位覆写引擎，实现基于 Token Stream 的安全提取-翻译-重建流程。
实现极致的MD特殊标记保护，确保100%不被LLM篡改。
核心升级：实现占位符丢失时的四层递进式语义感知修复机制（正则清洗 -> 上下文锚点映射 -> LLM微调重插 -> 安全落点兜底），消除人工干预，杜绝粗暴强制对齐破坏语法。
实现针对MD通道的浅层文字完整性校验与自动风险打标。

> **与M2的并行关系**：M1与M2分别开发MD通道和XLIFF通道，两者在代码层面完全独立，可并行开发。
> **与M3a的依赖关系**：Level 3（LLM微调重插）依赖LiteLLM接口。M1/M2开发阶段使用Mock LLM接口，Level 3的完整实现集成于M3a。
> **开发策略**：M1/M2先完成Level 1/2/4的完整实现，Level 3仅做接口定义+Mock，等M3a的LiteLLM基座完成后集成。

2. 工具矩阵
| 环节 | 工具 | 职责 |
|------|------|------|
| MD 解析与渲染 | markdown-it-py | Token Stream解析与反向渲染 |
| 标记保护/还原/修复 | 自研（基于Token类型+正则 + Python-Markdown HtmlStash参考） | 识别、替换、还原；LLM丢失占位符时调用span-aligner做锚点映射辅助定位 |
| LLM 弹性调用 | LiteLLM (复用Phase 3a基座) | 统一接管翻译/修复LLM调用，处理模型退避与降级 |
| 锚点映射辅助 | **span-aligner** (+VectorAlign备选) | Level 2语义修复时，SpanProjector跨语言投影定位占位符在译文中的位置 |
| 文字完整性 | regex + Token比对 | 数字/专有名词/长度比对 |
🧪 UTDD - 单元测试驱动
测试交付物: tests/test_md_extractor.py, tests/test_md_protector.py, tests/test_md_rebuilder.py, tests/test_md_text_integrity.py, tests/test_md_auto_repair.py (核心重构), tests/test_md_format_preservation.py (新增)

| 核心函数 | 正常输入用例 | 边界值用例 | 异常输入用例 |
|----------|-------------|------------|--------------|
| extract_translatable_tokens(tokens) | 提取标题、段落等文本Token | 提取链接alt文本（跳过URL） | 遇到未识别Token类型时跳过并警告 |
| shield_special_tokens(md_text) | 屏蔽代码块、公式等 | 屏蔽嵌套标记；屏蔽自定义容器 | 占位符ID冲突；标记识别遗漏 |
| unshield_special_tokens(translated_text, shield_map) | 还原占位符为原标记 | LLM在占位符前后添加空格或标点 | LLM改变了占位符结构 |
| auto_repair_lost_shields(translated_text, shield_map, original_text) | (重构) LLM丢失占位符 | LLM调换了占位符语序 | LLM丢失占位符（触发4级语义感知修复：1.正则清洗 2.上下文锚点映射 3.LLM微调重插 4.句末安全落点） |

**调用链实现**：
```python
def auto_repair_lost_shields(translated_text, shield_map, original_text):
    """
    四层递进式语义感知修复

    Args:
        translated_text: LLM翻译后的文本（可能丢失占位符）
        shield_map: 占位符ID与原始标记的映射关系
        original_text: 原始原文（含占位符），用于Level 3 LLM重插
    """
    # Level 1 - 正则清洗
    cleaned = level1_regex_clean(translated_text, shield_map)
    if is_complete(cleaned, shield_map):
        return cleaned

    # Level 2 - span-aligner锚点映射
    aligned = level2_span_align(cleaned, shield_map)
    if is_complete(aligned, shield_map):
        return aligned

    # Level 3 - LLM微调重插（需LiteLLM，M3a完成后集成）
    # original_text 参数用于LLM理解占位符的上下文位置
    restored = level3_llm_restore(aligned, original_text)  # Mock during M1/M2
    if is_complete(restored, shield_map):
        return restored

    # Level 4 - 安全落点兜底
    return level4_safe_fallback(restored, shield_map)
```
| rebuild_md_from_translated_tokens(...) | 用译文Token替换原Token并渲染 | 译文包含换行符，需适配原Token结构 | Token树结构不匹配 |
| 文字完整性校验 | 正常 | 长度异常；关键名词丢失（打标放行） | - |
✅ ATDD - 验收测试驱动
🛡️ MD 原生格式保护硬性标准: 标记完整率100%；结构无损率100%；链接/图片安全。
🛡️ 文字质量保护验收标准: 防漏译（偏差≤5%）；防异常扩写（长度比超出[0.3, 3.0]自动重试，可配置）；数字一致性。
❌ 异常流程验收标准 (核心修改):
LLM吞噬占位符：触发4级语义感知修复（1. 正则清洗非法空格 -> 2. 基于源文前后实词的上下文锚点映射插回 -> 3. 调用LLM微调重插 -> 4. 修复失败则降级至句末安全落点）。
绝不允许基于源文索引的粗暴强制对齐插入，杜绝目标语言语法破坏。
降级落点时：该段落保留译文，丢失的占位符统一追加至句末，并在MD中自动注入 <!-- OL_WARN: Tag auto-appended at sentence end -->，流水线不中断。
🎯 BDD - 行为驱动场景
场景1：AI技术博客MD文件翻译(含占位符丢失的语义修复)：Given 包含代码块的blog.md -> When 翻译且LLM丢失了代码块占位符 -> Then 自动触发语义修复（优先锚点映射/LLM重插）；若仍失败则将占位符安全落点于句末并加HTML注释警告，保证译文语法通畅，程序继续运行不中断。
场景1a（Level 2锚点映射专项）：Given 包含嵌套标记的复杂MD文件 -> When LLM丢失占位符且Level 1正则清洗失败 -> Then span-aligner基于词对齐定位锚点实词，在译文中找到对应位置插入占位符；若锚点映射仍失败则进入Level 3/L4修复流程。

Phase 2: XLIFF通道（translate-toolkit操作 + 内嵌标签绝对保护 + 语义感知修复）
📋 Phase 2 执行计划
1. 概述与目标
实现基于translate-toolkit的XLIFF翻译解析与写入。
实现XLIFF内嵌标签的绝对保护及语义感知修复机制。
核心原则：OL只做"XLIFF的读写与翻译"，绝不涉及格式回转。

> **与M1的并行关系**：M1与M2分别开发MD通道和XLIFF通道，两者在代码层面完全独立，可并行开发。
> **与M3a的依赖关系**：Level 3（LLM微调重插）依赖LiteLLM接口。M1/M2开发阶段使用Mock LLM接口，Level 3的完整实现集成于M3a。

2. 工具矩阵
| 环节 | 工具 | 职责 |
|------|------|------|
| XLIFF解析与写入 | translate-toolkit | XLIFF节点解析、翻译写入、状态更新 |
| 内嵌标签保护/修复 | 自研（基于translate-toolkit API + span-aligner锚点映射） | 提取、保护、还原、语义感知自动修复XLIFF内嵌标签 |
| LLM 弹性调用 | **LiteLLM** (复用Phase 3a基座) | 统一接管翻译/修复LLM调用，处理模型退避与降级 |
| 锚点映射辅助 | **span-aligner** (+VectorAlign备选) | Level 2语义修复时，跨语言投影辅助定位标签在译文中的位置 |
🧪 UTDD - 单元测试驱动
测试交付物: tests/test_xliff_translator.py, tests/test_xliff_tag_protector.py, tests/test_xliff_tag_autorepair.py (核心重构), tests/test_xliff_format_preservation.py (新增)

| 核心函数 | 正常输入用例 | 边界值用例 | 异常输入用例 |
|----------|-------------|------------|--------------|
| translate_xliff_unit(...) | 翻译单个trans-unit | 翻译含内嵌标签的source | LLM API失败；翻译结果为空 |
| extract_xliff_tags(source_xml) | 提取<x/>, <bx/>等标签 | 提取嵌套标签 | 标签语法错误 |
| restore_xliff_tags(target_text, tag_map) | 将占位符还原为标签 | 连续多个标签 | LLM丢失了占位符标签 |
| auto_repair_xliff_tags(target_text, tag_map, original_text) | (重构) LLM调换了标签顺序 | 锚点映射修复标签位置 | LLM丢失占位符（触发语义感知修复：锚点映射 -> LLM重插 -> 句末安全落点） |

**调用链实现**：同Phase 1，使用相同四层修复逻辑（Level 3在M3a完成后集成）。
✅ ATDD - 验收测试驱动
正常流程验收标准: XLIFF翻译后结构100%有效；内嵌标签100%保留。
❌ 异常流程验收标准 (核心修改):
内嵌标签丢失：触发多级语义感知修复（锚点映射 -> LLM重插）。
修复失败：绝不粗暴强插，而是将标签安全落点于单元末尾，该单元状态标记为 needs-adaptation，添加 <note from="OL">Warning: Tag auto-appended at end, manual check needed</note>，流水线不中断。
🎯 BDD - 行为驱动场景
场景1：XLIFF纯翻译验证(含标签丢失安全降级)：Given manual.xlf -> When 翻译且某单元标签丢失且语义修复失败 -> Then 该单元标签落点于末尾，state设为需人工调整，其他单元正常翻译，全流程跑完输出XLIFF。

Phase 3: 双通道汇聚 + 弹性模型池 + 并发基座 (Phase 3a)
Phase 3a: 前置路由 + 弹性模型池 + 并发调度基座
📋 Phase 3a 执行计划
1. 概述与目标
实现前置智能路由引擎（严格后缀校验）。
核心新增：实现 LLM Provider 级别的弹性模型池架构。翻译与质检分离，各配置主备模型（≥2个），遇限流、宕机、Token耗尽自动退避至顺位模型。
实现并发调度引擎基座（速率限制、流量控制），**含检查点机制**（断点续传的基础），TM共享在Phase 3b实现。

> **Phase 3a 评估职责说明**：openevalkit（Scorer→Judge两层）在 Phase 3a 完整可用，支持批量评分+反馈重试+Best-of-N。Phase 3b 仅增加 COMET 作为可选第三核。

2. 工具矩阵
| 环节 | 工具 | 职责 | 备注 |
|------|------|------|------|
| 智能路由 | 自研（基于文件后缀强校验） | 格式识别与通道分发，非法格式拦截 | |
| 弹性模型池 | **LiteLLM** + AgentFuse | 多模型优先级路由、异常拦截、自动 Failover；LiteLLM Router做核心调度，AgentFuse做成本优化 | 核心轮子 |
| 确定性规则QA | regex + tbx2json + 自研比对 | 数字、术语、标签、长度校验 | |
| 术语强制引擎 | tbx2json / csv | 加载术语表，注入Prompt，验证命中 | |
| LLM语义评估与仲裁 | **openevalkit.Scorer** + **openevalkit.Judge** | Scorer做规则快速过滤，Judge做细粒度裁判；Rubric自定义4个criteria（adequacy/fluency/terminology/format_preservation）；EnsembleJudge多模型投票提升稳定性 | 核心轮子 |
| 翻译记忆库 | **hypomnema** (TMX) | 翻译对存储与TMX格式支持、模糊匹配 | Phase 3b实现 |
| 并发调度 | asyncio / concurrent.futures | 并发控制、速率限制、重试 | |
| 断点续传 | 自研（JSON/SQLite检查点） | 进度与状态保存与恢复 | Phase 3b实现 |	
```yaml
llm_pool:
  translation:
    - provider: openai
      model: gpt-4-turbo
      priority: 1
      api_key: ${OPENAI_API_KEY}
    - provider: anthropic
      model: claude-3-sonnet
      priority: 2
      api_key: ${ANTHROPIC_API_KEY}
  judging:
    - provider: openai
      model: gpt-4o-mini
      priority: 1
    - provider: deepseek
      model: deepseek-chat
      priority: 2
```
🧪 UTDD - 单元测试驱动
测试交付物: tests/test_channel_router.py, tests/test_model_pool_failover.py (新增), tests/test_deterministic_qa.py, tests/test_glossary_enforcer.py, tests/test_llm_judge_and_arbitrage.py, tests/test_concurrent_engine.py, tests/test_checkpoint_recovery.py

| 核心函数 | 正常输入用例 | 边界值用例 | 异常输入用例 |
|----------|-------------|------------|--------------|
| 前置智能路由引擎 | MD/XLIFF正确路由 | 极大文档 | 输入DOCX等（阻断异常） |
| 弹性模型池调用 (新增) | | | |
| call_llm_with_pool(task, prompt) | 优先使用1号模型成功返回 | 1号模型限流(429)，自动切至2号模型 | 1号Auth失败；2号也宕机（抛出明确异常，该单元降级处理） |
| judge_and_arbitrate(candidates) | 高分直接通过 | 多次重试得分均低 | 全部重试低于及格线（选历史最高分+打标放行） |
✅ ATDD - 验收测试驱动
前置路由: 准确率100%，拦截率100%。
并发调度: 吞吐量提升≥5倍。
弹性模型池验收标准: 主模型抛出 429/5xx/Auth 错误时，必须在 3 秒内无缝切换至备用模型，流水线零感知、零中断。若全量模型不可用，单个翻译单元/段落必须安全降级（原文落点+严重警告标签），不影响后续单元。
LQA异步评估验收标准:
  - 批量翻译阶段：所有原文并行调用LiteLLM翻译，无阻塞
  - 批量评分阶段：openevalkit.Scorer快速预过滤 → openevalkit.Judge细粒度打分，无阻塞
  - 重翻机制：openevalkit.Judge评分<及格线时最多重翻2次（共3次)，每次重翻后重新评分
  - Fallback兜底：3次均<及格线时采用最高分版本，注入OL_WARN: Low_Score
  - openevalkit.Judge角色说明：评分低触发的是"重试"（不是"否决"），重试3次仍低才打标签放行
  - 评分稳定性校验：若同一译文连续评分波动>2分，取中位数或再做一次确认
  - 术语命中率≥98%（未命中则重试，仍不中则打标放行）
  - 标签100%保留（丢失触发语义修复/安全降级）
  - 格式保护校验：所有放行译文需经过FormatPreservationScorer校验占位符/变量/转义字符完整性
  - COMET集成（Phase 3b）：作为可选第三核，提供无参考质量评估，与openevalkit.Judge互补
🎯 BDD - 行为驱动场景
场景1：异构合法文档的自动化路由翻译：Given 包含MD和XLF的项目 -> When 运行 -> Then 自动路由，统一受LQA评估及自动降级打标，顺利输出结果。
场景2：主模型宕机的无缝自愈：Given 翻译任务开始且OpenAI为主模型 -> When 发生429限流且重试耗尽 -> Then 自动切换至Claude备用模型继续当前段落翻译，并在离线报告中记录Fallback事件。
场景3：LLM评估低分的自动闭环：Given 某段落初翻流畅度2/10 -> When openevalkit.Judge评估 -> Then 自动重翻（第2次），第2次仍不及格则重翻（第3次），3次均不及格则采用最高分版本并打上 OL_WARN: Low_Score 标签放行，绝不阻塞等待人工。

Phase 3b: 双核LQA防线 + TM共享 + 断点续传 (Phase 3a完成后)
📋 Phase 3b 执行计划
1. 概述与目标
基于Phase 3a建立的并发基座，实现双核LQA防线的完整闭环（openevalkit.Judge+COMET双核评估）。
实现翻译记忆库（TM）共享机制，多文件/多语言项目可复用翻译记忆。
实现断点续传，确保大规模翻译任务可恢复。

> **TM与断点续传的关系**：
> - 检查点（checkpoint）保存：已翻译单元数、TM库路径、配置快照
> - 断点续传时：先加载最新检查点 → 再加载TM库 → 从检查点记录的进度继续翻译
> - TM增量更新不受断点续传影响：新翻译自动入库，不影响已保存的检查点
> - 去重策略：每次启动时对TM做一次全量去重（清除重复翻译对）
> - 检查点文件格式：`{input_file}.ol_checkpoint.json`，存储位置与源文件同目录

**检查点文件结构**：
```json
{
  "version": "1.0",
  "file_hash": "sha256_of_source_file",
  "processed_units": ["unit_id_1", "unit_id_2", ...],
  "timestamp": "2026-05-15T10:30:00Z",
  "tmx_path": "./backup/tmx/",
  "config_snapshot": {...},
  "total_units": 10000,
  "completed_units": 5000
}
```

**断点恢复冲突处理**：
- 若源文件hash与checkpoint不匹配 → 警告 + 拒绝自动恢复
- 用户可选择：`ol resume --force`（重新开始）或 `ol resume --merge`（保留已完成翻译）
- 若checkpoint为空 → 冷启动，正常翻译流程

2. 工具矩阵
| 环节 | 工具 | 职责 | 备注 |
|------|------|------|------|
| 确定性规则QA | regex + tbx2json + 自研比对 | 数字、术语、标签、长度校验 | Phase 3a已建立基座 |
| 术语强制引擎 | tbx2json / csv | 加载术语表，注入Prompt，验证命中 | Phase 3a已建立基座 |
| LLM语义评估与仲裁 | openevalkit.Judge + COMET | 准确度/流畅度打分、反馈重试、版本择优、格式保护Scorer | Phase 3a已建立基座 |
| 翻译记忆库 | hypomnema (TMX) | 翻译对存储与TMX格式支持、模糊匹配 | 新增TM共享 |
| 断点续传 | 自研（JSON/SQLite检查点） | 进度与状态保存与恢复 | 新增 |

🧪 UTDD - 单元测试驱动
测试交付物: tests/test_tm_sharing.py (新增), tests/test_tm_consistency.py (新增), tests/test_checkpoint_recovery.py

| 核心函数 | 正常输入用例 | 边界值用例 | 异常输入用例 |
|----------|-------------|------------|--------------|
| TM共享机制 | 多Worker写入同一TM库 | 高并发写入冲突 | TM库损坏；网络存储中断 |
| TM优先级冲突 | 术语引擎命中 vs TM冲突时以术语为准 | TM片段与当前上下文不匹配 | - |
| 断点续传 | 中断后从检查点恢复 | 检查点损坏/版本不匹配 | 检查点为空（冷启动） |
✅ ATDD - 验收测试驱动
TM验收标准：多Worker并发写入1000条翻译对，无数据丢失，无冲突覆盖。
断点续传验收标准：模拟断电场景，重启后从上次检查点恢复，恢复时间<5秒，数据零丢失。
LQA双核完整验收标准：
  - 批量评分：所有翻译候选并行调用openevalkit.Judge评分，异步无阻塞
  - 重翻兜底：3次均<及格线时采用最高分+OL_WARN: Low_Score，绝不阻塞
  - 术语命中率≥98%（未命中则重试，仍不中则打标放行）
  - 格式保护：所有放行译文需经过FormatPreservationScorer校验
🎯 BDD - 行为驱动场景
场景1：大规模项目断点续传：Given 10000个XLIFF单元的翻译任务 -> When 在第5000单元时意外中断 -> Then 重启后从第5001单元继续，输出文件与连续完成完全一致。
场景2：多语言TM共享：Given 中文->英文翻译后建立TM -> When 同一项目中文->日文翻译 -> Then TM中的双语对齐片段自动复用，提升翻译一致性。

Phase 4: 用户体验 + 端到端集成 + 增强型离线报告 + PyPI发布
📋 Phase 4 执行计划
1. 概述与目标
完善CLI用户体验，提供纯粹的批处理翻译引擎命令。
实现 OL 端到端集成测试，确保双通道极致鲁棒与零阻塞。
废除交互式审核入口，实现可操作的双向溯源离线报告与待审校文件提取。
PyPI发布准备。
2. 工具矩阵
| 环节 | 工具 | 职责 | 备注 |
|------|------|------|------|
| CLI封装 | typer | 统一命令入口 | |
| 端到端测试 | pytest | 真实环境全流程测试 | |
| 报告生成 | Jinja2 / 自研 | LQA离线报告HTML/CSV输出（含精准溯源与模型消耗看板） | 增强功能 |
| 待审校提取 | 自研 | 抽取带 OL_WARN 的段落生成精校文件 | 新增 |
🧪 UTDD - 单元测试驱动
测试交付物: tests/test_e2e_md_pipeline.py, tests/test_e2e_xliff_pipeline.py, tests/test_lqa_report.py, tests/test_review_extractor.py (新增)

| 核心函数 | 正常输入用例 | 边界值用例 | 异常输入用例 |
|----------|-------------|------------|--------------|
| 端到端流水线 | MD+XLIFF混合项目全流程 | 纯MD/纯XLIFF项目 | 包含非法格式文件(跳过报错)；部分翻译失败降级(安全落点打标放行) |
| 增强型报告生成 | 生成带单元ID/行号溯源的报告 | 报告中包含模型Fallback记录 | - |
| 待审校提取 (新增) | 提取所有含 OL_WARN 的XLIFF单元生成新XLIFF | 整个文件无警告(生成空文件) | - |

✅ ATDD - 验收测试驱动
正常流程验收标准: MD/XLIFF通道端到端测试通过率100%（样本全部跑通无崩溃中断）。
命令行体验: 产出的文件包含完整的翻译和明确的标签溯源（含安全落点警告），可交由外部工具/人工离线复核。
增强型报告验收标准: 离线 HTML/CSV 报告必须支持双向溯源（MD报出具体 Heading/段落，XLIFF报出 trans-unit id），并包含“模型池调用统计与成本看板”。
待审校提取验收标准: 支持通过 CLI 参数 --extract-warnings，自动将带警告标签的段落抽离为独立的轻量级 MD/XLIFF 文件，供人工直接审校。
🎯 BDD - 行为驱动场景
场景1：AI知识库（MD格式）的本地化零干预全流程：Given MD格式Prompt库 -> When 执行本地化 -> Then 代码块100%保护，低质量/标签丢失段落自动降级（语义修复或句末安全落点）并注入警告标签，全量输出结构完好的目标语言MD文件，进程退出码为0（成功）。
场景2：人工精准复核闭环：Given 翻译完成且生成了包含3个 OL_WARN 的XLIFF文件 -> When 运行 ol extract-warnings -> Then 生成仅含这3个单元的 review_only.xliff，人工修改后可直接回写或作为训练数据。

总体风险分析与极致缓解策略 (Auto-Pilot 弹性池版)
| 风险等级 | 风险描述 | 影响范围 | 缓解策略 |
|----------|----------|----------|----------|
| 极高 | LLM吞噬/篡改MD占位符或XLIFF标签 | 翻译后格式损坏 | 强制标签保护；四层语义感知修复引擎（span-aligner锚点映射/LiteLLM重插/句末落点）；绝不容许基于源文索引的粗暴硬插，杜绝语法破坏；落点失败则原文Fallback+严重警告标签 |
| 极高 | MD原生结构在翻译中破损 | 输出MD不可用 | 废除AST原位覆写；采用Token Stream重建保证语法合法；结构比对校验 |
| 高 | LLM Provider 宕机/限流/Token耗尽 | 流水线阻塞，翻译任务整体失败 | 弹性模型池设计：LiteLLM Router负责Failover；API异常自动切换至顺位模型；全量模型不可用时单段落降级放行，绝不阻塞全局 |
| 高 | LLM语义评估不稳定/得分过低 | 产物质量低下 | openevalkit.Judge裁判层+openevalkit.Scorer规则过滤；带反馈自动重试(最多3次) + Best-of-N仲裁择优；评分稳定性检测（波动>2分则重新评估）；低分自动打标放行；**新增：自适应阈值机制（基于批次分数分布动态调整）** |
| 高 | **transformers版本冲突** | 依赖安装失败 | Phase 0统一锁定transformers ^4.41.0，poetry自动解决依赖 |
| 中 | 确定性规则QA假阳性 | 正常翻译被降级 | 合理设置容错区间；提供白名单豁免；打标放行而非阻塞，通过离线报告人工复核 |
| 中 | 翻译一致性差 | 产物质量低下 | TM优先策略（hypomnema TMX）；术语强制引擎；一致性校验 |
| 中 | AgentFuse与LiteLLM retry逻辑重叠 | 指数退避冲突 | 明确分工：LiteLLM负责retry，AgentFuse仅做成本+缓存 |
*注：原计划中极高/高风险的"OPP回转排版严重错乱"、"OPP进程崩溃"因架构调整已彻底消除。新增"LLM Provider宕机"风险已被弹性模型池机制降级。*

## 依赖管理风险与缓解

| 风险等级 | 风险描述 | 影响范围 | 缓解策略 |
|----------|----------|----------|----------|
| 高 | transformers版本冲突（COMET/span-aligner/sentence-transformers） | 安装失败或运行时crash | Phase 0统一锁定transformers ^4.41.0，由poetry自动解决 |
| 中 | LiteLLM内置backoff与AgentFuse tenacity重叠 | retry逻辑冲突，指数退避失效 | 明确分工：LiteLLM负责retry，AgentFuse仅做成本+缓存 |
| 中 | openevalkit.Judge/openevalkit.Scorer独立调用LLM | API Key管理 | 统一通过LiteLLM Router调用，API Key集中管理 |
| 低 | COMET独立虚拟环境增加复杂度 | 额外安装步骤 | Phase 3集成时统一通过LiteLLM调用COMET CLI |

里程碑总览与交付物
| 里程碑 | 阶段 | 核心交付物 | 预计工期 | 并行说明 |
|---------|------|----------|----------|----------|
| M0 | Phase 0：基础设施与双总线 + 数据结构 + Mock接口 | 项目仓库、CI/CD、依赖清单+冲突检测、XLIFF总线、MD基础、格式守卫、配置加载基座、**TranslationContext/RepairContext数据结构、LLMRestorer Mock接口** | 2.5 天 | 起点（含数据结构设计 + Mock接口定义） |
| M1 | Phase 1：MD原生通道 | Token Stream重建引擎、标记绝对保护与语义感知修复、MD文字质检、**FormatPreservationScorer** | 3 天 | 可与M2并行 |
| M2 | Phase 2：XLIFF通道 | translate-toolkit集成、内嵌标签绝对保护与语义感知修复、**FormatPreservationScorer** | 2 天 | 可与M1并行 |
| M3a | Phase 3a：路由+模型池+并发基座 | 格式路由、弹性模型池、并发调度基座、**LiteLLMRestorer真实实现** | 1.5 天 | M1/M2完成后开始 |
| M3b | Phase 3b：LQA+TM+断点续传 | 双核LQA、TM共享机制、断点续传 | 1.5 天 | M3a完成后开始 |
| M4 | Phase 4：用户体验与发布 | 翻译流水线CLI、端到端测试、增强型双向溯源报告/待审校提取 (废除交互)、PyPI包 | 1.5 天 | 收尾 |

> **并行策略**：M1与M2完全独立，可同步开发。M3依赖M1+M2完成，M3a与M3b串行但每阶段仅1.5天。
> **优化后总工期**：2.5(M0) + 3(M1||M2并行) + 1.5(M3a) + 1.5(M3b) + 1.5(M4) = 10 天
> **原工期**：11天（串行执行）

测试文件明细：
- Phase 0: 10个 (xliff_bus, md_tokenizer, dependency_graph, input_guard, config_loader, dependency_resolver, format_preservation, translation_context, repair_context, llm_restorer_interface)
- Phase 1: 6个 (md_extractor, md_protector, md_rebuilder, md_text_integrity, md_auto_repair, md_format_preservation)
- Phase 2: 4个 (xliff_translator, xliff_tag_protector, xliff_tag_autorepair, xliff_format_preservation)
- Phase 3a: 7个 (channel_router, model_pool_failover, deterministic_qa, glossary_enforcer, llm_judge_and_arbitrate, concurrent_engine, checkpoint_recovery)
- Phase 3b: 3个 (tm_sharing, tm_consistency, checkpoint_recovery)
- Phase 4: 4个 (e2e_md_pipeline, e2e_xliff_pipeline, lqa_report, review_extractor)
- **总计约 34 个**（新增6个：Phase 0的3个数据结构+Mock接口测试，Phase 1/2的FormatPreservation测试）
测试覆盖率目标：核心路径 ≥ 95%