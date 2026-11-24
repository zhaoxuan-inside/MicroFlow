# MicroFlow4Registry —— 注册与策略元数据上报

MicroFlow 的**注册面**：把"已发布的快照"投影成平台可消费的元数据，并按内容摘要幂等登记。

它**不是**服务发现：没有心跳、没有地址注册、没有实例健康探活。它的全部工作是把框架已经算出来的事实
（`release_id`、算子目录、契约、策略 schema 摘要）搬到支撑平台，且**只搬运、不重算**。

零三方依赖，Python >= 3.12；与 `MicroFlow4MCP` 同型——都是框架外的协议适配层，内核不感知它。

```bash
pip install -e MicroFlow4Registry
microflow-registry export <project.json> --namespace opchub --group dev --ephemeral
microflow-registry push report.json --endpoint http://127.0.0.1:3000/api/v1/dispatch --token "$TOKEN"
microflow-registry status --json
```

## 一、定位与边界（为什么是独立包）

注册是"框架事实 → 平台投影"的一次搬运，生命周期与内核不同：

| 关切 | 归属 | 原因 |
|---|---|---|
| 算子契约、`release_id`、策略合并语义 | 内核（已有） | 唯一真相，注册包**不得重算** |
| 搬运形状（信封、寻址键、幂等） | 本包 | 协议演进不牵动框架版本 |
| 登记去向（目录/审批/看板） | 平台（已有） | `orchestration.catalog.*` + 控制面 REST |

硬约束（违反即实现缺陷，见 `AGENTS.md`）：

1. 只允许 `subprocess` 调 `microflow <cmd>`，**禁止 import microflow**；
2. 禁止解析算子源码、禁止自行合并策略四层——策略只上报**摘要**；
3. 上报失败不影响 `check/run/test`，退出码 `2`，不静默降级、不无限重试；
4. 缺失项显式 `missing`，禁止默认值填充；
5. 同 `dataId` 异摘要**拒绝**（不覆盖）；
6. 无心跳、无服务发现。

## 二、借鉴的设计原则（Spring Boot / Nacos）

| 原则 | 来源 | 在本包的落法 |
|---|---|---|
| 约定优于配置 + 外部化优先级 | Spring Boot | 配置链：命令行参数 > `MF_REGISTRY_*` 环境变量 > 内置默认；端点默认 `/api/v1/dispatch` |
| 条件装配（能力探测，而非硬编码） | Spring Boot `@ConditionalOn*` | 先读 `microflow capabilities`；缺 `operators`/`check` 等必需命令 → `UNSUPPORTED_COMMAND` 显式拒绝，不猜 |
| 配置错误 fail-fast，运行故障隔离 | Spring Boot 启动语义 | 报告结构/协议错误 → 立即失败；网络/上游故障 → 隔离为退出码 2，本地快照不受损 |
| Starter 思维（可选依赖） | Spring Boot | 内核 `dependencies = []` 不变；本包纯标准库 |
| Actuator 读面（无副作用自述） | Spring Boot Actuator | `status` 只读本地快照与上次推送结果，不做探活 |
| 命名空间 / 分组 / dataId 三元寻址 | Nacos | `namespace`（业务域）· `group`（环境 dev/test/staging/online）· `dataId`（`operator@version`） |
| 元数据附着而非另立注册表 | Nacos instance metadata | capabilities / schemas / 声明式策略作为资产元数据随报告上行 |
| 客户端本地快照 + 服务端不可达降级 | Nacos 客户端缓存 | `export` 先产出确定性快照落盘；`push` 失败保留快照、可重放；同摘要直接短路 `unchanged` |
| 注册即覆盖、按 key 幂等 | Nacos re-register | 同 key 同摘要 = no-op；同 key 异摘要 = 冲突拒绝（对齐 Delivery 同摘要异内容先例） |
| 服务端过载显式拒绝 | Nacos 保护阈值 | 尊重 `429` → `RATE_LIMITED`，默认不自动重试（`--retries` 显式开启） |

