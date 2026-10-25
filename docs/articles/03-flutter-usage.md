# 前端篇：页面即配置——用 MicroFlow Flutter 声明一个交易平台

> 本文是 MicroFlow 系列第三篇（Flutter 前端使用）。前两篇讲了[设计思想](01-vision-and-philosophy.md)和[Python 后端用法](02-python-usage.md)，这篇讲前端：同一个交易平台，页面不是"写"出来的，是**声明**出来的；AI 建页面走的不是自由发挥，而是带门禁的结构化命令面。

## 一、前端代码里最贵的东西，不是 UI

前端项目的腐烂几乎总从同一个地方开始：状态管理散落各处、UI 与业务逻辑纠缠、样式覆盖靠特异性硬堆、埋点代码混在交互里。三个月后没人敢动 `build` 方法。

MicroFlow Flutter 框架的回答是一条铁律：**代码、数据、配置三平面分离**。

- **配置平面**：页面、交互、样式全部是声明式项目模型——数据，不是代码；
- **代码平面**：真正的业务实现（调接口、读写数据）由宿主注册，框架通过契约调用；
- **数据平面**：运行时产生的观测数据，只进采集管道，永不回写模型。

这三平面之间的访问路径是封死的：配置不能携带可执行逻辑（内联函数是静态错误），运行数据不能修改项目模型。前端腐烂的三条主要通道，在架构层面就被焊死了。

## 二、四步声明一个应用

以仓库里的完整示例 `apps/trading_app`（一个类电商交易平台）为例。业务层职责只有四件事，其余全是模型。

### 第 1 步：注册资源（代码平面）

框架自带 Tier A 元组件（Text/Button/Input/Icon/List/Stack 等 12 个）+ Tier B 复杂组件（6 个），渲染由解释器的组件表承载。你要注册的是**真实业务实现**：

```dart
registry.register(
  'adapter', 'adapter.trading.add_cart',
  const ComponentContract(props: {
    'output': TObject(requiredKeys: ['cartCount', 'hint']),
    // 采集注记：声明的事件与参数键进入运营事件，业务代码零埋点
    'telemetry': MFTelemetryAnnotation(
        events: {'success': 'ops.trade.added-to-cart'}, args: ['sku']),
  }),
  MFAdapterImpl((args) async => data.addCart(args['sku'], args['title'], args['unitPrice'])),
  description: '加入购物车',
);
```

注意契约里的两个关键声明：`output` 的 Schema（不符输出是类型化错误，不静默截断）和 `telemetry` 注记——**加购这个动作的运营统计，从此归框架管**。

### 第 2 步：声明页面（配置平面）

页面是一棵纯配置的节点树：

```dart
MFNode(
  id: 'home-row', type: 'Stack',
  props: const {'direction': 'horizontal', 'crossAlign': 'center'},
  children: [
    MFNode(id: 'home-row-title', type: 'Text',
        props: {'text': {'ref': 'item.title'}},
        constraints: const MFSelfConstraint(width: 'fill')),
    MFNode(id: 'home-row-price', type: 'Text',
        props: {'text': {'ref': 'item.priceText'}}),
    MFNode(id: 'home-row-add', type: 'Button',
        props: {'label': {'ref': 'item.actionLabel'}, 'variant': 'primary'}),
  ],
)
```

没有 `setState`，没有回调地狱。交互是**绑定**——也是纯配置：

```dart
MFBinding(
  id: 'home-row-add',
  on: 'home-row-add.press',                              // 事件锚点
  actions: [
    MFAdapterAction(kind: 'adapter', call: 'adapter.trading.add_cart',
        arguments: {'sku': MFRef('item.sku'), ...}, as: 'added'),
    MFStateAction(target: 'cartHint', value: MFRef('prev.added.hint')),  // prev.<as>.<path> 取结果
  ],
  policy: MFPolicy.rejectNew,                            // 并发策略，声明式
)
```

商品列表是声明式 List 绑定：`items` 指向状态，子树里 `item.<field>` 自动获得行数据作用域。样式是 Token 引用（字面量颜色是静态错误），主题走 `extends` 继承重定向，切换只影响新建实例。

