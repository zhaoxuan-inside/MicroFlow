# AGENTS.md —— MicroFlow4Bizops（运营平台）

纯前端 SPA（React + Kit 共用件）；数据源全部真实（宿主网关 `bizops.*` / `experiment.readout`），**零埋点依赖、口径诚实披露**。

## 纪律

- 实体标签解析在 `src/lib/entities.ts`（测试固定）：未登记实体**如实回退显示原名**，不做猜测式美化。
- 漏斗口径（足迹去重、非严格时序）、样本量与 note 如实透出——展示层不许美化数据口径。
- KPI/趋势/漏斗/留存 D1D7/实验读出全部经 Kit `dispatch`；权限门用 Kit `PermissionGate`（ScopeProvider 体系）。
- 纯逻辑抽 `src/lib/`，配 `tests/*.test.mts`（node:test，`npm test`）；门禁 `tsc -b` + `vite build`。
- 宿主契约见 `../MicroFlow4Kit/HOST_CONTRACT.md`。