## 三、命令面（6 个：2 发现 + 4 工作，表达力刻意做小）

| 命令 | 语义 | `--ephemeral` |
|---|---|---|
| `capabilities` | 本包实现的命令目录 + 所需 CLI 命令（探测替代硬编码） | rejected |
| `diagnostics` | 诊断码目录（单一来源的排序投影） | rejected |
| `export <project>` | CLI 事实 → 确定性报告（stdout，可选 `--out` 落盘） | **required**（触发编译） |
| `push <report.json>` | 报告 → 宿主 dispatch，幂等登记 | rejected（不编译） |
| `stream [batch.json]` | 事件批 → outbox → 宿主 dispatch（`--replay` 补发） | rejected（不编译） |
| `status` | 本地快照/发件箱与上次推送结果（只读，不做探活） | rejected |

统一信封：`microflow-registry-v1` + 命令专属键；退出码 `0` 肯定 / `1` 对象否定（冲突、门禁否定）/ `2` 请求失败。

### export

```bash
microflow-registry export project.json --namespace opchub --group dev --ephemeral
```

内部三步，全部只读：

1. `microflow capabilities` → 条件装配（缺命令即拒绝）+ 记录实现版本；
2. `microflow check <project> --ephemeral` → **门禁**：诊断非 0 即 `PROJECT_CHECK_FAILED`（exit 1）；
3. `microflow operators <project> --ephemeral` + `microflow policy-schema` → 资产与策略摘要。

报告形状（`generatedAt` 仅在 `--stamp` 时出现，且不参与摘要，保证默认字节确定）：

```json
{
  "protocol": "microflow-registry-v1",
  "namespace": "opchub",
  "group": "dev",
  "source": {"implementation": "python", "implementationVersion": "0.1.0",
             "cliProtocol": "microflow-cli-v1", "commands": ["check", "..."]},
  "project": {"digest": "sha256(project.json bytes)", "releaseId": "5f14…",
              "durability": "ephemeral", "flows": ["main"]},
  "assets": [{
    "kind": "operator", "dataId": "increment@1", "ref": "increment@1", "version": "1",
    "digest": "sha256(资产事实)",
    "inputSchema": "ints", "outputSchema": "ints",
    "capabilities": {"effect": "pure", "idempotency_support": "natural"},
    "declaredPolicy": {},
    "source": {"path": "ops.py", "sha256": "…"},
    "staticReferences": 1, "referencingFlows": ["main"]
  }],
  "policy": {
    "protocol": "microflow-policy-schema-v1",
    "schemaDigest": "…", "defaultsDigest": "…", "mergeDigest": "…",
    "effective": "unavailable",
    "reason": "CLI 未暴露生效策略命令；不重算即不猜测",
    "hint": "需要时由内核新增只读命令，再升级本包投影"
  },
  "diagnostics": [],
  "contentDigest": "sha256(与路径无关的内容投影) → 跨机器幂等键",
  "digest": "sha256(除 meta/digest/contentDigest 外的全文) → 报告完整性"
}
```

两个摘要分工明确：

- `digest` = 整份报告（含 `releaseId`）的完整性校验，`push` 前重新计算，防手改/截断；
- `contentDigest` = 与检出路径无关的内容身份（项目字节 + 资产摘要 + 策略摘要），是**跨机器幂等键**。
  框架的 `releaseId` 哈希的 manifest 以**绝对源码路径**为键（`compiler.py:282`），所以同样代码在不同目录
  会得到不同 `releaseId`——报告把它当真相保留，但不拿它做幂等判断。

`policy.effective = "unavailable"` 是**如实边界**：CLI 只给默认值与合并规则，本包不自行合并四层
（那会造出第二套真相）。等内核补一个只读的生效策略命令，这里才升级。

### push

```bash
microflow-registry push report.json --endpoint http://host/api/v1/dispatch --token "$T"
```

