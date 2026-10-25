# MicroFlow4Flutter Apps — 习惯打卡平台 + 运营管理平台

基于 MicroFlow4Flutter 框架（解释运行模式，§13.3）开发的两个纯 Web 前端，
验证「业务声明式建模 + 零埋点运营数据收集 + 管理面消费」的完整闭环。

```text
┌────────────────────────────── 同一浏览器（同源 localStorage） ──────────────────────────────┐
│                                                                                             │
│  habit_tracker（/habit/）                              ops_admin（/admin/）                 │
│  ├─ MFProject 页面树/绑定图/i18n/主题                   ├─ MFProject 六页面/绑定图           │
│  ├─ MFRegistry：真实函数/适配器（打卡 CRUD）             ├─ MFRegistry：运营函数（读共享日志）  │
│  ├─ 运行时拦截边界零埋点（§24.7，基线 29）      事件      │  ├─ MFLocalQueryEngine（§30.2）     │
│  ├─ 采集注记 ops.habit.*（§24.7，基线 8）   ──────────→  │  ├─ 页面/功能/日志/导出/采集控制     │
│  └─ MFTelemetryQueue → TelemetryLogSink（JSONL 落盘）    │  └─ storage 事件 → 实时刷新         │
│                                                          │  （写入采集开关，采集端投递前读取）  │
│  共享存储（mf_platform_store）：                         │                                    │
│   · mf.habits.data.v1      打卡数据（习惯 + 打卡记录）    │                                    │
│   · mf.telemetry.events.v1 遥测 JSONL 日志（容量 5000）   │                                    │
│   · mf.telemetry.control.v1 采集开关                      │                                    │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 模块

| 目录 | 说明 |
|---|---|
| `mf_platform_store/` | 跨应用业务层数据契约：localStorage KV、遥测 JSONL 接收日志（§30.1 接收端业务承载）、采集控制开关、跨标签页通知 |
| `habit_tracker/` | 个人习惯打卡平台：今日打卡 / 习惯管理 / 数据统计 |
| `ops_admin/` | 运营管理平台：运营概览 / 页面分析 / 功能使用 / 日志检索 / 导出与保留 / 采集控制 |

## 运行

```bash
# 各应用独立检查（0 issues）与测试
cd apps/habit_tracker && flutter analyze && flutter test --platform chrome
cd apps/ops_admin    && flutter analyze && flutter test --platform chrome

# 构建 Web 产物
cd apps/habit_tracker && flutter build web --base-href /habit/
cd apps/ops_admin     && flutter build web --base-href /admin/
```

纯 Web 应用统一用 `--platform chrome` 跑测试：浏览器专属测试（真实
localStorage + 完整框架装配）与纯逻辑测试同套件执行。

同源部署（两个应用共享 localStorage 才能构成数据闭环）：

```bash
mkdir -p deploy && cp -r apps/habit_tracker/build/web deploy/habit
cp -r apps/ops_admin/build/web deploy/admin
cd deploy && python3 -m http.server 8090
# 打开 http://localhost:8090/habit/ 与 http://localhost:8090/admin/
```

## 纪律

- 页面、交互、样式、采集注记全部由 `MFProject`/`MFRegistry` 声明；业务代码只出现在注册资源实现（`functions.dart` / `ops_functions.dart`）与框架装配（`main.dart`）。
- 无死代码：每个注册资源都被绑定图调用；每个页面从入口可达；每个状态成员被读写；每条 i18n 文案被 `t` 引用。
- 无桩代码、无 Mock 数据：打卡数据来自用户输入并实时落 localStorage；管理平台的全部指标来自真实采集的事件信封（标准事件族 + `ops.habit.*` 注记事件）。

## 过程中对框架的修复（packages/ 内，均有测试）

1. `microflow_runtime/expression.dart` — `EvalContext.withPrev` 在无 `as`
   的动作后丢弃已命名的适配器结果，违反 §39.1「prev 解析到命名结果」语义；
   多步链 `[adapter as x, state A, state B]` 中第二条状态动作读不到 `prev.x`。
2. `microflow_model/bindings.dart` — `MFExpr.parse` 不接受 MFExpr 实例直通，
   Dart 侧构造的 `props: {'x': MFRef(...)}` 被包成字面量导致不求值
   （属性树应支持 JSON 形式 `{'ref': ...}` 与表达式实例两种入面）。
3. `test/framework_ext_test.dart`（工作树遗留测试）补齐夹具缺失的 Stack 注册。