### 第 3 步：遥测接收（数据平面）

```dart
final sink = TelemetryLogSink(TelemetryLogStore(kv: kv), CollectionControl(kv: kv));
```

完事。页面浏览产生 `ops.page.viewed`，加购/下单产生注记事件——全部由运行时拦截边界零埋点发射，走信封校验、有界队列、批量落盘。业务代码里没有一行上报逻辑，标准事件族的手工上报甚至是**静态错误**（防止重复统计）。

### 第 4 步：装配启动

```dart
final framework = MicroFlowFramework.create(
    project: project, registry: registry, releaseId: 'trading-app-r1', telemetrySink: sink);
runApp(MicroFlowApp(project: project, registry: registry, runtime: framework.runtime));
```

我们的示例应用测试里验证了完整链路：首页自动加载 5 个商品、搜索过滤、加购提示、下单（会员 95 折，与后端同一套业务语义）、订单页成交金额汇总——以及 `ops.page.viewed` 确实到达了 sink。Flutter analyze 零问题，测试全绿。

## 三、让 AI 建页面：带门禁的命令面

上面是开发者路径。VibeCoding 工具走的是另一条更严格的路：**authoring 命令面**。

工具不能自由改模型——每条结构化命令都过与发布相同的静态校验门禁，失败时项目保持不变：

```dart
final session = MFAuthoringSession(project: base, registry: registry, actor: 'zcode-builder');
session.createPage(pageId: 'home-page', route: '/home', tree: homeTree(), ...);
session.createPage(pageId: 'cart-page', ..., navigationFrom: 'home-page');
session.connectNavigation(from: 'home-page', to: 'orders-page');
session.inspectImpact('home-page');   // 反向索引：这个资源被谁引用
session.undo();                        // LIFO 回滚最近一次修订，审计保留
```

每条命令产生修改前后摘要、影响对象和可回滚修订——**AI 的每次改动都自带审计链**。我们的交易平台示例就是这样建的：3 个页面、5 笔修订、actor 是 `zcode-builder`，门禁逐条生效。工具还能先探测能力目录再干活：

```dart
mfAuthoringCapabilities();  // 协议 mf-authoring-capabilities-v1，声明 7 个命令的参数与返回
```

有个实战教训值得单独讲：**门禁禁止前向引用**。页面的 `onEnter` 绑定必须与页面同批存在，绑定引用的目标节点必须已经就位——新手会觉得"这条门禁真烦"，但正是它保证了**候选项目在任何时刻都是完整可校验的**，AI 不可能制造出"半成品但通过了检查"的状态。绕行通道不存在，这是设计而非限制。

## 四、门禁与基线：验证也是声明式的

框架带了 32 条机器可读的一致性基线（`docs/design/baselines.json`），每条对应可执行测试：双实例隔离、绑定并发策略、超时进错误边界、缺翻译走回退链、实验冻结不改历史……当前 21 条已覆盖、5 条部分覆盖，覆盖表由工具生成。

也就是说，前端的正确性验证同样不靠人眼：改了任何东西，跑一遍测试，基线表告诉你什么被破坏了。配合 `flutter analyze` 零警告的门禁，这就是给 AI 准备的证据链。

## 五、边界

如实声明（框架的价值观之一）：解释模式（Level 1）完整可用；编译模式产物、发布快照构建器、性能预算门禁还在路上（README 有逐条清单）。接收端、实验平台、远程诊断由业务层按责任矩阵承载——框架管协议，不管你的运维选型。

---

三篇到此收尾。回顾整个系列：后端把业务压进算子与配置，前端把页面压进模型与命令面，两端共享同一条哲学——**把二义性压缩到少数设计决策处，让每一次修改都有机器可验证的证据**。仓库里 `examples/trading` + `apps/trading_app` 是一个能跑通全链路的参照：后端 API 在 8310 端口，前端页面由命令面建出来，运营平台从同源日志收集事件。

*如果这个思路对你有启发，欢迎点个赞；更欢迎来仓库提 issue 拍砖——尤其想听听你 在"算子粒度"和"子图切分"上的实战经验。*