- 载荷：`{scenario:"registry.publish", version:1, payload:{namespace, group, digest, contentDigest, report}, context:{token, tenant_id?, project_id?, env_key?}}`
- 信封：`{code, data, message, trace_id}`；`code==0` 成功，`data.status ∈ registered|unchanged|updated`
- 客户端幂等：本地快照 `contentDigest` 与报告相同且上次推送成功 → 直接 `unchanged`，不发请求（`--force` 可强制）
- 冲突：本地同 `dataId` 不同摘要 → `REGISTRY_DIGEST_CONFLICT`（exit 1），需人工确认版本

### stream

```bash
microflow-registry stream batch.json --endpoint … --token …
microflow-registry stream --replay --namespace opchub --group dev --endpoint … --token …
```

快照回答“发布了什么”，事件回答“刚刚发生了什么”。两者信封刻意不同：

| | 快照（`microflow-registry-v1`） | 事件批（`microflow-registry-stream-v1`） |
|---|---|---|
| 单位 | 全量、可重算 | 有序帧、带序号 |
| 身份 | `contentDigest`（整体） | 每帧 `eventId` + 批次 `contentDigest` |
| 语义 | 幂等覆盖 | **at-least-once**，按 `eventId` 去重 |

帧的 `eventId` 是 **内容派生**（`aggregateKey + sequence + kind + payload` 的 SHA-256），
所以重发同一帧不会产生第二条事实；`runtime_record` 的 id 在加载侧会被重新计算校验，
**改不了**。若来源本身已带身份（框架 `EventIntent`），用 `kind: "event_intent"` 原样保留。

传输可靠性：`outbox` 先落盘再发；成功才 `ack`。失败保持 outbox、退出码 2、默认不重试。
`--replay` 按入队顺序补发（先旧后新，不重排）。

库侧适配器（宿主接 `record_sink` 用）：

```python
from microflow_registry import RecordStream
from microflow_registry.push import resolve_config

stream = RecordStream(namespace="opchub", group="dev",
                      config=resolve_config(endpoint=..., token=...),
                      capacity=1000, flush_size=100, flush_interval=5.0)
ScheduledRuntime(commands, record_sink=stream.accept)   # 同步回调，绝不阻塞业务线程
stream.start()                                          # 后台冲刷线程
...
stream.close()                                          # 停线程 + 最后一次冲刷
```

`accept` 只做“分配序号 + 入有界队列”，不做任何 IO；队列满则**计数丢弃**（`dropped`），
不阻塞、不抛错。落盘/上传/重试全在后台线程，失败只记账（`failed_flushes`）。

## 四、验收标准（机器可判定）

