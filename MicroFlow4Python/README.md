# MicroFlow4Python

Python 业务算子与流程框架，核心运行依赖仅为标准库。设计与任务状态见上级 `docs/`。

当前声明 Python >=3.12；实际验证版本逐次记录于实施计划，未运行的解释器不视为已兼容验证。

在本目录使用目标解释器运行：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\microflow.exe --help
.\.venv\Scripts\python.exe -m microflow describe examples/quote.py
.\.venv\Scripts\microflow.exe check examples/quote.flow.json --ephemeral
.\.venv\Scripts\microflow.exe run examples/quote.flow.json quote examples/quote.input.json --ephemeral
```

`describe` 只加载显式列出的可信 Python 文件，输出版本化 JSON。导入与注册代码是可执行代码，注册入口不得执行实际业务或连接业务资源。示例只注册纯计算的报价算子，金额以整数单位表示。

框架默认耐久策略；无合格宿主提供者时不得用于耐久异步或恢复。现有本地内存实现仅用于显式同步 ephemeral 演练，不能作为生产持久化实现。

示例运行输出 `total=3900`。`LocalRuntime` 当前按确定性拓扑顺序执行静态 DAG、子图及 all_active_success 汇合；`run_async` 是对该本地流程的非阻塞等待入口，不返回后台任务接纳。Python 同步方法由线程承载，协程直接等待；二者的业务结果语义一致。

本地执行器不启用耐久、后台异步、恢复、缓存、业务幂等、重试、多资源互斥或动态控制节点，相关配置会在运行前拒绝。超时在检查点和方法返回后判断，不能中断线程或作为硬执行上限；不承诺生产超时隔离。候选快照固定源码字节和 manifest，可校验缺失/损坏；尚不提供耐久发布、迁移或回退。

Python API 示例：

```python
from microflow import LocalRuntime, discover
from microflow.compiler import compile_release
from microflow.values import load_json
from pathlib import Path

