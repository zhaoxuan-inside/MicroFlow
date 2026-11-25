# MicroFlow4Ops —— 运维支撑平台

观测承载：**dispatch 运行记录**（宿主 runs 表真实字段：scenario/status/duration_ms/actor/env）+ **事件瀑布**（`ops.events.list`，microflow-registry stream 上报的真实帧，按聚合键分组、帧内 durationMs 画条）+ 指标看板 + 审计检索 + 调试工作台。数据全部来自宿主运行记录与事件流，零造假；字段与 `../MicroFlow4Kit/host-contract.fields.json` 逐字对齐（守卫测试双向咬合）。

技术：React 19 + Vite 6 + Tailwind 4 + recharts；共享底座见 `../MicroFlow4Kit`。

```bash
npm install --no-bin-links
node node_modules/vite/bin/vite.js build   # dev: 4602
```
