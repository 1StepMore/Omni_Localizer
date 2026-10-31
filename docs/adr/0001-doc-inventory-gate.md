# 0001. 文档真值门禁（doc_inventory + ADR 体系）

- 状态：已接受
- 日期：2026-10-31
- 决策人：maintainer（issue OL#163）

## 背景

OL 的 README / AGENTS / API.md 携带会随功能变化的数字（21 个 MCP 工具、
8 个质量门），此前没有机制校验它们与源码派生值一致；架构决策也没有
ADR 可追溯。AGENTS.md 瘦身（#162）拆出的子文档更需要门禁保护，否则
拆分本身就成了新的漂移源。

## 决策

1. 新增 `scripts/doc_inventory.py`：
   - **派生**活体数字——MCP 工具（`ol_mcp.tools.TOOL_REGISTRY`）、质量门
     数（`ol_lqa.quality_gates.run_quality_gates` 签名里的 `*_enabled`
     开关个数）、场景数与 tier 拆分（scenarios 递归 glob + 行级 tier
     正则）、pyproject 版本；零第三方依赖。
   - **门禁**声明点（README 的 `21 MCP tools` / `8 gates`、AGENTS 的
     `MCP tools (21 total)`、API.md 的 `registers 21 tools` 等）与派生
     值比对；`--check` exit 1 = 有漂移。
   - 生成 `docs/dev/doc-inventory.md` 行集（不新鲜即 fail）；
     README/AGENTS/API.md 反引号路径做存在性检查（两档：本仓总是强制，
     suite 父仓仅在树存在时强制）。
2. 新增 `docs/adr/`（本目录）：TEMPLATE + 索引，架构决策逐条记录。
3. CI（test.yml 的 test-full job）加 `doc_inventory --check` 步骤。

## 备选方案

- **手写一致性检查（AutoMedia check-doc-consistency 模式）** —— 缺少
  「生成行集 + 新鲜度」，声明漂移靠人眼；未选。
- **不引入，靠 review** —— 套件仓与 OPP 的同型门禁上线即各抓到真实
  断链/漂移（OPP#111 门禁首跑抓到 2 个陈旧引用），review 纪律实测
  不可靠。

## 后果

- 正面：关键数字 CI 强制为对；#162 瘦身拆出的子文档进 inventory 行集，
  漂移在 PR 阶段暴露。
- 负面 / 代价：改文档后须重新生成 inventory（一条命令）；声明点清单
  随新文档维护。
- 中性：`scripts/` 下新增常驻脚本；`ol_mcp` / `ol_lqa` 导入发生在
  `--check` 运行时（惰性、不影响 --help 类热路径）。

## 验证

- `python scripts/doc_inventory.py --check` exit 0；
- 故意改错 README 的 "21 MCP tools" → exit 1（开发期实测）。
