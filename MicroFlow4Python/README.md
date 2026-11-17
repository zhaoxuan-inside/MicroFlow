# MicroFlow4Python

Python 业务算子与流程框架，核心运行依赖仅为标准库。设计要点见根 [README](../README.md)「实现的设计」5.1（原上级 `docs/` 设计文档已归档于 git 历史）。

**开发入口**：新任务先读 [开发手册](DEVELOPER_GUIDE.md)（面向开发者与 VibeCoding 工具的任务导向指南：开发回路、算子/编排规范、证据纪律、诊断速查）；集成方法见下方「集成与使用」。

## 实现特点

- **零第三方依赖**：包运行依赖为空（`dependencies=[]`），核心仅使用 Python 标准库；经独立 wheel 安装验证 `Requires-Dist` 为 None。
- **契约驱动的算子模型**：六参数 SDK、标准 Output/Schema v1、路径 AST 与受限表达式（无 eval）、确定性编译与来源级诊断定位、静态影响反向索引。
- **协议先行的状态与执行**：`LocalRuntime` 显式同步演练；`ExecutionCommands`/`ScheduledRuntime` 原子状态命令切片。持久化收敛为项目内子模块 `microflow/persistence`（协议端口 + 内置 memory/SQLite 提供者 + 配置工厂，默认内存）；授权器、证据查询器、事件投递与时钟仍为宿主注入端口，能力不足时显式拒绝相关配置而非静默降级。
- **诚实的能力边界**：写入型算子默认拒绝；动态控制节点执行、自动恢复、硬时间隔离等未实现能力在运行前拒绝；协议切片以内存替身验证，不计为生产耐久证据。

协议切片与任务状态记录见下文（原实施计划文档已归档于 git 历史）。

## 集成与使用

本地性能基线可运行 `PYTHONPATH=src python benchmarks/local_runtime.py --requests 1000 --concurrency 20`，输出吞吐量、错误数、实际活跃请求峰值及 P50/P95/P99。可增加 `--delay-ms 10` 用异步计时器模拟每个算子的 I/O 等待；这不模拟数据库或网络。基线仅测当前进程中无持久化的单算子演练，不代表生产服务容量。

四步接入，全部代码可直接复制。当前声明 Python >=3.12（实际验证版本逐次记录于实施记录）；凡触发本地编译或执行的命令必须显式 `--ephemeral`。框架默认耐久策略，无合格宿主提供者时不得用于耐久异步或恢复——本地内存实现仅用于显式同步 ephemeral 演练。

环境准备：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -q   # 全量测试应全绿
```

### 第 1 步：定义算子（契约先行）

新建业务模块（如 `ops.py`）：先注册 Schema，再注册算子——契约与副作用是强制声明，`effect` 必须如实：

```python
def discount(input, output, context, metrix, debug, log):
    total = input["total"]
    payable = total * 95 // 100 if input["vip"] else total   # 金额用整数分
    output.set("payable", payable)
    output.set("saved", total - payable)
    return True

def register(registry):
    registry.register_schema("shop.discount.pass@1", {
        "type": "object",
        "properties": {"total": {"type": "integer", "minimum": 0},
                       "vip": {"type": "boolean"}},
        "required": ["total", "vip"],
    })
    registry.register_schema("shop.discount.result@1", {
        "type": "object",
        "properties": {"payable": {"type": "integer", "minimum": 0},
                       "saved": {"type": "integer", "minimum": 0}},
        "required": ["payable", "saved"],
    })
    registry.register_operator(
        name="shop.discount", version="1", method=discount,
        input_schema="shop.discount.pass@1", output_schema="shop.discount.result@1",
        capabilities={"effect": "pure", "idempotency_support": "natural"},
        description="会员折扣：vip 按 95/100 整数折算")
```

规则要点：六参数签名 `(input, output, context, metrix, debug, log) -> bool`；`True`=成功、`False`=业务否定（写 `output.data` 表达原因）、异常自动进 fallback（无 fallback 则根流程熔断）；`output.set` 只写 `data`，**数组整体写入一次**（按稀疏下标逐元素写触发 `SPARSE_ARRAY`）；注册入口只做声明，不得执行业务、连接资源或启动后台任务。

### 第 2 步：编排配置（业务项目 DSL）

保存为 `shop.mf`：

```python
module("ops.py")

