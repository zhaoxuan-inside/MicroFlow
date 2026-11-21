# AGENTS.md —— MicroFlow4Delivery（交付流水线）

Python 包：`src/delivery/`（store/service/cli/errors）+ `tests/`。门禁语义在**存储层**执行——CLI 与 REST 共享同一判定源，禁止在调用方复制门禁逻辑。

## 架构事实（先查再改）

- `store.py` 是唯一权威：登记（内容寻址 + 证据信封校验）、promote（门禁 + 指针 + promotions 历史 + 审计）、读面。SQLite 连接 `check_same_thread=False`，**全部公共方法经 `self._lock` 串行化**（REST 服务跨线程）——新增方法必须遵守。
- 环境守卫读 `promotions` 历史表（per-version 通过记录），不是当前指针——这是回滚"旧版本重走 deploy、守卫照常"的前提；改动前先读 `test_rollback_rereuns_the_guard_and_is_audited`。
- 门禁否定 = `GateRejected`（exit 1，`gates[]` 逐原因）；请求失败 = `DeliveryError`（exit 2）。两者不得混用：证据信封损坏是 2，证据内容不过关是 1。
- 证据信封契约：spec coverage = `microflow-spec-v1` + `command: "coverage"` + `spec.digest`；check = `microflow-cli-v1`（diagnostics 列表）；verify = `microflow-verify-v1`（verdict）。信封变更须同步 Spec/Verify 侧。

## 纪律

- 时间戳只来自真实事件（`_now()` 在事件发生时取），不参与门禁判定；测试对决策字段断言，不对时钟字段断言。
- 审计 append-only：不提供 UPDATE/DELETE 路径，回滚是新的 promote 事件（`rollback: true`）。
- 同人禁审在存储层硬校验——不要试图在 CLI/REST 层"提前放行"。
- 测试：`python3 -m pytest tests/ -q`（fastapi TestClient）；REST 门禁否定映射 HTTP 409，未知引用 404，参数 422。
