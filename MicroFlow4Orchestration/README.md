# MicroFlow4Orchestration —— 编排管理支撑平台

MicroFlow 上层承载（根 README §三.4「汇聚、查询、看板、告警由上层承载」）· 编排管理：算子/子图/场景三层资产目录全生命周期（创建 → 持锁编辑（@xyflow/react 画布，成环拒绝/撤销）→ 发布/第二人审批 → 回滚 → 删除，项目隔离 + 跨项目显式复制）、A/B 实验域、配置中心（灰度发布 × 项目环境 dev/test/staging/online）。

技术：React 19 + Vite 6 + Tailwind 4 + TanStack Query；共享底座见 `../MicroFlow4Kit`（宿主契约见 `../MicroFlow4Kit/HOST_CONTRACT.md`）。

```bash
npm install --no-bin-links
node node_modules/vite/bin/vite.js build   # dev: 4601，/api 代理到宿主 3000
```
