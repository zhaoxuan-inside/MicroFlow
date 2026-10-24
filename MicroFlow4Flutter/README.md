# MicroFlow4Flutter

MicroFlow Frontend 的 Flutter Renderer 与运行时（对齐 `docs/design/frontend-framework-design.md` v1.12）。

```text
Project Model → Runtime → Flutter Renderer / Host
                       ↓
             Telemetry / Experiment / Debug（契约面）
```

## 已实现能力（按 §38.2 分级如实声明）

### Level 0 模型与验证核心（已实现）

- 项目模型（§4）：manifest、资源稳定 id、依赖与版本声明；
- 组件 / 元组件契约（§5、§6、§23.2）：props、slots、events、states、布局能力、
  可访问性要求、容器信息面（provides / consumes，§2.8）；
- 声明式节点树（§6）与 Tier A 元组件集（§38.1）；
- 绑定映射资源（§39）+ 结构化表达子集（§37.2）：ref、比较、逻辑组合；
- 导航模型（§9）：路由、edges、可达性与入口检查；
- i18n 资源模型（§42）：locale 注册表、回退链、缺失翻译诊断、t/text 互斥；
- 静态校验器（§18.1 子集）：未注册引用、绑定目标与事件声明、并发策略声明
  （基线 26）、导航可达性/入口、幽灵依赖（基线 16）、i18n 通道互斥（基线 30 部分）；
- 统一诊断码命名空间与注册表（§41）：`mf.<area>.<name>`；
- Token 最小集（§36.2）：颜色 Token 解析进 Flutter 主题与渲染色。

### Level 1 解释运行时（已实现，§13.2 §13.3 解释模式）

- 页面实例生命周期（§2.6 实例语义、§8）：参数、页面状态、实例身份
  （`page_instance_id` / `component_instance_id`，§12.1）；
- 双实例隔离：同一组件定义多实例状态互不影响（§2.6，基线 1）；
- 导航执行：push / replace / back，页面状态随实例销毁（§11）；
- 动作执行（§10 六类的本地子集）：state / navigation / event / ui /
  function / adapter，动作链 `as`/`prev` 结果传递（§39.1）；
- 并发策略执行（§39.1，基线 26）：cancel-previous / supersede / queue / reject-new；
  未声明策略的绑定拒绝重复触发；
- Guard：假值不执行且不是错误（§39，基线 2）；
- 超时进入 `unknown`，不当作"操作未执行"，未知结果不自动重试（§22.1，基线 3、27）；
- 错误边界（§22.1）：捕获进入声明边界并产生诊断；
- Data Contract 运行期子集（§40.3）：输出 Schema 校验失败是类型化错误
  （基线 4）；缓存/陈旧策略字段已建模、执行面待接入。

### Level 2 契约面（协议已定义，实现承载见下）

- Telemetry（§24、§30.1）：事件四分类、信封 Schema 与校验、身份字段分离与
  凭据拒绝、有界队列/丢弃计数/批量/失败反压；标准运营事件族
  （`ops.page.viewed` / `ops.page.left` / `ops.feature.used`）由运行时拦截
  边界**零埋点**产生（基线 29），业务代码手工上报被拒绝；接收端由业务层
  按 Ingest 契约承载；
- Experiment（§24.4、§31）：外部 Provider 提供分配结果，框架校验、冻结到
  实例、停用不改写历史归属（§24.5）；实验曝光事件就绪但**不**内置曝光平台；
- Debug（§29）：本地/预览/生产受控三级、按 grant 授权、快照屏蔽与过期；
- Security（§32 子集）：凭据不入模型/事件/快照，身份哈希化。

## 尚未实现（Sections 状态对照）

- 编译模式（§13.3 编译侧目标产物）；本包当前仅解释模式，按规范单验
  解释模式自身的行为一致性；
- 完整样式片 / 主题覆盖链 / 条件样式（§36.3–§36.6）：Token 只覆盖颜色语义；
- Tier B 元组件（Grid 已含，Tabs/Drawer/Table 待实现）；
- 恢复迁移器、Business Fact 可靠通道、Trusted Types / CSP 等平台级安全面；
- 增量编译与性能预算门禁（§22.2）：指标已建模（Performance Contract
  Schema），未接真实度量管线。

## 使用

```dart
final registry = buildTierAExampleRegistry();
final project = MFProject(
  manifest: const MFManifest(projectId: 'demo', entryPage: 'home'),
  pages: [MFPage(id: 'home', route: '/home', tree: MFNode(...), stateMembers: ['count'])],
  bindingMaps: {'main': MFBindingMap(...)},
);
runApp(MicroFlowApp(project: project, registry: registry));
```

完整可运行示例见 [example/lib/main.dart](../example/)（§44.2 "备忘（Notes）"）。

## 检查

```text
flutter analyze                     # 0 issues
flutter test                        # 一致性基线测试
```

进入 `example/` 可运行最小产品示例：

```text
cd example && flutter run -d chrome
```
