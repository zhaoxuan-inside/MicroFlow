# AGENTS.md —— VibeCoding 工具开发纪律（MicroFlow 仓库）

MicroFlow 是面向 VibeCoding 开发方式（AI 结对编程）的业务框架体系：**后端 = 业务无关算子 + 结构化编排配置；前端 = 声明式项目模型 + 带门禁的命令面**。目标是让 AI 工具的全部工作落在"可校验、可验证、可审计"的结构化轨道上。

## 读序（先读这个再动手）

1. 根 `README.md` —— 愿景、设计基线、实现状态（§5.4 如实声明）
2. 目标子项目的 `README.md`（集成与使用）+ `DEVELOPER_GUIDE.md`（标准开发回路）
3. 本目录下目标子项目的 `AGENTS.md`（纪律速查）
4. 设计原文已归档 git 历史（根 README 附录有索引）——需要时用 `git show` 恢复，不要凭记忆重构设计

## 六条开发纪律

1. **小步**：一个会话一个任务，做完即收口；大任务拆到"可单步验证"的粒度。
2. **验收先行**：动手前写下机器可判定的完成标准（check 0 诊断 + run 期望输出 + 测试）。
3. **证据**：每步附真实运行输出；"应该可以了"= 未完成；**调用成功 ≠ 业务成功**。
4. **负面清单**：禁止 Mock/TODO 代替真实实现；禁止改测试断言迁就实现；禁止把写入声明成 `pure`；先探测能力再使用命令。
5. **不猜，查**：契约看 `schema`，影响看 `impact`，能力看 `capabilities`，诊断看 `diagnostics`——API 面封闭且全部可读，猜测是幻觉的来源。
6. **诚实**：替身不算生产证据；未验收能力不使用；边界声明随交付更新。

## 标准开发回路（后端；MCP 工具名见 MicroFlow4MCP）

```
capabilities 探测 → operators/schema 查契约 → scaffold 生成骨架（可选）
→ 补全 [fill] 段（业务规则真实实现，不留 TODO）
→ check（0 诊断才继续）→ run --ephemeral 演练（对照期望输出）
→ impact 影响预览（改契约前必看）→ 提交 git
```

每一步的命令输出就是证据链。AI 工具可通过 MCP 直连：`microflow_capabilities` / `microflow_check` / `microflow_run` / `microflow_context` / `microflow_scaffold` 等 12 个工具（见 `MicroFlow4MCP/README.md` 接入配置）。

## "不猜，查"映射表

| 要做的事 | 查什么 | 经什么 |
|---|---|---|
| 知道有哪些命令/能力 | `capabilities` | CLI / `microflow_capabilities` |
| 写算子前看契约 | `schema` + `describe` | CLI / MCP |
| 改算子前看影响面 | `impact` | CLI / MCP |
| 理解一个算子的边界 | `context` | CLI / MCP |
| 解释一个诊断码 | `diagnostics` | CLI / MCP |
| 策略字段/合并语义 | `policy-schema` | CLI / MCP |

## 提交纪律

- 一批工作一个 commit，message 说清楚"做什么 + 为什么"；测试绿了才提交。
- 框架测试门禁：`pytest MicroFlow4Python`（全绿）+ `flutter test`（基线覆盖不回退）。
- 支撑侧（三 SPA / Kit / Host / Container / Registry / 部署壳）已于 2026-11-26 拆分至兄弟仓
  `MicroFlowSupport`——其构建/测试门禁随迁，见支撑仓 AGENTS.md。