| # | 判据 | 证据 |
|---|---|---|
| A1 | `export` 同输入两次字节完全一致 | `test_export_is_deterministic` |
| A2 | 同一项目换目录：`contentDigest` 与资产摘要不变（`releaseId` 随绝对路径变，如实保留） | `test_digest_stable_across_paths` |
| A3 | 源码内容变化 → 资产摘要变化 | `test_asset_digest_tracks_source` |
| A4 | `check` 有诊断 → exit 1 + `PROJECT_CHECK_FAILED` | `test_export_gates_on_diagnostics` |
| A5 | CLI 缺必需命令 → exit 2 + `UNSUPPORTED_COMMAND`（条件装配） | `test_missing_cli_command_is_rejected` |
| A6 | 同 `dataId` 异摘要 → exit 1 + `REGISTRY_DIGEST_CONFLICT` | `test_digest_conflict_is_rejected` |
| A7 | 网络失败不影响本地快照，exit 2 | `test_push_network_failure_keeps_snapshot` |
| A8 | `429` → `RATE_LIMITED`，不重试 | `test_push_rate_limited` |
| A9 | 同摘要重复推送 → `unchanged` 且零请求 | `test_push_short_circuits_identical_report` |
| A10 | 未配置端点/令牌 → 显式拒绝 | `test_push_requires_endpoint_and_token` |
| A11 | 每个抛出的诊断码都在目录中，且目录无死项 | `test_guard_every_raised_code_is_registered` |
| A12 | 生效策略不可得时如实声明，不填充默认值 | `test_effective_policy_is_declared_unavailable` |
| A13 | 事件批同输入字节一致，帧按 `(aggregateKey, sequence)` 排序 | `test_batch_is_deterministic_and_ordered` |
| A14 | `stream` 推送后 ack，outbox 归零，载荷含批次摘要与帧数 | `test_stream_pushes_and_acknowledges` |
| A15 | 网络失败保留 outbox；`--replay` 按序补发并归零 | `test_network_failure_keeps_outbox_then_replay_drains_it` |
| A16 | 篡改帧载荷或伪造 `eventId` → `STREAM_DIGEST_MISMATCH` | `test_tampered_batch_is_rejected` / `test_forged_event_id_is_rejected` |
| A17 | 超过帧预算 → `BATCH_TOO_LARGE` | `test_oversized_batch_is_rejected` |
| A18 | 同批次摘要重复上报 → `unchanged` 且零请求 | `test_identical_batch_short_circuits` |
| A19 | 缺批次/`--replay`、或寻址与批内不一致 → 显式拒绝 | `test_needs_a_batch_or_replay` / `test_batch_addressing_must_agree_with_flags` |
| A20 | `stream` 拒绝 `--ephemeral` | `test_stream_rejects_ephemeral` |
| A21 | sink 队列满只计数丢弃，绝不抛错/阻塞 | `test_accept_is_bounded_and_never_raises_when_full` |
| A22 | 序号按聚合键单调，不同聚合互不影响 | `test_sequence_is_monotonic_per_aggregate` |
| A23 | 冲刷按 `flush_size` 分块，顺序不变 | `test_flush_sends_chunks_of_flush_size` |
| A24 | 冲刷失败保 outbox、计数；非法载荷被计数而非毒化整批 | `test_failure_keeps_outbox_and_replay_drains_it` / `test_invalid_payload_is_counted_not_raised` |
| A25 | `status` 也列出只有事件流的组（无报告时如实显示 assets=0） | `test_status_lists_stream_only_groups` |

运行：`cd MicroFlow4Registry && PYTHONPATH=../MicroFlow4Python/src python3 -m unittest discover -s tests -t .`（44 项）

## 五、边界声明

- 本包**不**实现服务发现、心跳、实例健康检查——若将来确需，走 `MicroFlow4Kit/HOST_CONTRACT.md` 新增场景，由宿主承载。
- **投递语义是 at-least-once，不是恰好一次**：重发会产生重复帧，消费者必须按 `eventId` 去重。
  框架本身也不承诺全局恰好一次，本包不在这里补一个假承诺。
- `record_sink` 是**同步回调**（框架拒绝协程），所以 `accept` 不做 IO；落盘与上传归后台线程。
  若宿主自行实现出口，必须遵守同一约束，否则会拖慢业务执行。
- 记录里没有可关联的执行标识时，聚合键落到 `unattributed`（计数可见），不猜。
- `registry.publish` / `registry.stream` 的**服务端**（登记落库、目录去重、审批联动）不在本包；当前由宿主
  `extra_scenarios` 或编排控制面实现。未接线时宿主应显式 `501/404`，本包如实转发失败。
- 生效策略（EffectiveOperatorPolicy）暂不可上报；内核补只读命令后升级，属后续切片。
- **框架事实（非本包缺陷）**：`release_id` 的 manifest 以绝对源码路径为键，跨机器/跨目录会变。
  本包用 `contentDigest` 承担可移植身份；若要让框架层面的 release 身份也可移植，应在
  `compiler.py` 规范化源路径键——那属于内核切片，不在本包内私自补救。
- 跨语言（Flutter/TS）复用同一 `microflow-registry-v1` 信封属后续切片。
