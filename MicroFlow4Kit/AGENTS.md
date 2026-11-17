# AGENTS.md —— MicroFlow4Kit（支撑平台共享底座）

三平台（Orchestration/Ops/Bizops）的共用件：纯 TS 源码包（无构建产物，Vite alias 直接消费）。

## 包结构

- `packages/ui`：oklch token、14 个原语组件、主题（暗色默认）、overlay、diff、`useAssetLock` 排他编辑锁、`ScopeProvider`/`PermissionGate`（per-scope QueryClient 隔离 + 会话世代号）、⌘K 命令面板、i18n 单例（`initI18n` 幂等）。
- `packages/api`：`dispatch`（宿主单分发端点信封协议）、`orchRest`（控制面 REST，mf_orch_token 共享）、scope 存储与跨标签广播、宿主配置单点 `host.ts`。
- `packages/admin`：平台治理共享页（三平台共挂 `/platform/*`），写走 `{action,payload}` 双层信封。

## 纪律

- **PermissionGate 强耦合 Kit ScopeProvider**：未挂 Provider 的页面（如 Orchestration）不得使用，用各自账号垫片的同形组件。
- i18n：新增文案必须 zh/en 键齐平（测试强制占位符一致）；i18next/react-i18next 统一 alias 到 Kit 单实例，防双实例订阅失效。
- `client.ts` 信封协议 {code,data,message,trace_id}（200/201 成功）——改协议要同步三平台与 HOST_CONTRACT.md。
- 纯逻辑测试 `tests/`（node:test，`npm test`）；契约变更先改 HOST_CONTRACT.md。