registry = discover(["examples/quote.py"])
flows = load_json(Path("examples/quote.flow.json").read_text(encoding="utf-8"))["flows"]
release = compile_release(registry, flows, defaults={
    "durability": "ephemeral", "recovery": {"enabled": False}
})
result = LocalRuntime(release).run("quote", {"items": [{"price": 1200, "quantity": 2}]})
assert result.output["data"]["total"] == 2400
```

状态协调与宿主提供者接口可从 `microflow.coordinator`、`microflow.persistence` 导入。`validate_provider` 校验显式注入对象的协议版本、配置 schema、绑定修订/配置摘要及能力，不负责创建提供者。固定控制请求必须提供 `request_id` 和完整命令的 `request_digest`；重复请求返回已保存结果。提交结果未知期间，协调器拒绝继续写入并查询原请求。

`microflow.testing.MemoryStateStore` 是有界内存协议替身，供单元测试使用；不提供耐久确认、租约到期或跨进程恢复。分页查询固定首个视图的修订号；取得续页游标后，读取完成仍需调用 `close_cursor` 释放快照。当前 LocalRuntime 尚未连接该状态协议，耐久运行仍在实施中。最新范围与测试证据见 `docs/implementation-plan.md`。

`microflow policy-schema`（也可运行 `python -m microflow policy-schema`）输出策略专用的版本化字段描述、默认值和合并规则。使用 `microflow.policy.describe_policy()` 获取独立 JSON 副本；`validate_policy()` 可在宿主中校验部分配置层，`resolve()` 继续检查生效策略的安全组合和提供者能力。每层配置均须有效，后层覆盖不掩盖前层错误。

顶层 `checkpoint_policy` 可取 `operator`（默认）或 `explicit`，其恢复边界见算法设计 §15；调度实现仍待接入。编译 API 可指定 `source_file`，环/未知依赖诊断包含具体配置字段位置，Graph.edge_sources 保留重复依赖的各个来源。动态节点仍不能交给 LocalRuntime 执行。

`microflow.scheduling.ExecutionCommands` 提供静态算子 DAG 的接纳、领取、完成、取消及查询状态命令，复用 Coordinator 原子提交；不会调用业务方法或启动后台工作者。结果、后继 READY、根停止闩锁和事件意图同批保存。失败后等待已领取分支收敛，迟到成功不推进后继；过期拥有者/attempt_epoch 不能覆盖状态。

生产模式要求耐久协调器，宿主还须接入发布产物保存和恢复协议。`protocol_test=True` 仅供内存协议验证，返回值明确标记为 ephemeral。工作执行入口见下文，完整生产耐久性仍未验收；LocalRuntime 不变，写入型算子及未支持策略在新命令层拒绝。完整边界见算法设计 §16～17 和实施计划 T08。

`from microflow import ScheduledRuntime` 可将状态命令连接到本进程工作执行器。用 `async with ScheduledRuntime(commands, workers=4) as runtime` 管理服务：`await runtime.submit(..., request_id=...)` 返回接纳；`await runtime.wait(execution_id, timeout=...)` 返回实际终态；`await runtime.run(...)` 组合两者。等待超时或调用方取消等待不取消已接纳工作，显式取消使用 `runtime.cancel`。同步方法使用有界业务线程池，协程及等待不占业务线程；结果提交先于可选采集。

纯计算示例：在本目录执行 `.venv/Scripts/python.exe examples/scheduled_quote.py`，输出 `total=3900` 并明确标记 `protocol_test=true`、`durability=ephemeral`。示例展示服务流程，不作为生产耐久性证据。

当前工作执行器只支持状态命令层已允许的静态算子 DAG。旧 CLAIMED 或完成提交故障会阻断执行，`runtime.blocked` 可查询原因，不自动重跑业务。`close` 排空工作，不能硬中断不返回的线程。队列/尝试/流程预算已接入状态检查，CPU 进程池、硬隔离、业务检查点、自动恢复和真实提供者验证仍待实施，详见算法设计 §17～18。

调度执行的 `queue` 从节点 READY 开始，`attempt` 从领取授权开始，根 `deadline` 在接纳时固定。超时通过状态命令原子记录；未领取的队列任务明确失败，在途任务保持 CLAIMED/STOPPING 并请求协作取消，直到实际返回再收敛。迟到成功 data 保留在节点结果中，根不会因此恢复成功或继续派发。

状态格式现为 `microflow-execution-state-v2`，v1 记录须显式迁移，不能用当前时间重置预算。默认预算时钟结合墙钟与单调经过时间防止进程内回拨延长预算；注入时钟和跨主机校时要求见算法设计 §18。计时器不提供硬线程终止能力。

业务幂等现已接入状态命令和 ScheduledRuntime 的纯计算/读取切片。节点启用 `idempotency.enabled` 后，宿主须用 `microflow.idempotency.OperationScope` 向 ExecutionCommands 注入 `operation_scopes={operator_ref: scope}`；业务范围在接纳时固定，键路径只允许引用映射后的 `input` 字段。默认关闭幂等的纯计算仍按不同逻辑调用分别执行，不把所有相同输入自动当作同一业务请求。

同业务键处理中只等待原操作，确认结果复用但生成新的调用元数据；异输入/语义摘要冲突、旧结果不满足新契约或保留期结束均不会再次执行业务。记录与领取/完成同批提交，缓存淘汰不删除业务身份。

新拥有者可用 `commands.mark_in_doubt(..., expected_revision=...)` 将旧代际的失联 CLAIMED 隔离为未知，保留真实结束时间为空；该命令不确认外部结果、不授权重跑。写入型算子、真实外部查询提供者、资源租约和自动恢复仍待集成，见算法设计 §19～20。当前没有自动清除原执行、operation 或命令回执数据的保留清理器。

`microflow.confirmation.ConfirmationService(commands, authorizer=..., verifier=...)` 提供未知结果的授权证据确认接口。调用 `confirm(operation_id, evidence, principal=..., request_id=..., expected_revision=...)`；evidence 为绑定原业务请求/尝试的 ConfirmationEvidence。宿主授权器返回绑定目标摘要和有效期的 ConfirmationGrant，证据查询器只能读取现有业务事实并明确返回 True。两者均须显式注入，没有默认放行实现；查无结果不等于确认失败。

确认结果、账本、事件和审计原子提交，重复请求重新授权但不重复确认。查询在协调器锁外完成，提交前重新检查修订和授权到期。原执行停止状态和跳过的后继保留，不自动继续或重跑业务；后续新逻辑调用可复用已确认结果。当前仅验证内存协议，生产授权、证据保存及外部结果最终性由宿主按 D03/D04 接入。

`microflow.events.EventIntent` 和 `MemoryEventStore` 提供可靠业务事件的协议测试切片。事件固定 `event_id`、聚合键/连续序号、schema、执行来源和不可变 payload；`append` 对同一事件安全去重，`acknowledge` 以摘要确认投递，`pending` 返回有界待投递意图。生产事件提供者仍需与 StateBatch、投递重试、消费凭据、权限和保留策略集成。
