# MicroFlow4Flutter 开发手册

面向两类读者：**应用开发者**（用框架构建产品的业务层）与 **VibeCoding 工具/AI 代理**（经结构化命令面操作项目模型）。本手册是任务导向的操作指南；语义以《前端框架完整设计方案》（v1.12，下称"基线设计"；原文档已归档于 git 历史，要点浓缩于根 README「实现的设计」5.2）为权威，实现分级与边界以 [README](README.md) 的如实声明为准。

## 1. 五分钟心智模型

- **三平面分离（§2.9）**：页面、交互、样式全部是声明式项目模型（配置平面）；业务实现在宿主（代码平面）；运行数据是数据平面——配置不携带代码，运行数据不回写模型。
- **解释运行时**（§13.2）按项目模型驱动 Tier A/B 元组件渲染；页面、状态、绑定、导航都在模型里。
- **观测零埋点（§24.7）**：标准运营事件族与采集注记由运行时拦截边界产生，业务代码不做手工上报。
- **门禁是活的（§2.7）**：一切修改（包括纯配置创建）过同一静态校验；失败时项目保持不变，不存在免门禁通道。
- **实现分级如实声明（§38.2）**：Level 0/1 已实现，Level 2 协议面部分实现——未实现清单见 README，不要按未验收能力开发。

## 2. 环境准备

```text
# 每个包独立分析（模块化原则：依赖单向收敛 model ← runtime ← renderer/observability ← authoring）
cd packages/microflow_model      && flutter analyze && flutter test
# 总包 + 一致性基线测试
flutter analyze && flutter test
# 运行示例应用
# 应用工程由业务层自行创建（见下文「集成与使用」五步）
```

基线覆盖表由工具生成（勿手工编辑）：`dart run tool/baseline_coverage.dart`。

## 3. 两条开发路径

### 路径 A：应用开发者（参照 README「集成与使用」五步）

业务层职责只有四件事（§27 责任矩阵），其余全是模型：

1. **项目模型** `project.dart`：manifest、页面树、绑定图、i18n、Token、导航图——声明式，不携带可执行逻辑。
2. **资源注册** `registry.dart`：Tier A 元组件契约注册（`MFTierA.required`）+ 业务 `function`/`adapter`（§10/§40 契约，含 output Schema）。
3. **适配器实现**：真实业务语义（本机数据/网络调用）；生产部署经 T14 控制面调用后端耐久接口。
4. **遥测接收端**：`mf_platform_store` 的 JSONL 落地 sink（同源运营平台可收集），或自实现 `MFTelemetrySink`。

装配（`main.dart`）：

```dart
final framework = MicroFlowFramework.create(
  project: project, registry: registry, environment: 'preview',
  releaseId: 'app-r1', telemetrySink: sink);
runApp(MicroFlowApp(project: project, registry: registry, runtime: framework.runtime));
```

### 路径 B：工具 / VibeCoding（authoring 命令面，§14）

工具必须先探测再使用（对齐 CLI 命令体系设计兼容契约第 5 条）：

```dart
final caps = mfAuthoringCapabilities();   // 协议 mf-authoring-capabilities-v1
final session = MFAuthoringSession(project: base, registry: registry, actor: 'zcode-builder');
session.createPage(...);      // 每条命令过与发布相同的静态门禁，产生修订审计
session.connectNavigation(from: 'a-page', to: 'b-page');
session.validateProject();    // MFValidationResult
session.inspectImpact('resource-id');   // §4.3 反向索引
session.undo();               // LIFO 回滚最近一次修订；审计保留
```

纪律：结构化命令优先，**禁止绕过门禁直接拼模型后跳过校验**；每条命令检查 `result.ok` 与诊断；运营/缺陷结论经 `registerFinding`（§43.3）按 Schema 回流，自由文本替代是静态错误。

**门禁的前向引用规则（实战教训，务必遵守）**：候选项目逐命令整体校验——

- `onEnter` 引用的绑定 id 必须与页面**同批**存在；
- 绑定的目标节点/导航目标必须**已经存在**（不许前向引用）；
- 因此多页面项目按页面**分批推进**：基础绑定随首页进入，后续页面的绑定随该页 `createPage` 同批 `copyWith` 进候选，导航按钮绑定放最后一批——多页面项目按页面分批推进。

## 4. 页面与交互

**页面骨架**：`MFPage(id, route, tree, stateMembers, onEnter, layerRegions, ...)`。根节点 id 与页面同 id（即 §39 生命周期锚点对象）；节点 id 全项目唯一（绑定锚点按全局 id 解析）。

**节点树**：`MFNode(id, type, props, children, constraints, layer)`——`type` 引用注册契约；`props` 值是字面量、`{'ref': 'state.x'}` 状态引用、`{'ref': 'item.x'}` 列表项作用域或 `{'ref': 'token.x'}` token；文案用 `t: 'app.key'` 走 i18n（与字面量 text 双声明是静态错误，基线 30）。

**绑定**（`MFBindingMap` → `MFBinding(id, on, actions, policy)`），锚点语法 `<node-id>.press` / `<input>.change` / `<page-id>.onEnter`。四类动作按序执行：