with flow("checkout", input_schema="shop.discount.pass@1",
          output_schema="shop.discount.result@1"):
    operator("price", operator="shop.discount@1", inputs={
        "total": source("flow.input.total", required=True),
        "vip": source("flow.input.vip", required=True),
    })
    output("payable", "nodes.price.output.data.payable", required=True)
    output("saved", "nodes.price.output.data.saved", required=True)
```

数据流走显式路径映射（来源必须以 `flow.input` / `nodes.<id>.output` / `context` 开头）；类型不兼容在编译期报 `SCHEMA_INCOMPATIBLE`，映射目标重叠报 `MAPPING_CONFLICT`。复杂流程用子图分层（`"type": "subflow", "flow": "<子流程 id>"`）——子图与算子遵守同一契约纪律：引用而非复制、接口预算（端口建议 ≤8）、父图不展开即可读。

DSL 是受限声明语言，采用 Python 风格语法，但解析时不会执行文件；不支持任意 Python 语句、变量或函数调用。节点条件可写 `when=eq(path("flow.input.vip"), True)`，也支持 `exists("...")`、`truthy("...")`、`not_`、`all_`、`any_` 和其他比较操作。`source` 支持 `required` 与 `default`。节点声明还可使用 `subflow`、`route`、`join`、`map`、`loop` 和 `wait`，参数沿用现有编译模型；这不改变运行器能力，动态控制节点目前仍不可执行。原 JSON 项目继续兼容；`.mf` 扩展名选择 DSL，其余项目文件按 JSON 解析。

### 第 3 步：编译与执行

CLI（对 AI 工具与脚本最友好）：

```bash
python -m microflow check shop.mf --ephemeral    # 编译校验，0 诊断才继续
python -m microflow run shop.mf checkout input.json --ephemeral
```

Python API（同一语义，`import microflow` 即用）：

```python
from pathlib import Path
from microflow import LocalRuntime, discover, parse_project
from microflow.compiler import compile_release

registry = discover(["ops.py"])          # 只加载显式列出的可信文件
flows = parse_project(Path("shop.mf").read_text(encoding="utf-8"))["flows"]
release = compile_release(registry, flows,
                          defaults={"durability": "ephemeral", "recovery": {"enabled": False}})
