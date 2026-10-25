# MicroFlow4Python 开发手册

面向两类读者：**开发者**与 **VibeCoding 工具（AI 代理）**。本手册是任务导向的操作指南——怎么把一个业务需求做出来、做对、验证清楚。语义以仓库设计基线为准（原文档已归档于 git 历史，要点浓缩于根 README「实现的设计」5.1），实现状态以 [README](README.md) 为准；发现冲突先修订设计，不在实现里自行改写。

## 1. 五分钟心智模型

- **业务 = 算子 + 编排配置**。算子是契约明确、副作用如实声明、边界固定的业务步骤；业务功能由编排配置（标准 JSON）组织算子而成。
- **发布快照不可变**。编译产出 release，执行按 release_id 装载；配置改动 = 新版本，不在途热改。
- **框架管执行机制、状态协议与采集**；持久化介质、分析展示、开发工具归宿主与上层（端口注入）。
- **当前可验证路径是本地同步演练**（`--ephemeral`）：纯计算/读取算子、静态 DAG 与子图。耐久执行、写入型算子、恢复是协议切片——**未验收的能力不要用，`UNSUPPORTED_*` 拒绝是护栏不是缺陷**。
- 两条铁律：**调用成功 ≠ 业务成功**（看 `Output.meta.status`）；**实现状态诚实声明**（内存替身不算生产证据）。

## 2. 环境准备

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -q   # 全量测试应全绿
.\.venv\Scripts\microflow.exe --help
```

零第三方依赖：核心只用标准库。不要为图方便引入业务包到框架核心（业务算子自己的依赖归宿主管理）。

## 3. 标准开发回路

VibeCoding 工具首选 CLI（机器可判定证据），开发者可用等价 Python API。每一步都要**附命令输出作为证据**——"应该可以了"等于未完成。

| 步骤 | 命令 | 产出 | 状态 |
|---|---|---|---|
| 1 探测 | `microflow capabilities` | 实现标识 + 命令目录（工具必须先探测再使用） | 已实现 |
| 2 查目录 | `microflow operators <project> --ephemeral` | 算子契约、能力、静态引用计数 | 已实现 |
| 3 查契约 | `microflow schema <project> <name> --ephemeral` | 单个 Schema 定义 | 已实现 |
| 4 建算子 | （`scaffold` 规划中）手工按 §4 模板 | 六参数方法 + 注册 + Schema | — |
| 5 编排 | 编写 flow JSON（§5） | 项目配置 | — |
| 6 校验 | `microflow check <project> --ephemeral` | releaseId + 诊断（**0 诊断才继续**） | 已实现 |
| 7 演练 | `microflow run <project> <flow> <input> --ephemeral` | 标准 Output + 节点记录 | 已实现 |
| 8 影响 | `microflow impact <project> --ephemeral --operator REF` | 引用与上游闭包 | 已实现 |
| 9 提交 | 版本管理（git） | 审计与回滚由版本管理承担 | — |

完整可运行的参照实现：[`examples/trading/`](examples/trading/README.md)（算子 + 编排 + 子图 + 监控运营聚合 + HTTP 宿主）。新任务先读它再动手。

## 4. 算子开发规范

**契约先行**：先注册 Schema，再写方法，最后注册算子。参照 `examples/trading/trading_ops.py`：

```python
def discount(input, output, context, metrix, debug, log):
    total = input["total"]
    payable = total * 95 // 100 if input["vip"] else total
    output.set("payable", payable)
    output.set("saved", total - payable)
    return True

registry.register_schema("trading.discount.pass@1", {...})          # 先有契约
registry.register_operator(name="trading.pricing_discount", version="1",
    method=discount, input_schema="...", output_schema="...",
    capabilities={"effect": "pure", "idempotency_support": "natural"},
    description="...")
