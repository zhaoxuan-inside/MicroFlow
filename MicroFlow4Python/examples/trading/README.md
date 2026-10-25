# 交易平台演示（Trading Platform Demo）

ZCode 通过框架接口构建的端到端垂直切片：后端业务 = 算子 + 编排配置（MicroFlow4Python），前端页面 = authoring 命令面构造的项目模型（MicroFlow4Flutter），监控/运营数据面 = 框架内置采集 + 上层聚合。

## 后端（ZCode × 框架 CLI）

构建与验证全部经由 `microflow` CLI（协议 `microflow-cli-v1`）：

```bash
PYTHONPATH=../../src
python3 -m microflow capabilities                                   # 探测命令面
python3 -m microflow check trading.project.json --ephemeral         # 编译与静态校验（0 诊断）
python3 -m microflow operators trading.project.json --ephemeral     # 算子目录 + 静态引用计数
python3 -m microflow schema trading.project.json trading.order@1 --ephemeral
python3 -m microflow impact trading.project.json --ephemeral --operator trading.order_compose@1
python3 -m microflow impact trading.project.json --ephemeral --flow pricing   # 子图引用链
python3 -m microflow run trading.project.json browse input_browse.json --ephemeral
python3 -m microflow run trading.project.json place_order input_order.json --ephemeral
```

业务结构：

- 算子（5 个，纯计算/读取，金额整数分）：`catalog_search` / `cart_total` / `pricing_discount`（会员 95/100）/ `inventory_check` / `order_compose`（确定性 orderId）。
- 流程：`browse`（搜索）；`place_order`（根流程）→ `inventory`（算子）+ `pricing`（**子图**：total → discount）→ `compose`（汇合）。
- 影响分析：改 `order_compose` 命中 `place_order`；改 `pricing` 子图经引用链命中 `place_order`（上游闭包）。

## 监控与运营数据面

观测分层（平台标准 §14）的演示：

- **框架采集内核**：运行时零埋点产生结构化执行记录（attempt/invocation 生命周期），业务代码无一行埋点。
- **上层聚合**（`ops_report.py`）：消费本地演练记录生成监控指标（按算子的调用量/成功率/耗时）与运营汇总（订单数/GMV/状态分布）。生产部署中该角色由监控/运营平台承载，可靠事件经宿主提供者投递（T10/T14）。

```bash
PYTHONPATH=../../src python3 ops_report.py
```

## 前端（MicroFlow4Flutter/apps/trading_app）

- 页面经 **authoring 命令面**构造（§14 `create_page` / `connect_navigation`，actor=zcode-builder）：每条命令走与发布相同的静态校验门禁，产生修改审计与可回滚修订（5 笔修订链）。页面不携带可执行逻辑（§2.9）。
- 商品列表/购物车/下单为声明式 List 绑定 + 适配器（§40）；适配器业务语义与后端流程对齐（整数分、会员折扣），生产部署经 T14 控制面调用后端。
- **监控数据面**：运行时拦截边界零埋点产生 `ops.page.viewed` 与采集注记事件（`ops.trade.added-to-cart` / `ops.trade.order-placed`），经遥测管道落地（mf_platform_store JSONL），供 ops_admin 运营平台收集；测试以内存 sink + 查询断言验证同一管道。
