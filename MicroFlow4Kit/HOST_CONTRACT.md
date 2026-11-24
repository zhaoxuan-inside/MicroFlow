# 宿主契约（Host Contract）—— 支撑平台对宿主的全部依赖面

支撑平台与具体业务项目无关；以下能力由宿主（部署方网关）按契约实现。协议：POST 单分发端点
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
| 注册（可选） | `registry.publish` | `MicroFlow4Registry` 上报发布快照元数据（`{namespace, group, digest, contentDigest, report}`）；按 `contentDigest` 幂等，同 key 异摘要由宿主拒绝。宿主未实现时返回 404/501，客户端如实报 `PUSH_FAILED` |
| 注册（可选） | `registry.stream` | 事件批上报（`{namespace, group, contentDigest, count, batch}`，信封 `microflow-registry-stream-v1`，逐帧 `eventId`）。**投递语义 at-least-once**，消费者按 `eventId` 去重；宿主按 `contentDigest` 幂等接收，过载回 429。未实现时 404/501 |

## 权限点目录（宿主 RBAC 需实现）

`platform:tenant_manage/user_manage/role_manage/audit_read`、`tenant:member_manage/project_create/role_manage`、
`project:manage/member_manage`、`orchestration:read/write`、`experiment:manage/read`、`configcenter:read/write`、
`page:ops_console/page:bizops_console`。scope 语义：PLATFORM 全局 / TENANT 租户内 / PROJECT 项目内；
活动环境 `staging/online` 为保护级（发布/回滚要求项目所有者角色）。

## 控制面承载能力（编排控制面 `/api/*`，非宿主 dispatch）

编排管理平台已自带独立控制面（FastAPI `:8200`，独立账号体系与 `orch_control` 库），以下能力不再依赖宿主：
目录/生命周期/审批/回滚（`orchestration.*` 对应的 REST 路由）、**A/B 实验域**（`/api/experiments*`）、
**配置中心灰度**（`/api/configcenter/*`）、**告警最小闭环**（`/api/alerts`、`/api/alerts/{id}/ack`、
`/api/alerts/rules*`，规则求值挂接容器 debug I/O 上报与场景执行结果；Ops 平台"告警中心"页经 `/orch-api`
代理消费，权限点 `ops:alerts`）。T12 对齐：下发哈希为 SHA-256 规范化 JSON（`config_hash`），并携带
`flow_digest`（宿主装有 microflow 时经 `microflow.platform_graph` 转换的平台图 → flow 骨架摘要）。

## 路线衔接

漏斗时序归因与运行时多环境拓扑随框架 T14 控制面 / T15 运行分析落地；Flutter 侧遥测查询协议见 §30.2。
