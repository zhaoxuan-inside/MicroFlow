# MicroFlow4Host —— 宿主参考实现

把 [HOST_CONTRACT.md](../MicroFlow4Kit/HOST_CONTRACT.md) 从文档变成**可运行起点**：dispatch 单端点网关 + 最小治理 + RBAC 权限点目录 + 遥测接收端口 + ops/bizops 读时聚合 + 三平台 SPA 托管 + `scaffold` 骨架生成器。消除"宿主契约人人从零自写"的生态断链（设计动机见根目录 [LIFECYCLE.md](../LIFECYCLE.md)）。

技术：Python ≥3.12 + FastAPI + SQLite（单机协议验证介质，生产介质归宿主演进）；口令 PBKDF2（标准库）。

## 协议实现（对齐 HOST_CONTRACT.md）

- **dispatch 单端点** `POST /api/v1/dispatch`：信封 `{code, data, message, trace_id}`；身份只来自 `Authorization: Bearer` 或 `context.token`——**`context.user_id` 不被信任**（测试固定）。
- **场景清单**：auth.\* / platform.scope.my / 治理（tenants/projects/users/roles/envs/audit）/ ops.runs.\*·ops.metrics·ops.events.list / bizops.\* / **registry.publish·registry.stream**；`orchestration.*`、`experiment.*`、`configcenter.*` 由编排控制面承载，本参考实现**诚实 501**（不做占位实现）。
- **registry 承载**（`MicroFlow4Registry` 客户端的服务端兑现）：`registry.publish` 落 `registry_snapshots`（`contentDigest` 幂等：registered/updated/unchanged）、`registry.stream` 落 `registry_events`（`event_id` 唯一约束兑现 at-least-once 接收侧去重）；两侧**宿主重算 canonical JSON + SHA-256 摘要**，不信任客户端自报完整性；`ops.events.list` 按聚合键检索真实帧（Ops 瀑布数据源）。权限点 `registry:write`（新入目录）。
- **权限点目录**：17 个权限点单一来源（`scenarios.py`），场景→权限映射 + 用户-角色三级 scope（PLATFORM/TENANT/PROJECT）判定；治理写路径全部入审计。
- **遥测接收端口** `POST /api/v1/telemetry`：信封批量接收（≤100/批），有界容量 10000，**过载显式 429**（TELEMETRY_OVERLOAD，不静默降级）；无效信封不落库、逐条计数如实返回。
- **聚合**：ops.metrics 读时聚合真实分位；bizops 漏斗（足迹去重口径 + 样本量如实披露）、留存 D1/D7、趋势——与 Bizops 平台"口径诚实披露"纪律一致。

## 使用

```bash
pip install -e MicroFlow4Host   # 或 pip install -e ".[test]"
microflow-host bootstrap --store host.sqlite3 --admin owner    # 口令只打印一次
microflow-host scaffold --into my-host                         # 骨架：只写 --into，永不覆盖
microflow-host serve --store host.sqlite3 --port 3000 --apps-dir ./apps
```

SPA 构建产物放入 `apps/ops|bizops|orchestration`（各含 index.html）；未部署的应用**诚实 404**（不装假页面）。

## 测试

```bash
python3 -m pytest tests/ -q    # 20 项：信封契约、身份信任边界、RBAC、治理生命周期、
                               # 遥测过载、聚合口径、SPA 托管、scaffold/bootstrap 纪律
```

## 边界声明

- 参考实现验证协议正确性，不冒充生产部署证据（替身不算生产证据）；宿主关切（真实身份体系、介质演进、部署拓扑）归部署方扩展。
- 每次场景执行记录为 run 记录（场景级 status/durationMs）；节点级瀑布需要框架执行数据，属编排控制面/框架的承载面。
- 委托接线（orchestration.\* 等代理到 ：8200）是宿主扩展点，参考实现只如实声明未接线。
