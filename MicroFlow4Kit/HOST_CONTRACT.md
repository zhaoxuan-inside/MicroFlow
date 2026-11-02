# 宿主契约（Host Contract）—— 支撑平台对宿主的全部依赖面

支撑平台与具体业务项目无关；以下能力由宿主（如 OpcHub）按契约实现。协议：POST 单分发端点
（默认 `/api/v1/dispatch`），载荷 `{scenario, version, payload, context:{token, tenant_id?, project_id?, env_key?}}`，
信封 `{code, data, message, trace_id}`（200/201 为成功）；身份来自 `Authorization: Bearer` 或 `context.token`，
`context.user_id` 不被信任。

## 场景清单

| 域 | 场景 | 说明 |
|---|---|---|
| 身份（宿主关切） | `auth.login` / `auth.session` | 登录与会话；登出为客户端清 token |
| 平台治理 | `platform.scope.my`，`platform.tenants.*`，`platform.projects.*`，`platform.roles.*`，`platform.permissions.list`，`platform.users.*`，`platform.envs.*` | 租户/项目/成员/可配置角色/用户/环境管理（写走 `OPC_PLATFORM_GOVERNANCE_PIPELINE`，`{action,payload}` 信封） |
| 编排目录 | `orchestration.catalog.*`，`orchestration.{operators,subgraphs,scenarios}.*`，`orchestration.locks.*`，`orchestration.approvals.*`，`orchestration.assets.copy`，`orchestration.dag.list` | 三层资产目录全生命周期（写走 `OPC_ORCHESTRATION_CATALOG_PIPELINE`，项目隔离 + 排他锁） |
| 实验域 | `experiment.list/detail/create/update/status/delete/assign/outcome.report/readout` | A/B 实验（写/分流走 `OPC_EXPERIMENT_PIPELINE`） |
| 配置中心 | `configcenter.namespaces.*`，`configcenter.items.*`，`configcenter.resolve` | 灰度发布与按环境解析（写走 `OPC_CONFIGCENTER_PIPELINE`） |
| 运维 | `ops.runs.list/detail/metrics`，`platform.audit.list` | 运行记录/指标/审计 |
| 运营 | `bizops.overview/actions/trend/funnel/retention` | 真实数据聚合 |

## 权限点目录（宿主 RBAC 需实现）

`platform:tenant_manage/user_manage/role_manage/audit_read`、`tenant:member_manage/project_create/role_manage`、
`project:manage/member_manage`、`orchestration:read/write`、`experiment:manage/read`、`configcenter:read/write`、
`page:ops_console/page:bizops_console`。scope 语义：PLATFORM 全局 / TENANT 租户内 / PROJECT 项目内；
活动环境 `staging/online` 为保护级（发布/回滚要求项目所有者角色）。

## 路线衔接

漏斗时序归因与运行时多环境拓扑随框架 T14 控制面 / T15 运行分析落地；Flutter 侧遥测查询协议见 §30.2。
