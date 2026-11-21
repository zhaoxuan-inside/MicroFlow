# AGENTS.md —— MicroFlow4Host（宿主参考实现）

`src/host/`：database（SQLite + 全方法锁串行化）/ security（PBKDF2）/ scenarios（权限点目录单一来源）/ handlers（场景处理器）/ app（网关装配）/ cli（bootstrap/serve/scaffold）。

## 架构事实（先查再改）

- **身份信任边界**：`context.user_id` 永不被信任；身份只来自 Bearer 头或 `context.token` → `sessions` 表。改身份逻辑前先读 `IdentityTrustTests`。
- **权限点目录单一来源**：`scenarios.py` 的 `PERMISSION_CATALOG`（17 个）+ `SCENARIO_PERMISSIONS` 映射；roles.permissions 是目录子集（未知权限 create 即 422）。三级 scope：platform_roles / memberships / project_members。
- **遥测接收**：过载显式 429、无效信封不落库但逐条计数（accepted/rejected 如实返回）——与框架"能力不足显式拒绝而非静默降级"同纪律。
- **诚实拒绝**：编排/实验/配置中心场景（DELEGATED_SCENARIOS_PREFIXES）未接线时 501，不做占位实现。
- **治理写路径全审计**：tenants/projects/users/roles/envs 的 create/update 过 `db.audit_append`；多写用 `db.transaction()`（原子收口）。

## 纪律

- bootstrap 口令只打印一次；scaffold 只写 `--into`、永不覆盖（与 4MCP/4Python scaffold 同纪律，测试固定）。
- 场景执行统一记录 runs（status/durationMs/actor/scope）——ops.* 与 bizops.* 只读时聚合，不预存时序。
- 新场景三步：`handlers.py` 实现 → `app.py` SCENARIOS 注册 → `SCENARIO_PERMISSIONS` 权限映射 → 契约测试；缺权限映射的场景不该存在。
- 测试：`python3 -m pytest tests/ -q`；真实起服冒烟用 `microflow-host serve` + curl（见 README）。
