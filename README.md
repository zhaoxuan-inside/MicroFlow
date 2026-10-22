# MicroFlow

MicroFlow 是一个以 Python 标准库为核心的业务算子与流程执行框架。它把算子契约、静态流程编译、状态协调、预算控制、业务幂等和故障边界定义成可验证的协议，再由宿主注入持久化、授权、事件投递和外部资源提供者。

项目当前处于框架协议实施阶段。纯计算的本地同步流程、静态调度命令、进程内工作执行、业务幂等、未知结果确认、资源租约和事件意图已经有实现与测试；生产持久化介质、跨进程接管、真实外部副作用、事件投递和硬隔离仍需要宿主提供者与部署验证。

设计基线和逐项证据见 [项目文档](docs/README.md) 与 [实施计划](docs/implementation-plan.md)。Python 包的详细 API 说明见 [MicroFlow4Python/README.md](MicroFlow4Python/README.md)。

Flutter 前端框架位于 [MicroFlow4Flutter/README.md](MicroFlow4Flutter/README.md)，当前提供项目模型、运行时导航、Flutter Renderer 入口、Debug 快照、Telemetry 收集和外部实验 Provider 契约。

## 快速开始

要求 Python 3.12 或更高版本。仓库内的主要验证使用 CPython 3.14.5rc1，包括 free-threading 构建。

```powershell
cd MicroFlow4Python
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\microflow.exe --help
```

运行报价示例：

```powershell
.\.venv\Scripts\microflow.exe describe examples/quote.py
.\.venv\Scripts\microflow.exe check examples/quote.flow.json --ephemeral
.\.venv\Scripts\microflow.exe run examples/quote.flow.json quote examples/quote.input.json --ephemeral
```

示例输出的报价总额为 `3900`。`--ephemeral` 明确表示本地内存演练，不提供耐久执行保证。

## 核心接口

本地同步执行使用 `LocalRuntime`：

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
result = LocalRuntime(release).run(
    "quote", {"items": [{"price": 1200, "quantity": 2}]}
)
assert result.output["data"]["total"] == 2400
```

需要状态协议时，宿主使用 `Coordinator`、`ExecutionCommands` 和 `ScheduledRuntime`。接纳、领取、完成、取消、预算到期、根停止闩锁、后继就绪和事件意图通过 `StateBatch` 原子提交。`ScheduledRuntime` 支持有界同步线程、协程、非阻塞等待和排空；等待者超时不会取消已接纳的业务执行。

启用业务幂等后，使用 `microflow.idempotency.OperationScope` 固定租户、业务域、操作和业务键。相同业务键只保留一个物理操作；结果确认后可在契约兼容且保留期内复用，冲突或未知状态不会静默重跑。

对于失联后的 `IN_DOUBT` 操作，宿主可注入 `ConfirmationAuthorizer` 与 `ConfirmationVerifier` 使用 `ConfirmationService` 提交授权证据。确认会重新检查原发布、绑定、业务范围、CAS 修订和授权期限，并将节点结果、账本、事件和审计同批提交；原执行停止状态不会被自动解除。

资源约束使用 `LeaseRequest` / `ResourceLease`，资源键必须唯一且按字典序申请。`EventIntent` 提供稳定事件身份、聚合序号、内容摘要和 PENDING/DELIVERED 意图；实际租约服务和事件投递器由宿主注入。

## 边界

- 注册入口会执行可信 Python 代码，不是沙箱；不要在注册阶段连接业务资源或启动后台任务。
- `LocalRuntime` 不支持耐久后台执行、恢复、动态控制节点、自动重试、缓存和真实资源互斥。
- `protocol_test=True` 只允许内存协议替身，返回结果会标记为 ephemeral。
- 框架不把状态存储与外部业务资源变成全局事务，也不宣称任意副作用恰好一次。
- 真实提供者必须自行实现持久化、所有权隔离、授权、外部结果查询、事件投递、租约心跳和部署故障处理。

## 验证

在 `MicroFlow4Python/` 执行：

```powershell
\.venv\Scripts\python.exe -m unittest discover -s tests -q
$env:PYTHONPATH = "src"
py -3.14t -m unittest discover -s tests -q
\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir dist
```

最近一次协议回归为 214 项测试通过；独立 wheel 环境也已验证。测试使用内存替身和纯计算算子，不等同于生产介质、跨主机恢复或性能验收。

## 文档

- [设计文档索引](docs/README.md)
- [平台标准设计](docs/design/platform-standard-design.md)
- [技术选型](docs/design/technical-selection.md)
- [算法与一致性设计](docs/design/algorithms-and-consistency.md)
- [实施计划与验证记录](docs/implementation-plan.md)

## Flutter 前端验证

```powershell
cd MicroFlow4Flutter
flutter analyze
flutter test
```
