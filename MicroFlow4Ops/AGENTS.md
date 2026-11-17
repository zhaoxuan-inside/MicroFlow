# AGENTS.md —— MicroFlow4Ops（运维平台）

纯前端 SPA（React + Kit 共用件）；数据全部来自后端，**零造假数据**。

## 数据源双通道

- 宿主网关（Kit `dispatch`，`/api` → :3000）：`ops.runs.list/detail/metrics`、`platform.audit.list`、`orchestration.scenarios.execute`（调试工作台）。
- 编排控制面（Kit `orchRest`，`/orch-api` → :8200）：`/api/alerts*`（告警中心）——控制面独立账号体系，页面内置登录面（无 token 或 `ops:alerts` 权限时回落）。

## 纪律

- 运行记录瀑布的节点时长来自框架真实 `durationMs` 上报；换算语义在 `src/lib/waterfall.ts`（测试固定），不要在页面内联算式。
- 指标看板读时聚合，不预存时序——p95 是真实分位数。
- 权限门用 Kit `PermissionGate`（本平台保留 Kit ScopeProvider 体系）。
- 纯逻辑抽 `src/lib/`，配 `tests/*.test.mts`（node:test，`npm test`）；门禁 `tsc -b` + `vite build`。
- 宿主契约见 `../MicroFlow4Kit/HOST_CONTRACT.md`（含控制面承载段）。
