# AGENTS.md —— MicroFlow4Container 纪律速查

## 这个包是什么

业务容器适配器参考实现：接收控制面下发、真耐久执行、上行自注册/debug 上报、
事件投递泵一次接成。它是 MicroFlow4Host 的容器侧对偶——消除"容器契约人人从零自写"。

## 硬约束（违反即实现缺陷）

1. **对齐既契约**：/container/* 的载荷与返回字段逐字对齐控制面 `lifecycle.py`
   （execute 返回 `status/version/final_output/error_message`）；上行对齐 `main.py`。
2. **不发明语义**：flow.id == scenario_code、binding 覆盖、register(registry) 契约、
   ephemeral 试跑——全是既有内核/平台契约的正面用法。
3. **诚实边界**：debug I/O 的 inputs/outputs 如实 None（生命周期记录不含 I/O 转储）；
   控制面/宿主上行失败如实计数，不阻塞业务；未配置令牌全拒绝。
4. **内核经端口注入**：Registry 包不 import microflow；本包负责接线（discover/provider/
   coordinator），传输归 Registry，上行归 control.py。
5. **业务失败不 500**：execute 的异常转成 status=FAILED 的 200 返回（控制面按 status 记账）。
6. reload 必须先释放旧协调器 owner 租约（同 binding_id 重开分区），否则 OWNER_BUSY。

## 测试

```bash
PYTHONPATH=src:../MicroFlow4Python/src:../MicroFlow4Registry/src python3 -m pytest tests -q
```

A33–A38 见 README §四；改 /container/* 载荷必须同步改控制面侧与测试。
