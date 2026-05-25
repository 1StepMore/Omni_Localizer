# OPP-OLL API 契约文档

> 本文档定义 OPP (Omni Pre-Processor) 与 OLL (Omni Localizer) 之间的接口契约。
> 两个模块独立部署，通过 REST API 通信。

---

## 1. 架构概述

```
┌─────────────┐         ┌─────────────┐
│   OPP       │   API   │   OLL       │
│  (Pre-Pro)  │◄───────►│ (Localizer) │
└─────────────┘         └─────────────┘
     │                       │
     ▼                       ▼
  提取内容               翻译执行
  分块处理               质量评估
  术语提取               术语一致性
```

**部署关系**：
- OPP 和 OLL 独立部署
- OLL 按需调用 OPP API
- OPP 不依赖 OLL（可单独使用）

---

## 2. API 基础信息

| 项目 | 值 |
|------|-----|
| 基础 URL | `http://{OPP_HOST}:{OPP_PORT}`（可配置） |
| API 版本 | `v1` |
| 内容类型 | `application/json` |
| 字符编码 | UTF-8 |

---

## 3. API 端点

### 3.1 分块接口

**端点**：`POST /api/v1/chunk`

**描述**：对已提取的文档内容进行分块

**请求体**：
```json
{
  "source_text": "string",          // 完整原文（必填）
  "source_lang": "string",          // 源语言代码，如 "zh", "en"（必填）
  "format_type": "string",          // "epub", "pdf", "docx", "html", "plain"（必填）
  "target_size": 50000,             // 单块目标字符数（默认 50000）
  "strategy": "smart",              // "smart" | "chapter_first" | "paragraph"（默认 smart）
  "metadata": {                    // 可选的文档元信息
    "file_name": "string",
    "page_count": 100,
    "source_md5": "abc123..."
  }
}
```

**响应体**：
```json
{
  "success": true,
  "data": {
    "chunks": [
      {
        "index": 0,
        "text": "string",                      // chunk 文本
        "chapter_ref": "第一章" | null,          // 章节名（无章节时为 null）
        "start_char": 0,
        "end_char": 27070,
        "char_count": 27070,
        "paragraph_count": 45,
        "source_md5": "abc123...",
        "quality_score": null                   // 可后续通过 /chunk-quality 评估
      }
    ],
    "total_chars": 650000,
    "estimated_chunks": 13,
    "chunk_strategy": "smart",
    "metadata": {
      "source_lang": "zh",
      "format_type": "epub",
      "page_count": 100
    }
  },
  "error": null
}
```

**错误响应**：
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "INVALID_FORMAT_TYPE",
    "message": "Unsupported format_type: xxx",
    "details": {}
  }
}
```

---

### 3.2 质量评估接口

**端点**：`POST /api/v1/chunk-quality`

**描述**：对已分块的内容进行质量评估

**请求体**：
```json
{
  "chunks": [
    {
      "index": 0,
      "text": "string",
      "chapter_ref": "第一章",
      "char_count": 27070,
      "paragraph_count": 45
    }
  ],
  "source_lang": "zh",
  "target_lang": "en"
}
```

**响应体**：
```json
{
  "success": true,
  "data": {
    "evaluations": [
      {
        "chunk_index": 0,
        "passed": true,
        "scores": {
          "sentence_integrity": 0.95,      // 句子完整性 (0-1)
          "boundary_accuracy": 0.88,        // 边界准确率 (0-1)
          "term_density": 0.72,              // 术语密度 (0-1)
          "size_balance": 0.81              // 大小均匀度 (0-1)
        },
        "weighted_score": 0.86,
        "issues": []                         // 发现的问题列表
      }
    ],
    "summary": {
      "total_chunks": 13,
      "passed_chunks": 11,
      "failed_chunks": 2,
      "average_score": 0.84
    }
  },
  "error": null
}
```

---

### 3.3 术语提取接口

**端点**：`POST /api/v1/glossary`

**描述**：从文档中提取高频术语

**请求体**：
```json
{
  "source_text": "string",           // 完整原文（必填）
  "source_lang": "zh",               // 源语言代码（必填）
  "top_k": 50,                       // 返回术语数量（默认 50）
  "min_frequency": 2                 // 最小出现频率（默认 2）
}
```

**响应体**：
```json
{
  "success": true,
  "data": {
    "terms": [
      {
        "source": "牛顿",                        // 源语言术语
        "translation": "",                       // 译文（待填充）
        "context": "牛顿在1687年发表了《自然哲学的数学原理》...",  // 上下文
        "frequency": 15,                         // 出现频率
        "relevance_score": 3.0,                  // 关联分数
        "confidence": 1.0,                       // 置信度
        "position": [1234, 1236]                 // 在原文中的位置 [start, end]
      }
    ],
    "metadata": {
      "source_lang": "zh",
      "total_terms_extracted": 50,
      "extraction_method": "regex+jieba"         // 提取方法
    }
  },
  "error": null
}
```

---

### 3.4 增量翻译检查接口

**端点**：`POST /api/v1/check-incremental`

**描述**：基于 source_md5 检查内容是否变化，避免重复翻译

**请求体**：
```json
{
  "file_path": "string",             // 文件路径（OPP 本地访问）
  "source_md5": "abc123...",         // 之前的 MD5
  "target_lang": "en"
}
```

**响应体**：
```json
{
  "success": true,
  "data": {
    "changed": false,                // true = 内容变化，需要重新翻译
    "new_md5": "abc123...",          // 当前 MD5（如果 changed=true）
    "cached_result": {               // 如果 changed=false，返回缓存的 chunk 结果
      "chunks": [...],
      "glossary": [...]
    }
  },
  "error": null
}
```

---

### 3.5 健康检查接口

**端点**：`GET /api/v1/health`

**响应体**：
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "capabilities": ["chunk", "chunk-quality", "glossary", "check-incremental"]
}
```

