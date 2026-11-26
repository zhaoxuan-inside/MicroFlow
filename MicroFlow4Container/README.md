# MicroFlow4Container —— 业务容器适配器参考实现

把控制面 ↔ 业务容器 ↔ 宿主之间**全部悬空的线**接上：这是"整套"里唯一缺的参考实现。

宿主参考实现（MicroFlow4Host）消除过一次"宿主契约人人从零自写"的断链；本包是第二次——
**容器侧**的断链：编排控制面的下发/执行/上报通道此前只有推送端（lifecycle.py），接收端靠部署方
从零自写。本包给出可运行起点。

```bash
pip install -e ../MicroFlow4Python -e ../MicroFlow4Registry -e .
microflow-container serve --project ./examples/demo/project.json --env dev \
  --host-endpoint http://127.0.0.1:3000/api/v1/dispatch --host-token <token> \
  --control-url http://127.0.0.1:8200 --control-token <service-token> --port 8100
```

## 一、通道全景（与控制面/宿主逐字对齐）

```text
编排控制面 :8200                          本容器                        宿主网关 :3000
────────────────────  下行 ──────────────────────────────────────────
POST /container/configs         →  config_hash 重算校验；canvas 骨架转 flow 摘要
POST /container/debug           →  逐算子上报开关
POST /container/execute/scenario→  ScheduledRuntime 真耐久执行（SQLite 介质）
POST /container/operators/register →  内核契约校验（必须 register(registry)）
POST /container/operators/execute   →  schema 必填字段直通的显式演练（ephemeral）

────────────────────  上行 ──────────────────────────────────────────
启动自注册  POST /api/container/register-operators   （算子目录 → 控制面）
debug 上报  POST /api/container/report-node-io        （status/duration 真实；I/O 如实 None）
事件投递    registry.stream → 宿主 registry_events    （经 RecordStream，at-least-once）
意图翻账    coordinator.acknowledge_event            （经 EventPump，pending → DELIVERED）
```

## 二、关键约定（都是既有契约的正面用法，不是新发明）

| 约定 | 来源 |
|---|---|
| 可执行定义住容器本地项目，`flow.id == scenario_code` | platform_graph：canvas 节点禁止携带 inputs，下发的是控制骨架 |
| 容器用自己的 `binding_id` 覆盖项目 `defaults.persistence_binding` | scheduling 的 BINDING_MISMATCH 语义——真耐久执行必须声明介质绑定 |
| 推送算子必须定义 `register(registry)` | 内核装载契约，scaffold 生成的就是该形状 |
| 单算子试跑走 ephemeral（LocalRuntime），不污染耐久状态 | CLI `run --ephemeral` 同款语义 |
| debug 上报的 inputs/outputs 为 None | 框架生命周期记录不含 I/O 转储，不伪造 |

## 三、装配（wiring.py：一次接成）

```text
SQLite StateStore（内核 provider） ── Coordinator(durable) ── ExecutionCommands
        │                                │                        │
   record_sink ──────────────▶ RecordStream ──HTTP──▶ 宿主 registry_events
        │                                │                        │
        └── pending_events ──▶ EventPump ──acknowledge_event──▶ 翻账归零
```

- `EventPump`（Registry 包）经回调注入内核读面，**不 import microflow**；
- 启动自注册失败如实计数（`announced.ok=False`），不阻塞容器；
- 控制面上行失败不劫持业务结果（观测面故障隔离）。

## 四、验收（A33–A38，`tests/test_container.py`，7 项全绿）

| # | 判据 |
|---|---|
| A33 | 下发 config_hash 重算校验；篡改拒绝；canvas 骨架真转换（flow_digest + advisory 计数） |
| A34 | 未下发先执行 → 404 语义；下发后真耐久执行 SUCCEEDED，意图 ≥3 条 PENDING |
| A35 | **全链闭环**：执行 → 意图 → 泵 → HTTP → 宿主 → acknowledge → pending 归零；控制面不可达如实记录不阻塞 |
| A36 | debug 上行映射：node_id/status/duration 真实，inputs/outputs None |
| A37 | 违反内核契约的算子代码回滚并如实拒绝；合规代码重建 release，直通映射试跑 n×2=42 |
| A38 | HTTP 面令牌全拒绝（未配置=全拒绝）；业务失败不 500 假成功 |

## 五、边界声明

- 参考实现验证协议正确性，不冒充生产部署证据（替身不算生产证据；生产验证归部署方）。
- debug I/O 的逐算子输入输出转储不在生命周期记录里——那需要内核暴露 I/O 快照端口，属后续切片。
- 宿主侧服务账号（容器长期持有 registry:write 令牌）是宿主扩展点：开发栈里先用登录令牌手动传入。
- compose 尚未纳入本容器（需要令牌接线设计）；手动命令见文首。
