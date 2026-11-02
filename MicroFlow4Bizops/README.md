# MicroFlow4Bizops —— 运营支撑平台

业务读出（Umami/GrowthBook 读出模式）：KPI 总览 + 按日趋势 + 业务漏斗 + 留存（D1/D7）+ 实验读出。数据源全量真实：实体计数 + 审计流足迹（样本量如实披露）+ 运行记录，零埋点依赖；漏斗口径（足迹去重，非严格时序）如实标注。

技术：React 19 + Vite 6 + Tailwind 4 + recharts；共享底座见 `../MicroFlow4Kit`。

```bash
npm install --no-bin-links
node node_modules/vite/bin/vite.js build   # dev: 4603
```