---

## 4. OLL 集成指南

### 4.1 典型调用流程

```
1. OLL 收到翻译任务（文件路径 + 源语言 + 目标语言）

2. 调用 OPP /api/v1/check-incremental 检查是否需要重新分块
   ├─ 如果 changed=false → 使用缓存的 chunks 和 glossary
   └─ 如果 changed=true → 继续步骤 3

3. 调用 OPP /api/v1/chunk 获取分块结果
   └─ 保存 chunks 到 TranslationContext.units

4. 调用 OPP /api/v1/glossary 获取术语列表
   └─ 保存到 TranslationContext.glossary

5. OLL 执行翻译（使用 OPP 提供的 chunks 和 glossary）

6. （可选）调用 OPP /api/v1/chunk-quality 评估翻译质量
```

### 4.2 TranslationContext 映射

OLL 的 `TranslationContext` 从 OPP 获取数据：

```python
# OLL 侧代码示例
from opp_client import OPPClient

client = OPPClient(base_url="http://localhost:8080")

# 获取分块
chunk_result = client.chunk(source_text, source_lang="zh", format_type="epub")
context.units = [
    TranslationUnit(
        unit_id=f"chunk_{i}",
        source_text=chunk["text"],
        shield_map={},
        metadata={
            "chunk_index": chunk["index"],
            "chapter_ref": chunk["chapter_ref"],
            "char_count": chunk["char_count"]
        }
    )
    for i, chunk in enumerate(chunk_result["chunks"])
]

# 获取术语表
glossary_result = client.glossary(source_text, source_lang="zh", top_k=50)
context.glossary = {
    term["source"]: {
        "translation": term["translation"],
        "context": term["context"],
        "frequency": term["frequency"]
    }
    for term in glossary_result["terms"]
}
```

---

## 5. 错误码定义

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| `INVALID_FORMAT_TYPE` | 400 | 不支持的文档格式 |
| `INVALID_LANG_CODE` | 400 | 无效的语言代码 |
| `TEXT_TOO_SHORT` | 400 | 原文太短，无法分块 |
| `CHUNKING_FAILED` | 500 | 分块过程出错 |
| `GLOSSARY_EXTRACTION_FAILED` | 500 | 术语提取失败 |
| `QUALITY_EVAL_FAILED` | 500 | 质量评估失败 |
| `FILE_NOT_FOUND` | 404 | 文件不存在（用于 check-incremental） |
| `SERVICE_UNAVAILABLE` | 503 | OPP 服务不可用 |

---

## 6. 配置项

OPP 服务端配置（`opp_config.yaml`）：

```yaml
server:
  host: "0.0.0.0"
  port: 8080

chunking:
  default_target_size: 50000
  default_strategy: "smart"
  max_chunks_per_file: 500

glossary:
  default_top_k: 50
  min_term_frequency: 2
  default_languages:
    - zh
    - en
    - ja
    - ko

quality:
  pass_threshold: 0.7
  variance_threshold: 2.0

cache:
  enabled: true
  ttl_hours: 24
```

---

## 7. 已知限制

| 限制项 | 说明 | 解决方案 |
|--------|------|----------|
| 文件大小 | 单文件最大 100MB | 分批处理 |
| 实时性 | API 响应延迟取决于文件大小 | 异步调用 + webhooks（未来） |
| 术语语言 | 当前仅支持源语言提取 | 后续增加目标语言术语建议 |

---

## 8. 变更历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 1.0.0 | 2026-05-25 | 初始版本 |

---

## 9. 联系方式

| 系统 | 负责团队 | 联系方式 |
|------|----------|----------|
| OPP | OPP 团队 | - |
| OLL | OLL 团队 | - |