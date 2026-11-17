# AGENTS.md —— MicroFlow4Orchestration（编排管理平台）

前后端一体的编排管理平台：React SPA（`src/`）+ 自有控制面后端（`server/`，FastAPI + PostgreSQL `orch_control`，独立账号体系 admin/editor/viewer）。

## 架构事实（先查再改）

- SPA 经 vite 代理访问两个后端：`/api` → 宿主网关 :3000（遗留：Ops/Bizops 数据源），`/orch-api` → 自有控制面 :8200（rewrite 去前缀到 /api）。**目录/生命周期/审批/回滚/实验/配置中心已全部走控制面 REST**。
- 控制面路由统一挂 `/api` 下（`server/app/main.py` `_mount`）；信封 `{code,data,message,trace_id}` 与宿主一致。
- 账号体系：`orchAuth.tsx`（useScope/PermissionGate 垫片，同 Kit 形状）——**不要在无 Kit ScopeProvider 的页面用 Kit 的 PermissionGate**（会 throw；用 orchAuth 垫片）。
- 独立共享件 `orchClient.ts`：401 统一清 token 跳登录。

## 控制面关键语义

- 阶段下发守卫：dev→test→staging→online 不可跳过 + 上一环境须有 debug 上报 SUCCESS（E2E 门禁）——`lifecycle.do_deploy`。
- `env_current` 指针表记录每环境生效版本；回滚 = 旧版本重新走 do_deploy（守卫照常）。
- `config_hash` = SHA-256 规范化 JSON（内容寻址）；宿主装有 microflow 时另有 `flow_digest`（平台图→flow 骨架摘要）。
- 审批：staging/online 强制第二人确认，同人禁审（服务端硬校验）。
- 告警求值挂点：debug I/O 上报与场景执行响应后同步执行（`alerting.process`）；同 rule+scope 未 ack 只累计不重复开。

## 纪律

- 后端写路由必须过 `require(perm)` + `guard` 信封包装；新路由先在 `main.py` `_mount`。
- 权限点新增要同步 `web.py ROLE_PERMS` 三角色。
- 数据不入 git：`data/`、`*.sqlite` 已 ignore；bootstrap 管理员密码只打印一次。
- 测试：`server/tests/` 纯逻辑（无 PG 必跑）+ 集成（`ORCH_TEST_DATABASE_URL` 缺失时显式 skip，不伪造通过）；SPA `npm test`（node:test）。
- 门禁：`tsc -b` + `vite build` 全绿。
