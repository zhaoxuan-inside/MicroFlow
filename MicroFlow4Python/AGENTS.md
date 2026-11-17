# AGENTS.md —— MicroFlow4Python（后端执行框架）纪律速查

前置阅读：根 `AGENTS.md`、本目录 `README.md`（四步接入 + CLI 回路）、`DEVELOPER_GUIDE.md`。

## 算子六参数契约（违反即拒绝）

```python
def my_operator(input, output, context, metrix, debug, log) -> bool:
    # input: 只读 Map（get_path / 下标）；output: 只写 data 命名空间（output.set("path", value)）
    # True = 业务成功；False = 业务否定（可先 output.reject(code, message) 带原因）
    # 异常自动进 fallback（须显式声明 fallback_capabilities）；无 fallback 异常立即熔断根流程
```

- **effect 三值诚实声明**：`pure` / `read` / `write`——写入型在未具备确认能力的运行时被拒绝接入；禁止把写入声明成 pure。
- 输出只写 `data`；`meta`/`error` 是框架保留命名空间（OUTPUT_CONTRACT_VIOLATION）。
- 金额整数分、时间带时区、禁 pickle 与任意对象。

## 模块注册（discover 的信任边界）

每个 trusted 模块必须暴露 `register(registry)`；只加载项目配置 `modules` 显式列出的文件；注册入口不得执行业务或连接资源。

## 本地运行边界（LocalRuntime）

- 只支持 `operator` / `subflow` / `join` 节点；`route`/`map`/`loop`/`wait` → `UNSUPPORTED_LOCAL_NODE`。
- durability/recovery/idempotency/cache/retry/resource_policy → `UNSUPPORTED_LOCAL_POLICY`。
- write 算子需 `LocalRuntime(allow_write=True)` 显式放行（每次写入产出 `write_effect_invoked` 审计记录）；调度执行仍拒绝 write。
- 本地执行强制 `--ephemeral`：无耐久、无恢复——演练边界不是生产证据。

## 快速上手（scaffold）

```bash
microflow scaffold operator <name> --into ./generated [--with-fallback] [--proxy metrix,log]
microflow scaffold flow <id> --into ./generated --operator <name>@<version> \
  --input-schema <in> --output-schema <out> --module <path 相对项目文件>
# 骨架通过 check 前需要：补 [fill] 段、对齐 input/output 映射——check 的诊断就是补全清单
```

## 诊断码纪律

单一来源 `src/microflow/codes.py`；守卫测试双向校验（raised == catalog）。新诊断码必须先登记再用；`diagnostics` 命令输出完整目录。常见码速查见 DEVELOPER_GUIDE §9。

## 实现状态（诚实使用）

- T01–T06 完成；T07–T10 协议切片（内存/单机 SQLite 替身验证，不是生产耐久证据）。
- T12 切片：发布落库（`microflow.releases.publish`）+ 按 release_id 装载（`load_release`）——跨机器物化与介质迁移未开始。
- T11/T13–T16 未开始；A01–A35 验收场景全部未验收——**未验收能力不要在生产语义下使用**。

## 测试

```bash
pytest tests/ -q          # 全绿基线 299+；改断言迁就实现是红线
```
