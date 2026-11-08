# Inventory — Omni_Localizer @ origin 1StepMore/Omni_Localizer  SOURCE=REMOTE（§7.5）
| ID | 项 | 实测 | 判定依据 | 处置建议 |
|----|----|------|----------|----------|
| R-1 | 远端 | fetch=git@github.com:1StepMore/Omni_Localizer.git / push=https://…（fetch/push 协议混合,如实登记）+ backup OL_BackUp | git remote -v | push 走 https |
| R-2 | ruleset | main-protection ACTIVE（bypass 详情未逐项核对⚠️） | gh api rulesets | PR 流可用 |