result = LocalRuntime(release).run("checkout", {"total": 5498, "vip": True})
assert result.output["data"]["payable"] == 5223
# 调用成功 ≠ 业务成功：业务终态看 result.output["meta"]["status"]
```

`LocalRuntime` 按确定性拓扑顺序执行静态 DAG、子图及 `all_active_success` 汇合；`run_async` 是非阻塞等待入口，不返回后台任务接纳。它不启用耐久、后台异步、恢复、缓存、业务幂等、重试或动态控制节点——相关配置会在运行前拒绝（`UNSUPPORTED_LOCAL_*` 是护栏不是缺陷）；超时在检查点与方法返回后判断，不承诺硬执行上限。

### 第 4 步：影响分析与观测

```bash
python -m microflow impact shop.mf --ephemeral --operator shop.discount@1
```

返回引用节点、涉及流程与上游闭包——改算子前先查影响面（静态投影，"未被引用"≠"未使用"）。执行产生的结构化记录（生命周期事件、耗时、状态）由框架零埋点采集，上层按需聚合为监控/运营投影；需要业务原子性的事实等 T10/T14 可靠事件通道。

## CLI 命令面

CLI 体系依据《CLI 命令体系设计》（八条兼容契约 + 17 命令封闭集合，要点见根 README 5.3；原文档归档于 git 历史；协议 `microflow-cli-v1`）：stdout 只输出确定性 JSON，退出码 0=肯定/中性、1=被验证对象否定、2=请求失败；凡触发本地编译或执行的命令必须显式 `--ephemeral`。工具应先 `microflow capabilities` 探测命令目录再使用。

| 命令 | 状态 | 用途 |
|---|---|---|
| `capabilities` | 已实现 | 实现标识、版本与命令目录（能力探测） |
| `diagnostics` | 已实现 | 诊断码注册表（`microflow-diagnostics-v1`；未登记码即实现缺陷，守卫测试保证） |
| `describe <files...>` | 已实现 | 显式可信文件 → 版本化注册表 |
| `check <project> --ephemeral` | 已实现 | 编译与静态校验 |
| `run <project> <flow> <input> --ephemeral` | 已实现 | 本地同步执行 |
| `policy-schema` | 已实现 | 策略字段、默认值与合并规则 |
| `policy-check <config>` | 已实现 | 校验部分策略配置层 |
| `impact <project> --ephemeral [--operator REF] [--flow ID]` | 已实现 | 静态影响反向索引与上游闭包 |
| `operators <project> --ephemeral` | 已实现 | 算子目录：契约、能力、默认策略与静态引用计数 |
| `schema <project> <name> --ephemeral` | 已实现 | 单个契约 schema 的版本化定义 |
| `context <project> <operator-ref> --ephemeral [--tests-dir DIR] [--budget N]` | 已实现 | 算子局部上下文（实现摘要/契约/上下游/相关测试/边界声明）——为 VibeCoding 工具设计 |
| `scaffold operator <name> --into DIR [--with-fallback] [--proxy metrix,log]` | 已实现 | 生成算子模块、注册与契约测试骨架（只写 --into，永不覆盖） |
| `scaffold flow <id> --into DIR --operator REF --input-schema NAME --output-schema NAME [--module PATH]` | 已实现 | 生成单流程项目骨架（id/schema 引用/最小节点与输出映射） |

`test`/`preview`/`diff`/`query` 按设计随 T15/T14 后续切片落地。AI 工具可经 [MicroFlow4MCP](../MicroFlow4MCP/README.md) 直接调用以上全部命令（MCP 工具与 CLI 一一对应）。

## 状态协调与宿主提供者

状态协调与宿主提供者接口可从 `microflow.coordinator`、`microflow.persistence` 导入。`validate_provider` 校验显式注入对象的协议版本、配置 schema、绑定修订/配置摘要及能力，不负责创建提供者。固定控制请求必须提供 `request_id` 和完整命令的 `request_digest`；重复请求返回已保存结果。提交结果未知期间，协调器拒绝继续写入并查询原请求。

`MemoryStateStore` 已迁入 `microflow.persistence.memory`（`microflow.testing` 保留兼容 re-export），与 SQLite 提供者通过同一套契约测试（`tests/state_store_contract.py`，T07"实际提供者复用同一套契约"）。分页查询固定首个视图的修订号；取得续页游标后，读取完成仍需调用 `close_cursor` 释放快照。当前 LocalRuntime 尚未连接该状态协议；调度路径经 `ScheduledRuntime.launch` 已可配置化选择持久化（见下节）。最新范围与测试证据见本 README 及 git 历史中的实施计划。

## 持久化子模块与配置

持久化相关功能集中在项目内子模块 `microflow.persistence`：`protocol.py`（`microflow-persistence-v1` 端口）、`memory.py`（默认，ephemeral）、`sqlite.py`（单机耐久）、配置工厂。执行层（runtime/scheduling/worker）只依赖端口、不 import 具体实现，由解耦守卫测试固化。

```python
from microflow import ScheduledRuntime, create_provider

runtime = ScheduledRuntime.launch(release)                                      # 默认内存（ephemeral 演练）
runtime = ScheduledRuntime.launch(release, persistence="memory")                # 显式内存
runtime = ScheduledRuntime.launch(release,
    persistence={"kind": "sqlite", "path": "state.db"})                         # 单机耐久
