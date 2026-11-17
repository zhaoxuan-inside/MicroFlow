# 后端篇：算子 + 编排——用 MicroFlow 从零攒一个交易平台

> 本文是 MicroFlow 系列第二篇（Python 后端使用）。第一篇讲了为什么要造这套框架（[给 VibeCoding 修一条轨道](01-vision-and-philosophy.md)），这篇讲怎么用。所有代码来自仓库里的完整可运行示例：`MicroFlow4Python/examples/trading/`。

## 一、先装上，跑通第一个流程

MicroFlow 后端的 Python 实现**零第三方依赖**——核心只用标准库，pip 装的是你自己：

```bash
cd MicroFlow4Python
py -3.14 -m venv .venv
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m unittest discover -s tests -q   # 227 项测试应全绿
```

框架自带一套 CLI（对 AI 工具和对人同样好用），第一件事永远是探测能力面：

```bash
python -m microflow capabilities
# {"implementation": "python", "commands": {"check": ..., "run": ..., "impact": ...}, ...}
```

这十个命令就是你的全部工作台：`check`（编译校验）、`run`（本地执行）、`impact`（影响分析）、`operators`（算子目录）、`schema`（契约查询）、`diagnostics`（诊断码表）、`policy-schema` / `policy-check`、`describe`、`capabilities`。

**注意那条贯穿一切的规则**：凡触发本地编译或执行的命令必须显式加 `--ephemeral`——这是框架在告诉你"你在跑本地内存演练，不提供耐久保证"。诚实的边界声明，是这套框架的底色。

## 二、定义算子：先立契约，再写方法

一个电商下单流程需要哪些业务步骤？搜商品、算总价、算折扣、查库存、合成订单。每个步骤是一个**算子**——六参数签名，返回布尔值：

```python
def discount(input, output, context, metrix, debug, log):
    total = input["total"]
    payable = total * 95 // 100 if input["vip"] else total   # 会员 95 折，整数分
    output.set("payable", payable)
    output.set("saved", total - payable)
    return True
```

六个参数各有严格职责：`input` 是冻结的只读视图，`output` 只能写自己的 data 区，`context` 不可变，`metrix`/`debug`/`log` 是采集接口。返回 `True` 表示成功，`False` 表示业务否定——**异常自动进 fallback，没有 fallback 则整个根流程立即熔断**。这套签名没有自由发挥的空间，因为 AI 最容易出错的恰恰是"参数语义的隐式约定"。

算子向注册表登记时，契约和副作用是**强制声明**的：

```python
registry.register_schema("trading.discount.pass@1", {
    "type": "object",
    "properties": {"total": {"type": "integer", "minimum": 0},
                   "vip": {"type": "boolean"}},
    "required": ["total", "vip"],
})
registry.register_operator(
    name="trading.pricing_discount", version="1", method=discount,
    input_schema="trading.discount.pass@1", output_schema="trading.discount.result@1",
    capabilities={"effect": "pure", "idempotency_support": "natural"},
    description="会员折扣：vip 按 95/100 整数折算")
```

两条纪律值得单独说：

- **effect 必须诚实**：`pure` / `read` / `write` 三选一。把真实写库操作声明成 `pure` 试图绕过约束？框架在配置检查时直接拒绝。这套框架里骗不了它，也骗不了自己。
- **金额用整数分**：Schema 里写死 `minimum: 0`，浮点金额的精度惨案从源头杜绝。

还有个新手必踩的坑，提前帮你踩了：**数组必须整体写入**。`output.set("products[0]", ...)` 逐个下标写会触发 `SPARSE_ARRAY` 诊断——框架拒绝稀疏数组扩展。正确姿势是攒好一次写：`output.set("products", hits)`。

## 三、编排：一份 JSON 说了算

五个算子怎么组成"下单"业务？写一份编排配置，**不写一行控制流代码**：

```json
{
  "id": "place_order",
  "input_schema": "trading.order.request@1",
  "output_schema": "trading.order.output@1",
  "nodes": {
    "inventory": {
      "operator": "trading.inventory_check@1",
      "inputs": {"items": {"from": "flow.input.items", "required": true}}
    },
    "pricing": {
      "type": "subflow",
      "flow": "pricing",
      "depends_on": ["inventory"],
      "inputs": {"items": {"from": "flow.input.items", "required": true},
                 "vip": {"from": "flow.input.buyer.vip", "required": true}}
    },
    "compose": {
      "operator": "trading.order_compose@1",
      "depends_on": ["pricing"],
      "inputs": {"payable": {"from": "nodes.pricing.output.data.payable", "required": true},
                 "available": {"from": "nodes.inventory.output.data.available", "required": true}}
    }
  }
}
```

