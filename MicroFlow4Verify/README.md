# MicroFlow4Verify —— 端到端验收运行器

GUI 验收的执行器：**声明式脚本**（零可执行逻辑，三平面分离）在真实渲染面执行绑定链/适配器/导航/零埋点事件，产出 `microflow-verify-v1` 证据信封——供 MicroFlow4Spec `verify` 合并、供交付门禁消费。直接打掉"对 GUI 难断言维度系统性回避验证"的痛点：UI 层的"假完成"从此没有解释空间（设计动机见根目录 [LIFECYCLE.md](../LIFECYCLE.md)）。

技术：纯 TypeScript，零第三方依赖；**面中性架构**——runner 只依赖 `VerifySurface` 端口，web 面（`src/surface/web.ts`，唯一 import MicroFlow4Web 的模块）适配 MFRuntime；将来 flutter 面实现同一端口即复用全部脚本与 runner。

## 脚本（scriptVersion 1）

```jsonc
{
  "scriptVersion": 1,
  "title": "登录 → 工作台 UI 路径",
  "steps": [
    { "op": "fill", "node": "username", "value": "alice" },          // 语义 = Tier A input 的 change 载荷 {value}
    { "op": "expect_binding", "expr": {"ref": "state.username"}, "equals": "alice" },
    { "op": "tap", "node": "submit", "event": "press" },             // 事件锚必须为契约已声明事件
    { "op": "expect_route", "page": "home-page" },
    { "op": "expect_binding", "expr": {"ref": "param.user"}, "equals": "alice" },
    { "op": "expect_event", "event": "ops.page.viewed", "payload": {"page_definition_id": "home-page"} },
    { "op": "back" }
  ]
}
```

静态门禁（`vrf.*` 诊断）：断言一律引用 MFProject 已注册锚点——节点不在任何页面树、事件不在类型契约 events、事件不在标准事件族、页面不存在都是**静态错误**；`screenshot` 已声明未实现，同样静态拒绝（诚实边界，不是静默忽略）。

## 命令面

```bash
npm install --no-bin-links        # Samba 共享盘一律 --no-bin-links
npm test                          # vitest run（node 环境；runner 面中性，FakeSurface 全覆盖）
node --experimental-transform-types src/cli.ts run \
  --script verify/login.json --model model/opchub.model.json \
  [--impls host/impls.mjs] [--out report.json]
```

退出码：0 = verdict pass；1 = 断言否定（fail/skipped）；2 = 请求失败（脚本/模型不可读、静态门禁不过——模型先过 4Web MFValidator，0 error 才跑）。

**代码平面**：适配器实现经 `--impls`（ESM default 导出对象，键 = registry id）单独注册——脚本保持声明式，实现归宿主。

## 证据信封（microflow-verify-v1）

`envelope/script/verdict/assertions[]/summary/meta`；逐断言 verdict + fail 时 `detail: {expected, actual}`；确定性边界：verdict 与 assertions 确定性，`meta.startedAt/durationMs` 是时钟性字段（每次运行是独立证据，Spec 对报告整体摘要作证据标识）。面运行诊断透明披露进 `meta.surfaceDiagnostics`，不参与判定——判定只看断言。

## 边界声明

- web 面为运行时语义级（真实 MFRuntime：绑定链/状态/导航/事件）；DOM 渲染断言与截图属真实浏览器切片（Playwright），`screenshot`/`expect_text` 未实现且静态拒绝。
- flutter 面未接入（同一脚本格式 + `VerifySurface` 端口，独立切片）。
- `back` 只回退一步；`replace` 导航、列表 item 上下文 tap 未实现。
