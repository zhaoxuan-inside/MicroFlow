# MicroFlow4Delivery —— 交付流水线

应用产物（前端 bundle / 后端服务包 / 模型快照）的**内容寻址仓库 + 环境指针 + 证据门禁**。全周期表 ④ 的承载（设计动机见根目录 [LIFECYCLE.md](../LIFECYCLE.md)）：编排配置下发留 MicroFlow4Orchestration，本平台只管应用产物从构建到环境的推进。

技术：Python ≥3.12；存储 SQLite 单机（全部方法锁串行化，连接跨线程）；REST 面FastAPI。**产物与证据 SHA-256 内容寻址**（与框架 T12 releases.publish、宿主 config_hash 同语义）。

## 语义（与既有平台对齐）

- **证据门禁**（存储层执行，CLI 与 REST 共享判定源）：`spec coverage` 全绿（MicroFlow4Spec 信封，绑定 spec.digest 基线）+ `check` 0 诊断（microflow-cli-v1）+ `verify` 全过（microflow-verify-v1）。
- **环境链** `dev→test→staging→online` 不可跳过：守卫读该产物在上一环境的**通过记录**（per-version 历史证据，对齐编排控制面 E2E 门禁语义）；**回滚 = 旧产物重走 promote、守卫照常**，审计区分 `promote`/`rollback`。
- **第二人审批**：staging/online 每次推进强制 approver，同人禁审是存储层硬校验。
- **审计追加保留**：register/promote/rollback 全部入 append-only 审计，无删除路径。

## 命令面

```bash
pip install -e MicroFlow4Delivery   # 或 pip install -e ".[test]"
delivery --store store.sqlite3 register --kind web_bundle --artifact bundle.bin \
    --spec-coverage coverage.json --check-report check.json --verify-report verify.json --by builder
delivery promote <artifact-id> dev --actor alice
delivery promote <artifact-id> staging --actor alice --approver bob
delivery pointers && delivery audit
```

退出码：0 肯定 / 1 门禁否定（`gates[]` 逐门禁原因）/ 2 请求失败（证据信封损坏、未知引用、文件不可用）。信封 `microflow-delivery-v1`；时间戳来自真实事件。

## REST 面

`create_app(store)`：`GET /api/v1/artifacts|pointers|audit`、`GET/POST /api/v1/artifacts/{id}(/promote)`。信封 `{code, data, message, trace_id}` 与宿主契约同形；门禁否定 → HTTP 409（`GATE_REJECTED` + 逐门禁原因）。

## 边界声明

- 产物登记（含大文件）走 CLI 本地通道；REST 面承载团队推进工作流，不做 blob 上传。
- 单机 SQLite 是协议验证介质，不冒充跨主机高可用存储（对齐 SCALABILITY.md 纪律）；生产介质经提供者契约演进。
- 部署执行（把产物落到某台机器）是宿主扩展点（部署清单 + 脚本钩子），本平台不内嵌容器编排。
