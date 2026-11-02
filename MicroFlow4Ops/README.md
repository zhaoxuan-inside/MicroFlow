# MicroFlow4Ops —— 运维支撑平台

观测承载：MicroFlow 场景运行记录（节点级真实时长瀑布，框架 durationMs）+ 指标看板（调量/成功率/P95，读时聚合不预存时序）+ 审计检索 + 调试工作台。数据全部来自宿主运行记录与审计流，零造假。

技术：React 19 + Vite 6 + Tailwind 4 + recharts；共享底座见 `../MicroFlow4Kit`。

```bash
npm install --no-bin-links
node node_modules/vite/bin/vite.js build   # dev: 4602
```