```dart
actions: [
  MFAdapterAction(kind: 'adapter', call: 'adapter.trading.add_cart',
      arguments: {'sku': MFRef('item.sku')}, as: 'added'),   // 异步业务调用
  MFStateAction(target: 'cartHint', value: MFRef('prev.added.hint')),  // prev.<as>.<path> 取结果
  MFNavigationAction(target: 'orders-page'),
],
policy: MFPolicy.rejectNew,   // 并发策略：未声明的重复触发是静态错误（基线 26）
```

- **List 声明式绑定**：`props: {'items': {'ref': 'state.xxxItems'}}` + 子树 `item.<field>` 项作用域；项事件上下文自动携带行数据。
- **事件载荷**：`Input`/`Select` 的 `change` 经契约校验进入 `prop.value`。
- **实战教训**：页面 onEnter 的**首动作放异步调用**（function/adapter），同步状态写入放其后——构建期同步触发状态代际通知会在挂载时报错。

**状态层**：`page` / `session` / `product` 三层（§11）；页面成员在 `stateMembers` 声明，未声明的状态引用是静态错误。

## 5. 样式与主题

- **Token（§36.2）**：语义值基础集；**主题（§36.3）**：`extends` 继承 + 仅重定向已有 token（基线 7：切换只影响新建实例）；**样式片（§36.4）**：值只允许 token 引用——**字面量是静态错误**。
- 覆盖链：token < 组件默认样式片 < 页面覆盖 < 产品主题；运行实例按发布冻结。

## 6. 布局

- 自约束（§7.2）：`MFSelfConstraint(width: 'fill' | 'fixed')`；同轴 `fill` 与 `fixed` 并存 → `mf.layout.unsatisfiable`（基线 19）。
- 条件布局（§7.4）必须给默认方案，重复选择器 → ambiguous；显式图层（§7.1）`site-header/footer/content/overlay` 声明归区。
- 平台不支持已引用布局能力时按声明降级并产生诊断（基线 21）——降级要显式声明，不静默。

## 7. 观测、实验与恢复

- **标准事件族零埋点**（§24.7，基线 29）：`ops.page.viewed/left`、`ops.feature.used` 由运行时拦截边界产生；业务代码手工上报标准族是静态错误。
- **采集注记（§24.7，基线 8）**：在 adapter/function 契约上声明 `MFTelemetryAnnotation(events: {'success': 'ops.xxx'}, args: ['key'])`——声明键进入事件 payload，未声明键不进入；事件走完整校验管道。
- **接收端**由业务层承载：开发用 `mf_platform_store` 的 `TelemetryLogSink`（同源 JSONL，运营平台收集）；测试用 `MFInMemorySink`（`delivered` 可直接断言）；生产按 §30.1 协议（批量/压缩/退避/去重）实现。
- **实验/运营变体（§31）**：Provider 四方法接入，停用只停新曝光、不改写历史归属；受控交叉清单外的改写面静态拒绝（基线 32）。
- **恢复（§16.1，基线 27）**：未知结果副作用只进 unknown 台账可查询，不自动重试；快照 toJson/fromJson 支持跨会话。

## 8. 验证纪律

- 每包 `flutter analyze` 0 issues + `flutter test` 全绿后才算交付；总包跑一致性基线测试。
- 一切修改过同一静态门禁：`MFValidator(project, registry).validate()` 的 `ok` 是判定，不靠人眼。
- 诊断码单一来源（§41）：新码必须登记进 `mfDiagnosticRegistry`，守卫测试强制（P5）。
- 基线覆盖表是机器可读的验收面：新增行为应补基线测试并重新生成覆盖表。

## 9. 常见诊断速查

| 诊断 | 含义 | 处置 |
|---|---|---|
| `mf.reg.*`（refDangling 等） | 引用未注册资源/目标不存在 | 先注册资源或先建目标页面（注意前向引用规则） |
| `mf.reg.unknown-field` | 注册清单/节点字段未登记 | 按 §23.2/差异面补契约，删越界字段 |
| `mf.layout.unsatisfiable` | 同轴 fill+fixed 冲突或超空间 | 修正自约束组合 |
| `ambiguous-scheme` | 条件布局选择器重复 | 收敛选择器 |
| `mf.i18n.missing-translation` | 缺失翻译 | 补 i18n 目录（回退链可显示但会上报） |
| 输出 Schema 不匹配（基线 4） | 函数/适配器输出不符契约 | 修实现或修契约——不静默截断 |
| `mf.exp.variant-out-of-scope` | 实验改写越出受控清单 | 先登记改写面 |

## 10. VibeCoding 协作要点

1. **走命令面，不走捷径**：页面增删用 `create_page`/`connect_navigation`（自带门禁与审计）；直接拼模型也必须过 `MFValidator` 并附证据。
2. **先探测**：`mfAuthoringCapabilities()` 拿命令目录；未实现的能力（编译模式、性能门禁、增量构建）不要假设存在。
3. **小步 + 门禁证据**：一条命令一个意图，检查 `MFCommandResult.ok` 与诊断；失败时项目不变，直接改参数重提。
4. **引用先行检查**：新页面引用的资源先注册；绑定的目标先存在（前向引用会被门禁拒绝——这是特性不是缺陷）。
5. **读的顺序**：README（能力分级、集成五步与基线覆盖）→ 本手册 → 基线设计 §2/§7/§11/§14（归档于 git 历史）。
