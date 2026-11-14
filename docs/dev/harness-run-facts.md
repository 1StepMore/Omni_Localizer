# Harness 运行事实速查（Omni_Localizer）

> 仓事实真身。通用执行规则（边界 / 权限 / 合并判定）由 Owner 侧维护，不入库。

**解释器**：uv 工程，优先 `uv run`；Windows 原生由套件仓的引导脚本建 .venv_win（Windows 可执行文件在 Scripts\python.exe）。

**安装**：`uv sync --all-extras`；首次用 `ol init` 生成 config/local.yaml。

**必需环境变量**：SPARK_API_KEY 或 ZHIPU_API_KEY。写进 config/local.yaml 时必须是 ${SPARK_API_KEY} 形式，不要写明文；硬编码 key 会抛 SecurityError（除非 OL_ALLOW_HARDCODED_KEYS=1）。

**缺 key 症状**：`ol doctor` 第 5 项 FAIL（env vars resolve），并逐条列出未解析的 role/model。

**陷阱**：loader 每次 load_config 都读仓库根 .env —— "没配 key 却 PASS" 先查它；全局 Python 可能有旧 ol 影子安装，先 `which ol` 确认。

**DoD 顺序**：`make test`（自动 OMNI_TEST_FAKE_LLM=1）→ `make lint` → `ol doctor`。

**队列**：`gh issue list -l agent-ready --state open`。
