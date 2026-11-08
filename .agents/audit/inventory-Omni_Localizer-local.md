# Inventory — Omni_Localizer @ a1f4b59fa930e46a377d85aa15821a03a964b262 (2026-11-07)  SOURCE=LOCAL（§7.5）
| ID | 子系统 | 路径 | 类别 | 测试现状 | 文档现状 | CI 覆盖 | 判定依据 | 处置建议(A编号) |
|----|--------|------|------|----------|----------|---------|----------|----------------|
| S-01 | 翻译引擎 | src/ol/(21 MCP tools, 3-stage repair, LQA, TM/glossary) | 源码 | tests/ 170+ 文件 | AGENTS.md(202行>200❌C3) | test.yml | AGENTS.md | A1 瘦身(-2 行以上,O-1) |
| S-02 | 测试 | tests/ | 测试 | 有 | — | test.yml | 模块测试套件 | 不动 |
| S-03 | 文档 | docs/ + AGENTS.md + README | 文档 | — | suite: 前缀✅ | doc_inventory(副本) | 跨仓检查(#253) | A13 副本同步(O-2) |
| S-04 | CI | .github/workflows/(test.yml,publish.yml,real-llm-nightly.yml + ?? pinned-guard.yml) | CI | — | — | 自身 | real-LLM nightly 周级 | A7: test.yml 增一致性 job(O-2) |
| S-05 | 工程 | Makefile/pyproject.toml | CI | make test/lint✅ | — | — | 参数取证 | 参数区回填 |

## 待废弃清单（仅标记不删除）
- 无
## 敏感文件清单（仅路径）
.env(已忽略✅,实测 git check-ignore 通过) / .env.example
## 现有 agent 设施清单（D4）
AGENTS.md(保留+瘦身+路由指针) / .opencode(保留)
## 前置缺口登记（A14）
- 无
## 工作区脏点（D2 类推处置记录）
- ?? .github/workflows/pinned-guard.yml（同 OPP：保持 untracked，遗留项）
## 回填参数区
BUILD_CMD=pip install -e .; TEST_CMD=make test; LINT_CMD=make lint; E2E_CMD=(模块级); E2E_RUNNER=根仓 e2e-tests.yml; REPO=Omni_Localizer
