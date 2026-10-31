# OL production matrix — channels × quality gates × MCP tools (issue OL#164)

Derived truth: MCP tools: **21** · quality gates: **8** · scenarios: **5**
（计数由 `scripts/coverage_matrix.py --check` 与源码派生值比对；
`scripts/doc_inventory.py --check` 门禁 README/AGENTS 的对应声明。）

标注含义：✅ 主路径可用 · ⚠️ 可用但依赖可选包 / 特定配置 · ❌ 不支持。
目标语言是配置驱动（`config/*.yaml` 的模型池 + `--target-lang`），不设
硬编码清单——任何 LLM 支持的语言对都可用，矩阵因此按「通道 × 门 × 工具」
组织而非按语言枚举。

## Translation channels

| 通道 | 输入 | 输出 | 下游 | 备注 |
|------|------|------|------|------|
| `translate-md` | `.md` | 翻译后 `.md` | ORF `apply-md`（16 格式） | 主通道；`--chunk-by-paragraph` 适合文学文本 |
| `translate-xliff` | `.xlf`/`.xliff` | `<target>` 填充的 XLIFF | ORF `apply-xliff`（需 skeleton） | 版式保持；需要 OPP 的 skeleton.zip |
| `translate-batch` | 目录 | 目录 | 同上两通道 | `--concurrency` 并发；断点续跑见 cache |

通道选型决策表见 `docs/dev/pipeline.md`（translate-md vs translate-xliff）。

## Quality gates

| 门 | 标注 | 说明 |
|----|------|------|
| `inline_tags` | ✅ | `<bx>/<ex>/<x>` 标签配对校验 |
| `terminology` | ✅ | 术语一致性（需 glossary，缺省跳过该门） |
| `length_ratio` | ✅ | 长度比上下界（`OL_LENGTH_RATIO_MIN/MAX`） |
| `locale` | ✅ | 货币/日期/数字分组/拼写（`OL_TARGET_LOCALE`） |
| `source_copy` | ✅ | 源文回显检测 |
| `source_script_check` | ✅ | 非 CJK 目标中的 CJK 残留（`src_lang` 感知，OL#142） |
| `protocol_artifact_check` | ✅ | LLM 协议标记泄漏 |
| `invented_token_check` | ✅ | 模型自造粘连 token（OL#158） |

全部为**非阻塞 warning**（`OL_WARN: <CODE>`）；MCP 通道的
`quality_gates: {ran|not_run|skipped}` 字段如实上报（issue #115）。
完整 warning-code 表见 `docs/dev/gotchas.md`。

## MCP tools（21，套件 coverage_audit 的 ol 行必须 21/21）

| 工具 | 能力域 |
|------|--------|
| `translate_md_text` / `translate_xliff` | 核心翻译（text-in/text-out，带 gates 上报） |
| `batch_translate_texts` | 并行批量 |
| `translate_file` | 端到端（shell 出到 opp/ol/orf CLI） |
| `judge_text` | LQA 评分 |
| `shield_md_text` / `unshield_md_text` | 占位符屏蔽/恢复 |
| `load_glossary` / `get_relevant_terms` / `verify_terms` / `disambiguate` | 术语面 |
| `search_tm` / `add_tm_entries` | TMX 翻译记忆 |
| `extract_terms` | YAKE 术语抽取（需 ML 依赖） |
| `extract_warnings` | 产物中的 OL marker 结构化 |
| `generate_report` | HTML+CSV 质量报告 |
| `inspect_config` | 配置自检（密钥脱敏） |
| `get_translation_status` | 异步任务轮询 |
| `profile_doc` | StyleGuide 剖析 |
| `get_capabilities` / `ping` | 自述 / 健康 |
