# 验证证据区（交叉审计中转）

> 本目录是**要交叉审的产物**的入库落点。协议真身：workspace 根 `99-Tools/methodology/cross-audit-evidence-protocol.md`。

## 为什么有这个东西

质量通过不能口头认定。两侧机器（code 侧 WSL / 主人侧 Windows）不共享磁盘，**唯一共用通道是 GitHub**，
所以产物必须跟着仓库走 git，对方才审得到。放在 `本机临时区（见 .gitignore）` 里的东西对方永远看不见。

## 三类产物

| 类别 | 放哪 | 入库 |
|:--|:--|:--|
| 一次性中间件、调试残片 | `.scratch/` 或系统临时目录 | ✗ |
| 矩阵/验收产物（要交叉审的）| `docs/dev/validation-evidence/<matrix>/<run-date>/` | ✓ |
| 大媒体（>5MB/文件、>50MB/轮）| 同上，但只入**代理件**（片段/抽帧）+ 读数 | ✓（原件✗，留 sha256 + 复跑命令）|

## 目录形状

```
docs/dev/validation-evidence/
├── manifest.json          # 唯一索引，每格一条（schema 见协议 §3）
├── README.md              # 本文件
└── <run-date>/<domain>/<cell>/artifact.* + evidence.md
```

## 硬规则

- `quality.verdict=pass` 必须带 `quality.evidence`，且该文件存在非空 —— 否则**按 fail 计**。
- 每格只保留最新一轮；历史靠 `manifest.json` 的 `produced_at` 追溯。
- 自检：`python3 99-Tools/check_evidence_committed.py <repo>`（exit 0 才达标）。
- 本仓矩阵：**production-matrix**（跑法见 AGENTS.md 的验证段）。

## 交叉审计分工

code 侧（视频/音频模态）产的格 → 主人侧 harness 审；主人侧产的 → code 侧审。
审计结论写回 `manifest.json` 并提交，**没有提交就没有通过**。
