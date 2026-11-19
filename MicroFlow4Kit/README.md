# MicroFlow4Kit —— 支撑平台共享底座

三大支撑平台（编排管理 / 运维 / 运营）的共享底座：设计系统、宿主契约客户端、治理底座页。纯源码包（无构建产物），三平台 SPA 经 Vite 别名消费（族内约定，各 SPA README 声明）。

| 包 | 内容 |
|---|---|
| `packages/ui` | 设计系统（oklch 亮暗 token + 原语）、ScopeProvider/ScopeSwitcher（租户→项目→环境三选）、PermissionGate、useAssetLock（60s 心跳编辑锁）、diffLines |
| `packages/api` | 宿主契约客户端：统一分发 + envelope 解析 + 活动 scope 存储（租户/项目/环境）+ `host.ts` 宿主配置单点 |
| `packages/admin` | 平台治理共享页：租户/项目/成员/角色与权限/用户管理（三平台共挂 `/platform/*`） |

## 宿主契约

支撑平台与具体业务无关：一切后端能力经宿主契约获得（见 `HOST_CONTRACT.md`）。宿主可变点集中在 `packages/api/src/host.ts`，构建期以 `VITE_CONSOLE_*` 覆盖（endpoint / 存储键 / 品牌名 / 事件命名空间）。

## 开发

```bash
npm install --no-bin-links   # Samba 共享盘一律 --no-bin-links
npm test                     # node --experimental-transform-types --test（Node >= 22.7）
```

租户、项目、环境或登录身份变化时，控制台为新范围创建独立查询缓存并重建页面状态；其他标签页通过 storage 事件同步。该机制防止旧范围缓存继续显示，但不替代宿主服务端的鉴权和数据隔离。

> 可靠性（0.11.1）：`dispatch`/`orchRest` 内置 15s 请求超时（`VITE_CONSOLE_REQUEST_TIMEOUT_MS` 可覆盖）——网关挂起不再拖死调用方；SPA 侧 `ErrorBoundary`（@microflow4kit/ui）兜底组件树崩溃。
