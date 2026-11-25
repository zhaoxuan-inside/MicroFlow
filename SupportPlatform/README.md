# SupportPlatform —— 部署壳 + 一键开发栈

两件事，都是"框架外"的部署关切：

1. **部署壳**（`server.py`）：一个进程按环境变量服务一个平台 SPA 的 dist 静态面，
   并把 `/api/*` 反代到宿主网关、`/orch-api/*` 反代到编排控制面（前缀改写 `/orch-api`→`/api`）。
   路径穿越防护、assets immutable 缓存、SPA fallback no-cache、上游不可达显式 502——
   有 `tests/test_server.py` 八项验收，CI（`support-platforms.yml` 的 `deploy-shell` job）覆盖。
2. **一键开发栈**（`compose.yaml`）：`docker compose up -d --build` 起整套——
   PostgreSQL + 编排控制面（:8200）+ 宿主网关（:3000，`dev-admin / dev-password`）；
   `--profile spas` 再起三个 SPA 壳（需先各自 `vite build`）。

```bash
cd SupportPlatform
docker compose up -d --build               # 核心三件
docker compose --profile spas up -d        # 可选：4601/4602/4603
docker compose down -v                     # 收拾现场
```

## 与 MicroFlow4Host 的托管分工（写死，防半年后的误删）

| | 拓扑 | 定位 |
|---|---|---|
| `MicroFlow4Host` `/apps/*` | 单端口、多应用、同源 | 宿主参考实现（含 dispatch/RBAC/遥测/registry.*） |
| 本部署壳 | 多端口、单应用、各自反代 | 三平台独立部署的薄前端，SPA 源码零改动 |

两者是**两种部署形态**，不是重复实现：改托管语义（缓存头/穿越/502）时以本壳的
测试为准，宿主 `/apps` 是同源形态的等价面。

## 镜像

| 镜像 | 上下文 | 说明 |
|---|---|---|
| `../MicroFlow4Host` | `pip install .` + uvicorn | 宿主网关；`host-bootstrap` 一次性服务先建管理员 |
| `../MicroFlow4Orchestration/server` | `pip install -r requirements.txt` | 控制面，`ORCH_DATABASE_URL` 锚定 PG |
| 本目录 | `server.py` + fastapi/uvicorn/httpx | 部署壳 |

`deploy/host-bootstrap.sh`：可重入引导——管理员已存在则跳过（bootstrap CLI 本身幂等拒绝重建）。

## 边界声明

- 开发栈是**协议验证介质**，不是生产清单：限流、备份/恢复、PG 介质 Provider、自身可观测
  见 BLUEPRINT §六（R5），不在 `compose.yaml` 范围内。
- SPA dist 由开发者在宿主机构建（Samba 盘 `--no-bin-links`），栈内不构建前端；
  未构建时不要开 `spas` profile（壳在 dist 缺失时如实退出，不装假页面）。