```

规则（违反即编译/运行期拒绝）：

1. **六参数签名** `(input, output, context, metrix, debug, log) -> bool`，位置参数、无默认值；`True`=成功，`False`=业务否定（写 `output.data` 表达原因，不抛异常）；异常自动进 fallback，无 fallback 则根流程熔断。
2. **effect 诚实声明**：`pure` / `read` / `write`。写入型算子当前被拒绝接入——不要把真实写入声明成纯计算，这是本框架的诚信底线。
3. **数据规则**：JSON 兼容值（层级 Map/列表/标量）；金额用整数分并写进 Schema（`minimum: 0`）；时间带时区；禁止任意 Python 对象与 pickle。
4. **output 写入**：`output.set(path, value)` 只写 `output.data`；`meta`/`error` 是框架保留命名空间。**数组整体写入一次**（`set("products", hits)`）——按下标逐元素写会触发 `SPARSE_ARRAY`（框架拒绝稀疏数组扩展）。
5. **fallback**：必须显式声明 `fallback_capabilities`；fallback 不递归；`False`/异常 = 未恢复。
6. **注册入口纪律**：`register(registry)` 只做注册声明，不得执行业务、连接资源、起后台任务（`SOURCE_CHANGED`/`MODULE_REGISTRATION_FAILED` 会拦截）。
7. **幂等与缓存**：由配置决定（`default_policy`），代码不固定策略；本地演练路径会拒绝这些配置。

## 5. 编排配置规范

流程 JSON 骨架见 `examples/trading/trading.project.json`。要点：

- **节点类型**：`operator`（默认）/ `subflow` / `route` / `join` / `map` / `loop` / `wait`；动态控制节点的执行尚未接入本地演练器。
- **映射**：`inputs` 的 `from` 必须以 `flow.input` / `nodes.<id>.output` / `context` 开头；`required` 先于 `default` 判定；多目标重叠 = `MAPPING_CONFLICT`；复杂计算交给算子，表达式只有受限白名单（无 eval）。
- **子图纪律**（平台标准 §9.4 v1.4）：**引用而非复制**（带版本共享定义）；**接口预算**——端口建议 ≤8，超限是切分错误信号；**目录可读性**——父图不展开即可读，嵌套 ≤3~4 层；**不跨层寻址**——数据只走声明端口。
- **策略合并**：框架默认 → 算子默认 → 节点配置 → 白名单内本次覆盖；`enabled=false` 是显式值不会被忽略；未知字段一律拒绝。
- **汇合**：当前实现 `all_active_success`；未选分支标记 SKIPPED，必需输入来自跳过节点且无备用来源 = `MISSING_DEPENDENCY_RESULT`。

## 6. 验证与证据纪律

- **红绿**：先让 `check`/`run`/测试暴露失败，再修实现；测试预期必须有业务规则或已确认样例来源，**禁止改断言迁就实现**。
- **证据**：每个交付附真实运行输出（CLI JSON、测试结果）；框架只信运行证据。
- **诚实边界**：本地内存演练不冒充耐久/高可用；协议替身（`MemoryStateStore` 等）只验证调用协议；平台 A01～A35 未验收的能力按未验收使用。
- 项目内新增测试放 `tests/`，随交付提交；诊断码必须真实触发过。

## 7. 观测与运营

- **采集是框架职责**：每次调用自动产生结构化记录（`attempt_started` / `attempt_finished` / `invocation_completed`），业务代码**零埋点**；基础生命周期记录不可覆盖。
- `metrix` / `log` 代理可选（六参数同签名）：只读最终结果快照、写自己的输出，代理失败不影响业务。
- 记录字段是**打平的**（`record["operatorName"]` 而非 `record["options"]["operatorName"]`）；`durationMs` 在 `attempt_finished`。
- **上层聚合参考**：`examples/trading/ops_report.py` —— 消费记录生成监控指标（调用量/成功率/耗时）与运营汇总（订单/GMV）。生产中该角色由监控/运营平台承载，可靠业务事件走 T10 协议（`EventIntent`）。
- 需要业务原子性的事实不能只靠日志代理——等 T10/T14 的可靠通道。

## 8. 变更与影响分析

```bash
microflow impact trading.project.json --ephemeral --operator trading.order_compose@1
microflow impact trading.project.json --ephemeral --flow pricing    # 子图引用链
```

- 改算子前先看 `staticReferences` / `referencingFlows` / `upstream_flows`——影响面是确定性的图查询，不靠经验猜。
- **静态索引 ≠ 运行利用**："未被引用"不等于"未使用"；运行利用分析属 T15 后续。
- 改配置比改算子便宜：优先用编排/策略配置表达差异；契约变更必须版本化（新 Schema 名），不做原地破坏性修改。

## 9. 常见诊断码速查

| 码 | 含义 | 处置 |
|---|---|---|
| `SPARSE_ARRAY` | 按下标写数组产生稀疏扩展 | 数组整体一次写入 |
| `UNKNOWN_SCHEMA` / `UNKNOWN_OPERATOR` | 引用未注册契约/算子 | 先注册再引用；先 `operators`/`schema` 探测 |
| `SCHEMA_INCOMPATIBLE` | 源与目标类型不兼容 | 修正映射或契约；`UNKNOWN` 警告仍需运行期校验 |
| `MAPPING_CONFLICT` | 映射目标路径重叠 | 拆分目标或合并节点 |
| `INVALID_SIGNATURE` | 非六参数签名 | 按标准签名改方法 |
| `SOURCE_CHANGED` | 注册后源码被改 | 重新 discover + 编译 |
| `REGISTRY_SEALED` | 编译后继续注册 | 新建 Registry |
| `UNSUPPORTED_LOCAL_POLICY` / `_NODE` | 超出本地演练边界 | 属实：换宿主运行时或调整配置 |
| `FORBIDDEN_OVERRIDE` | 覆盖不在白名单 | 从配置层改，不走调用覆盖 |
| `VALUE_LIMIT` / `CONFIG_LIMIT` | 超深度/条目/字节预算 | 缩小数据或分批 |

全量码目录：`microflow diagnostics`。新码必须登记，未登记即实现缺陷（守卫测试强制）。

## 10. VibeCoding 协作要点

给工具（和给同事）的工作方式：

1. **小步**：一个会话一个任务，做完即收口；大任务先拆成"可单步验证"的粒度。
2. **验收先行**：动手前写下可执行的完成判据（check 0 诊断 + run 期望输出 + 测试用例）。
3. **负面清单**（建议写入项目 AGENTS.md）：禁止 Mock/TODO 代替真实实现；禁止修改测试断言让测试通过；禁止把写入声明成 `pure`；所有命令必须附运行证据；先 `capabilities` 探测再使用 CLI。
4. **读的顺序**：README → 本手册 → 平台标准 §6～§10（算子协议）→ `examples/trading/`。
5. **不确定就查，不要猜**：契约看 `schema`，影响看 `impact`，能力看 `capabilities`——框架的 API 面是封闭且全部可读的，猜测是幻觉的来源。