注意 `pricing` 是一个 **subflow（子图）**——把"算总价→算折扣"封装成独立流程，有版本、有输入输出端口、可独立测试。流程图大了以后，子图是唯一能走远的抽象方式，但前提是它以复合算子的身份进入契约体系，而不是画布上的一个分组框。

数据流全部走显式路径映射：`nodes.pricing.output.data.payable`。来源必须以 `flow.input` / `nodes.<id>.output` / `context` 开头，类型不兼容在编译期直接报 `SCHEMA_INCOMPATIBLE`，映射目标重叠报 `MAPPING_CONFLICT`。**很多 bug 在发布前就死了，这是静态检查存在的意义。**

## 四、CLI 回路：每一步都有机器证据

配置写完，走校验：

```bash
python -m microflow check trading.project.json --ephemeral
# {"diagnostics": [], "flows": ["browse", "place_order", "pricing"], "releaseId": "d82a03a4..."}
```

0 诊断，拿到 releaseId——编译产物不可变，之后的执行都固定在这个版本上。跑起来：

```bash
python -m microflow run trading.project.json place_order input_order.json --ephemeral
```

请求是"VIP 买家买一台 4999 元手机和一副 499 元耳机"，输出：

```json
{"meta": {"status": "SUCCEEDED"}, "data": {"order": {
    "orderId": "SO-a6bcf1025e09", "status": "CREATED", "payable": 522310}}}
```

(499900 + 49900) × 95 ÷ 100 = 522310 分，¥5223.10。换一个缺货 SKU 的输入，订单照常合成，状态自动变 `BLOCKED`——业务否定用数据表达，不是异常。

**划重点：调用成功 ≠ 业务成功。**HTTP 返回 200 只说明流程跑完了，业务终态看 `Output.meta.status`。这条铁律帮 AI（和人）避开了"把任务接纳当成业务成功"的经典大坑。

## 五、影响分析：改代码之前先问图

想改 `order_compose` 算子？先查影响面：

```bash
python -m microflow impact trading.project.json --ephemeral --operator trading.order_compose@1
# flows: ["place_order"], references: [{flow: place_order, node: compose, kind: operator}]
```

想改 `pricing` 子图：

```bash
python -m microflow impact trading.project.json --ephemeral --flow pricing
# references: [{flow: place_order, node: pricing, kind: subflow}], upstream_flows: ["place_order"]
```

影响面是确定性的图查询，不是开发者的直觉。改配置比改算子便宜——这个判断现在有了量化依据。

## 六、观测与运营：采集是框架的事

一个经常被忽略的事实：**你一行日志都没写，但监控数据已经有了**。框架在运行时边界自动产生结构化执行记录——每次调用的开始/结束/耗时/状态/重试，格式统一，零埋点。

仓库里的 `ops_report.py` 演示了上层聚合：跑一组演练后输出监控指标（每个算子的调用量、成功率、平均耗时）和运营汇总（订单数、BLOCKED 数、GMV）。我们实测的一组数据：5 个算子全部 100% 成功率，2 单成交 1 单缺货，GMV 1044620 分。

甚至还有个标准库写的 HTTP 宿主（`server.py`），把流程包装成 `POST /run/place_order` 接口——毕竟框架管执行机制，网络包装本来就是宿主的职责。

## 七、边界：现在能用什么，不能用什么

如实声明（这也是这个框架的价值观）：

- ✅ 本地同步演练：静态 DAG、子图、异常熔断、确定性编译、影响分析、默认采集——**测试全绿，可放心用**；
- ⚠️ 协议已定义、切片验证中：耐久调度、业务幂等、未知结果确认、可靠事件——生产环境先别依赖；
- ❌ 显式拒绝：写入型算子、动态控制节点执行、自动恢复——本地路径会直接拒绝相关配置，而不是静默忽略。

这个"未验收的能力不用"的原则，恰恰是为了让框架未来能被放心地用于生产。

---

下一篇：[前端篇——页面即配置：用 MicroFlow Flutter 框架声明同一个交易平台](03-flutter-usage.md)。前端会更好玩：页面由 AI 经结构化命令面逐条"建"出来，每一条都过门禁、留审计。

*有问题评论区见；仓库地址见第一篇文末。*