# 结束后释放 owner 供接管：runtime.commands.coordinator.close()
provider = create_provider("sqlite", {"path": "state.db", "namespace": "billing"})  # 手工组装入口
```

| 提供者 | 耐久 | 边界 |
|---|---|---|
| `memory`（默认） | 否 | 进程内存活；请求耐久配置在运行前被 `CAPABILITY_REQUIRED` 拒绝（护栏非缺陷） |
| `sqlite` | 是（scope="instance"） | WAL + `synchronous=FULL`，确认即已落盘；租约世代 fencing、过期接管；**单实例，不是跨主机高可用介质** |

- kind 是封闭集合 `{"memory", "sqlite"}`，未知 kind 报 `UNKNOWN_PROVIDER_KIND`；配置经版本化 Schema 校验（`describe_provider_config(kind)` 输出字段、默认值与能力声明），配置摘要进入 `StorageBinding`，重启即重开同一绑定。
- 失联恢复钩子：旧 owner 的租约过期后，新 owner 接管且 fencing generation 严格递增；旧 token 的提交被 `OWNER_FENCED` 拒绝。跨进程 fencing 已经子进程演练验证。
- 失联自动重派：`ExecutionCommands.recover(execution_id, request_id=..., expected_revision=...)` 将被 fence 的旧 owner 的 CLAIMED 节点重派——纯/读算子无外部效应，其幂等业务身份废弃重建后节点回 READY（新 claim 递增 attempt_epoch，旧 owner 迟到提交被 `STALE_ATTEMPT` 拒绝）；写入型效果不重派，保留手动 IN_DOUBT 确认路径；当前 owner 的在途尝试不被触碰。`ScheduledRuntime` 泵循环发现非本 runtime 的 CLAIMED 节点时自动调用 recover，纯/读执行无需人工干预即可自愈。
- Redis 不作为 StateStore 提供：无法如实声明 `durable_ack`（AOF/RDB 异步刷盘）与 `consistent_recovery`（无跨键一致快照），按诚实边界不实现、不静默降级；其位置是后续切片的缓存/租约/投递通道。PostgreSQL/MySQL 提供者按同一端口与同一契约测试套件在后续切片接入（驱动走 optional extras）。

## 策略、检查点与影响索引

`microflow policy-schema`（也可运行 `python -m microflow policy-schema`）输出策略专用的版本化字段描述、默认值和合并规则。使用 `microflow.policy.describe_policy()` 获取独立 JSON 副本；`validate_policy()` 可在宿主中校验部分配置层，`resolve()` 继续检查生效策略的安全组合和提供者能力。每层配置均须有效，后层覆盖不掩盖前层错误。

`microflow impact <project> --ephemeral` 构建静态影响反向索引（协议 `microflow-impact-index-v1`）：算子 ref 与被嵌套流程到引用节点 `(flow, node, kind)` 的有序映射、roots 及引用图无环校验；`--operator REF` / `--flow ID` 返回定向引用与上游闭包。Python API 见 `microflow.impact`：`build_index` / `describe_index` / `operator_references` / `operator_flows` / `flow_references` / `upstream_flows`。索引是纯静态投影，"未被引用"不等于"未使用"；运行利用分析仍属实施计划 T15 后续切片。

顶层 `checkpoint_policy` 可取 `operator`（默认）或 `explicit`，其恢复边界见算法设计 §15；调度实现仍待接入。编译 API 可指定 `source_file`，环/未知依赖诊断包含具体配置字段位置，Graph.edge_sources 保留重复依赖的各个来源。动态节点仍不能交给 LocalRuntime 执行。

## 调度执行与状态命令

`microflow.scheduling.ExecutionCommands` 提供静态算子 DAG 的接纳、领取、完成、取消及查询状态命令，复用 Coordinator 原子提交；不会调用业务方法或启动后台工作者。结果、后继 READY、根停止闩锁和事件意图同批保存。失败后等待已领取分支收敛，迟到成功不推进后继；过期拥有者/attempt_epoch 不能覆盖状态。

生产模式要求耐久协调器。内置 SQLite 提供者（`ScheduledRuntime.launch(release, persistence={"kind": "sqlite", ...})`）已打通耐久接纳 → 执行 → 原子提交 → 重启恢复的单实例闭环；发布产物保存、跨实例调度与自动恢复仍待实施。`protocol_test=True` 仅供协议验证，返回值明确标记为 ephemeral。工作执行入口见下文；LocalRuntime 不变，写入型算子及未支持策略在新命令层拒绝。完整边界见算法设计 §16～17 和实施计划 T08。

`from microflow import ScheduledRuntime` 可将状态命令连接到本进程工作执行器。用 `async with ScheduledRuntime(commands, workers=4) as runtime` 管理服务：`await runtime.submit(..., request_id=...)` 返回接纳；`await runtime.wait(execution_id, timeout=...)` 返回实际终态；`await runtime.run(...)` 组合两者。等待超时或调用方取消等待不取消已接纳工作，显式取消使用 `runtime.cancel`。同步方法使用有界业务线程池，协程及等待不占业务线程；结果提交先于可选采集。

同一运行器内多个调用方等待同一个执行时共享状态轮询；任一调用方超时或取消不会取消其他等待者。不同执行仍分别轮询，因此这不代表调度器已满足高并发容量要求。

状态提供者可选实现 `load_record_view(key)`：原子读取该记录及其修订号和绑定修订，返回仅包含目标记录的 `RecoveryView`；不存在时返回空记录。调度查询采用此接口，缺失时回退到完整恢复视图。状态写入、跨记录一致性检查与事件意图提交仍使用完整视图和原子命令。`PYTHONPATH=src python benchmarks/state_query.py --records 500 --queries 200` 可比较内存协议替身的两种读取方式，不代表生产存储性能。

调度器可注入 `record_sink` 同步回调接收每条不可变生命周期记录：`ScheduledRuntime(commands, record_sink=accept_record)`。回调在运行器事件循环中执行，宿主应只做快速、非阻塞的接纳；耗时导出应由宿主的有界队列与独立消费者完成。回调异常不会改变业务结果，`runtime.record_stats` 提供 `generated`、`buffered`、`buffer_evictions`、`sink_configured` 和 `sink_failures`，可用于监控与告警。`buffer_evictions` 只表示本地历史被覆盖，不表示已被出口接纳的记录丢失；回调正常返回也不证明记录已持久化。计数和本地缓冲均为进程内数据，进程崩溃、出口队列满或下游不可用时的可靠投递仍须宿主设计和验证。关键业务事实应使用可靠事件协议，不应仅依赖生命周期记录。

纯计算/读取切片演示了完整服务流程（接纳 → 执行 → 原子提交 → 可选采集），返回值明确标记 `protocol_test` 与 `durability`；不作为生产耐久性证据。

当前工作执行器只支持状态命令层已允许的静态算子 DAG。被 fence 的旧 owner 的纯/读 CLAIMED 节点由泵循环经 `recover` 自动重派（见上节"失联自动重派"）；完成提交故障或同 owner 孤儿尝试仍会阻断执行，`runtime.blocked` 可查询原因，不自动重跑业务。`close` 排空工作，不能硬中断不返回的线程。队列/尝试/流程预算已接入状态检查，CPU 进程池、硬隔离、业务检查点、写入型算子恢复确认和真实提供者验证仍待实施，详见算法设计 §17～18。

调度执行的 `queue` 从节点 READY 开始，`attempt` 从领取授权开始，根 `deadline` 在接纳时固定。超时通过状态命令原子记录；未领取的队列任务明确失败，在途任务保持 CLAIMED/STOPPING 并请求协作取消，直到实际返回再收敛。迟到成功 data 保留在节点结果中，根不会因此恢复成功或继续派发。

状态格式现为 `microflow-execution-state-v2`，v1 记录须显式迁移，不能用当前时间重置预算。默认预算时钟结合墙钟与单调经过时间防止进程内回拨延长预算；注入时钟和跨主机校时要求见算法设计 §18。计时器不提供硬线程终止能力。

## 业务幂等与失联确认

业务幂等现已接入状态命令和 ScheduledRuntime 的纯计算/读取切片。节点启用 `idempotency.enabled` 后，宿主须用 `microflow.idempotency.OperationScope` 向 ExecutionCommands 注入 `operation_scopes={operator_ref: scope}`；业务范围在接纳时固定，键路径只允许引用映射后的 `input` 字段。默认关闭幂等的纯计算仍按不同逻辑调用分别执行，不把所有相同输入自动当作同一业务请求。

同业务键处理中只等待原操作，确认结果复用但生成新的调用元数据；异输入/语义摘要冲突、旧结果不满足新契约或保留期结束均不会再次执行业务。记录与领取/完成同批提交，缓存淘汰不删除业务身份。

新拥有者可用 `commands.mark_in_doubt(..., expected_revision=...)` 将旧代际的失联 CLAIMED 隔离为未知，保留真实结束时间为空；该命令不确认外部结果、不授权重跑。写入型算子、真实外部查询提供者、资源租约和自动恢复仍待集成，见算法设计 §19～20。当前没有自动清除原执行、operation 或命令回执数据的保留清理器。

`microflow.confirmation.ConfirmationService(commands, authorizer=..., verifier=...)` 提供未知结果的授权证据确认接口。调用 `confirm(operation_id, evidence, principal=..., request_id=..., expected_revision=...)`；evidence 为绑定原业务请求/尝试的 ConfirmationEvidence。宿主授权器返回绑定目标摘要和有效期的 ConfirmationGrant，证据查询器只能读取现有业务事实并明确返回 True。两者均须显式注入，没有默认放行实现；查无结果不等于确认失败。

确认结果、账本、事件和审计原子提交，重复请求重新授权但不重复确认。查询在协调器锁外完成，提交前重新检查修订和授权到期。原执行停止状态和跳过的后继保留，不自动继续或重跑业务；后续新逻辑调用可复用已确认结果。当前仅验证内存协议，生产授权、证据保存及外部结果最终性由宿主按 D03/D04 接入。

## 可靠业务事件

`microflow.events.EventIntent` 和 `MemoryEventStore` 提供可靠业务事件的协议测试切片。事件固定 `event_id`、聚合键/连续序号、schema、执行来源和不可变 payload；`append` 对同一事件安全去重，`acknowledge` 以摘要确认投递，`pending` 返回有界待投递意图。生产事件提供者仍需与 StateBatch、投递重试、消费凭据、权限和保留策略集成。
