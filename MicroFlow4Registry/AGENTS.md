# AGENTS.md —— MicroFlow4Registry 纪律速查

## 这个包是什么

MicroFlow 的注册面：把**框架已发布的事实**投影成平台元数据，并按内容摘要幂等登记。
不是服务发现，不是心跳，不是第二个真相源。

## 六条硬约束（违反即实现缺陷）

1. **只读投影**：只允许 `subprocess` 调 `microflow <cmd>`；**禁止 `import microflow`**，禁止解析算子源码。
2. **不重算语义**：策略只上报 `schemaDigest` / `defaultsDigest` / `mergeDigest` / 资产 `declaredPolicy`；
   **禁止自行合并四层策略**。生效策略不可得 → `effective: "unavailable"` + 原因 + 提示。
3. **条件装配**：先 `microflow capabilities` 探测；缺命令 → `UNSUPPORTED_COMMAND` 显式拒绝，不猜、不降级。
4. **失败隔离**：网络/上游故障 → 退出码 2 + 诊断码；本地快照必须完好；默认不重试（`--retries` 才重试）。
5. **幂等与冲突**：同 `dataId` 同摘要 = no-op；同 `dataId` 异摘要 = `REGISTRY_DIGEST_CONFLICT`（exit 1），不覆盖。
   幂等键是 `contentDigest`（与检出路径无关），不是 `releaseId`（随绝对源码路径变，属框架事实）。
6. **确定性**：同一输入字节一致；时间戳只在 `--stamp` 的 `meta` 里，且不参与摘要。

## 诊断码纪律

每个抛出码必须登记在 `src/microflow_registry/codes.py`，且目录不得有死项——
守卫测试 `tests/test_guard.py` 扫描源码强制。新增码 = 同时改目录 + 补测试。

## 命令面纪律（对齐八条兼容契约）

- 封闭六个命令：`capabilities` / `diagnostics`（发现面）+ `export` / `push` / `stream` / `status`（工作命令）；
  新增命令必须同时更新 `CAPABILITIES` 与 README。
- 退出码：0 肯定 / 1 对象否定（门禁、冲突）/ 2 请求失败（配置、协议、网络）。
- `export` 触发编译 → 必须 `--ephemeral`；`push`/`stream`/`status` 不编译 → 拒绝 `--ephemeral`。
- 只输出 `microflow-registry-v1` 信封到 stdout；人读信息走 stderr 或不输出。
- `stream` 的批次自带寻址（`namespace`/`group` 参与摘要），命令行只做**一致性断言**，不覆盖。

## 事件流纪律（stream / sink）

1. **at-least-once，不假称恰好一次**：重发会产生重复帧，去重责任在消费者（按 `eventId`）。
2. `accept` 是业务线程上的同步回调：**禁止 IO**、禁止抛错、禁止阻塞；队列满 = 计数丢弃（`dropped`）。
3. 先 `enqueue` 落盘再发；收到 host `code==0` 才 `ack`；失败保留 outbox，退出码 2。
4. `runtime_record` 的 `eventId` 必须内容派生，加载侧重新计算校验；`event_intent` 才允许沿用来源身份。
5. 序号按 `aggregateKey` 单调；无法关联执行的记录落到 `unattributed`，不猜。
6. 时间戳只记录**已知**的（`occurredAt` 可省略），失联不得伪造。

## 不做什么

- 不做心跳/服务发现/实例健康探活（若需要，走宿主契约新增场景）。
- 不暴露审批、不写平台治理面（AI 不当第二审批人）。
- 不实现 `registry.publish` 的服务端；宿主或控制面承载，未接线时如实失败。
- 不引入三方依赖（纯标准库）。

## 开发回路

```bash
PYTHONPATH=../MicroFlow4Python/src python3 -m unittest discover -s tests -v
PYTHONPATH=../MicroFlow4Python/src python3 -m microflow_registry export <project.json> \
  --namespace demo --group dev --ephemeral | python3 -m json.tool
```

验收标准见 `README.md` §四（A1–A24），每条必须有对应测试；测试绿了才算完成。
