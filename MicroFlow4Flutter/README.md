# MicroFlow4Flutter

MicroFlow Frontend 的 Flutter 实现（对齐 `docs/design/frontend-framework-design.md` v1.12）。

## 模块结构（可独立升级）

```text
microflow4_flutter/            总包：装配 + 再导出（MicroFlowFramework.create）
└── packages/
    ├── microflow_model            模型/契约/诊断/i18n/Token   （§4-§11、§36.2、§39、§41、§42）
    │     ↓
    ├── microflow_runtime          注册/静态校验/解释运行时/错误边界（§13.2、§23、§10、§18.1）
    │     ↓                    ↑
    ├── microflow_renderer_flutter     Flutter Tier A 渲染 + MicroFlowApp（§12、§13.3、§38）
    ├── microflow_observability        遥测信封/有界队列/实验冻结/Debug 会话（§24、§29、§31）
    └── microflow_authoring            结构化命令/审计回滚/模板实例化（§14、§19 阶段六）
```

模块化原则（两条硬约束）：

1. **依赖单向收敛**：model / runtime 是零外部依赖的稳定核心；observability
   与 renderer 只依赖 runtime 的公共 API。运行时通过 `MFEmissionSink`
   接口向观测面发射拦截事件（§24.7 运行时是唯一发射点），采集管道可独立
   替换与升级，运行时不感知其实现。
2. **降级单配置总量**：每个模块自带 pubspec（版本、依赖、flutter_lints）、
   独立 analyze；业务层按需依赖，不必将全部能力引入单一配置。遥测接收端、
   实验平台、Debug 远程诊断均由业务层按 §27 责任矩阵承载。

## 各模块职责与导出面

| 模块 | 版本 | 公共 API（节选） |
|---|---|---|
| microflow_model | 0.2.0 | `MFProject/MFManifest/MFPage/MFNode`、`ComponentContract/InfoContract/LayoutCapability`、`MFBindingMap/MFExpr/MFAction`、`MFI18nCatalog`、`MFTokenSet`、`MFTheme/MFStyleSheet/MFStyleResolver`（§36.3-§36.6）、`MFSelfConstraint/MFConditionalLayout`（§7.2-§7.4）、`MFDiag/MFCodes/mfDiagnosticRegistry` |
| microflow_runtime | 0.2.0 | `MFRegistry/MFResourceEntry`、`MFRuntime/MFPageInstance/MFFrozenContext/MFActionResult`、`MFValidator/MFValidationResult`、`MFStateStore`、`MFLayoutSolver/staticLayoutChecks`（§7.3/§7.5）、`MFEmissionSink`、`MFExprEvaluator`、`MFBoundaryHandler` |
| microflow_observability | 0.1.0 | `MFEventEnvelope/MFTelemetryQueue/MFTelemetrySink/MFInMemorySink`、`MFStandardEvents`、`MFExperimentState/MFExperimentAssignment`、`MFDebugSession/MFDebugSnapshot` |
| microflow_renderer_flutter | 0.2.0 | `MFPrimitiveTable/MFTierA/MFInterpreter`、`MicroFlowApp`（含双层主题切换面）、`mfFlutterRendererContract`（§12.1）、`resolveTokenColor` |
| microflow_authoring | 0.1.0 | `MFAuthoringSession`（`createPage/createPageFromTemplate/connectNavigation/validateProject/inspectImpact/undo`）、`MFCommandResult/MFRevision/MFImpactReport`（§14 命令面） |
| microflow4_flutter（总包） | 0.4.0 | 上述全部再导出 + `MicroFlowFramework.create`（校验门禁 + 装配 + themeProvider） |

## 已实现能力（按 §38.2 分级如实声明）

- **Level 0 已实现**：项目模型 / 契约 / 静态校验器 / 诊断注册表 / i18n / Token；
  主题（extends 重定向、完整性检查）、样式片（变体条件、承接链、字面量禁令）、
  覆盖链（token < 组件默认样式片 < 页面覆盖 < 产品主题）、交互与绑定语法静态检查、
  布局约束 Schema 与静态检查（§36、§37、§7.2-§7.5 静态面）；
- **Level 1 已实现（解释模式）**：页面实例 / 导航 / 状态层 / 绑定映射 /
  并发策略 / guard / 超时 unknown / 错误边界；Tier A 元组件渲染 + Tier B
  Tabs/Drawer/Table/Grid；覆盖链按实例冻结主题渲染（基线 7）；§7.3 布局
  求解为确定性纯函数基线（`MFLayoutSolver.solveStack`，尚未接入 Flutter
  渲染路径——渲染走原生 Row/Column，求解语义由基线 18-21 固定）；
- **Level 2 协议面已定义并部分实现**：遥测信封 Schema 校验与有界队列、
  标准运营事件族零埋点（`ops.page.viewed/left`、`ops.feature.used`）、
  实验分配校验冻结停用、Debug 权限门与快照屏蔽；接收端服务、实验平台、
  远程诊断仍由业务层/承载方实现（§27）。
- **阶段六最小闭环（§14/§19）**：结构化命令 `create_page`、
  `create_page_from_template`、`connect_navigation`、`validate_project`、
  `inspect_impact`；候选项目过同一静态校验门禁，失败不改模型；
  修改审计（前后摘要/影响对象/主体）与可回滚修订；页面模板参数化实例化。

尚未实现（对照设计章节）：编译模式产物（§13.3 编译侧）、Tier B
Split/Anchor、§36.5 动效面、Recovery 执行器（§16.1）、Business Fact 可靠
通道（§24.1 第 4 类）、Telemetry Ingest 参考实现与 Query/Export（§30）、
增量编译与性能预算度量管线（§22.2）。

## 一致性基线覆盖（机器可读）

基线单一来源为 [`docs/design/baselines.json`](../docs/design/baselines.json)（§44.3 的机器可读投影，
不引入新语义）。测试名称以「基线 N」标记覆盖条目，「部分」后缀表示仅覆盖可静态/本地判定子集；
守卫测试保证引用合法与诊断码单一来源（§41.3）。覆盖表由工具生成，勿手工编辑：

```text
dart tool/baseline_coverage.dart
```

| 基线 | 条目 | 覆盖状态 | 测试 |
|---|---|---|---|
| 1 | 双实例隔离：同一组件定义多次实例化互不影响 | 已覆盖 | `运行时：启动、双实例隔离、导航与标准事件族零埋点产出（基线 1、29）` |
| 2 | guard 为假时绑定不执行且不报错 | 已覆盖 | `绑定执行：guard 为假不执行且不报错；状态写入触发 generation（基线 2）` |
| 3 | 适配器超时进入错误边界并产生 mf.data 超时诊断，不当作未执行 | 已覆盖 | `动作函数：注册、调用、超时进入 unknown 不当作失败（基线 3、27）` |
| 4 | 输出 Schema 不匹配产生类型化错误，不静默截断 | 已覆盖 | `输出 Schema 不匹配产生类型化错误，不静默截断（基线 4）` |
| 5 | 缺失翻译按回退链展示并上报 mf.i18n.missing-translation | 未覆盖 | — |
| 6 | 注册实现与契约不符是运行错误并进入错误边界 | 未覆盖 | — |
| 7 | locale/主题冻结：运行中切换只影响新建实例 | 已覆盖 | `基线 7：locale/主题冻结——切换只影响新建实例`<br>`实验冻结：停用不改写历史，运行实例读取冻结值（基线 7）` |
| 8 | 采集注记事件走完整校验管道，业务代码零埋点 | 未覆盖 | — |
| 9 | 解释模式与编译模式对上述行为完全一致 | 未覆盖 | — |
| 10 | 发布快照可重复构建、可回滚，诊断码可用注册表版本解释 | 未覆盖 | — |
| 11 | 追踪传播携带外部运行引用；未获得运行引用的确认进入 unknown | 未覆盖 | — |
| 12 | 页面未声明图层树时以隐式 ContentLayer 校验与渲染 | 已覆盖 | `基线 12：隐式 ContentLayer 共存规则` |
| 13 | 纯配置创建引用未注册资源时校验失败；通过后以新发布快照运行 | 已覆盖 | `注册/未注册引用检查（基线 13、15）`<br>`未注册类型引用是静态错误（基线 13）`<br>`create_page 纯配置构造：门禁拒绝未注册引用且项目不变（基线 13、§18.3）` |
| 14 | manifest 类型方言版本可解析快照内全部 Schema 引用；不满足时构建失败 | 已覆盖 | `manifest 类型方言版本不受支持时构建失败（基线 14）` |
| 15 | 统一注册 primitive/adapter 后纯配置构建新页面通过校验并正确渲染 | 已覆盖 | `注册/未注册引用检查（基线 13、15）` |
| 16 | 容器信息契约：consumes 不可解析是静态错误；provides 变更可经影响分析命中全部消费容器 | 部分覆盖 | `容器信息契约：consumes 解析到上游 provides；provides 变更命中影响分析（基线 16 部分）` |
| 17 | findings 按 schema 版本回流并可被回归基线消费；自由文本替代是静态错误 | 未覆盖 | — |
| 18 | 布局求解确定性：同一约束输入产生相同规范化矩形集 | 已覆盖 | `基线 18：同一输入两次求解（等价解释/编译模式）产出相同规范化矩形集` |
| 19 | 不可满足约束产生 mf.layout 静态错误并阻止构建 | 已覆盖 | `基线 19：同轴 fill 与 fixed 并存 → mf.layout.unsatisfiable；fixed 超出可用空间` |
| 20 | 条件布局命中声明方案；全不命中且无默认方案是静态错误 | 已覆盖 | `基线 20：条件布局确定命中与默认方案；重复选择器 → ambiguous-scheme` |
| 21 | 平台不支持已引用布局能力时按声明降级并产生诊断 | 已覆盖 | `基线 21：平台不支持能力需声明降级；声明后运行期记录不静默` |
| 22 | 动效只出现在已声明动效面；动效值只解析到 motion Token | 部分覆盖 | `基线 22（部分）：样式片值只解析到 token，字面量静态拒绝（§36.4；§36.5 动效面未覆盖）` |
| 23 | 减少动效偏好命中替代组时应用替代 Token 并记录 | 未覆盖 | — |
| 24 | 性能预算超标时发布门禁失败并产生 mf.perf 诊断 | 未覆盖 | — |
| 25 | 增量构建不重新生成无关页面，增量与全量产物一致 | 未覆盖 | — |
| 26 | 绑定重复触发按声明并发策略执行；未声明拒绝重复触发 | 已覆盖 | `未声明并发策略的绑定是静态错误（基线 26）` |
| 27 | 恢复后未知结果副作用只进入 unknown 且可查询，不自动重试 | 已覆盖 | `动作函数：注册、调用、超时进入 unknown 不当作失败（基线 3、27）` |
| 28 | Business Fact 按去重身份幂等确认；超时进入 unknown 可查询 | 未覆盖 | — |
| 29 | 标准运营事件族由运行时拦截边界零埋点产生，业务手工上报是静态错误 | 已覆盖 | `运行时：启动、双实例隔离、导航与标准事件族零埋点产出（基线 1、29）` |
| 30 | 文案通道互斥：i18n message 与内容资产双声明是静态错误 | 部分覆盖 | `i18n t+text 互斥与 message 引用缺失（§42，基线 30 部分）` |
| 31 | 三平面分离：内联可执行逻辑、配置携带代码/未验证数据、运行数据回写模型均被拒绝 | 部分覆盖 | `结构树属性内联可执行逻辑是静态错误（基线 31 部分）` |
| 32 | 受控交叉：未登记入受控交叉清单的改写面被静态拒绝；已登记面随实例冻结 | 部分覆盖 | `受控交叉清单外的变体改写面被静态拒绝（基线 32 部分）` |

覆盖汇总：16/32 条已覆盖，5 条部分覆盖（生成工具：`dart run tool/baseline_coverage.dart`，勿手工编辑本表）。

## 使用

```dart
import 'package:microflow4_flutter/microflow4_flutter.dart';

final fw = MicroFlowFramework.create(
  project: project,       // MFProject（§4）
  registry: registry,     // MFRegistry（§23 统一资源注册）
  releaseId: 'r1',
  telemetrySink: sink,    // 可选；缺省内存 sink
);
runApp(MicroFlowApp(project: project, registry: registry, runtime: fw.runtime));
```

完整可运行示例见 [example/lib/main.dart](example/)（§44.2 “备忘（Notes）”）。

## 检查

每个模块独立执行（总包与 example 同理）：

```text
cd packages/microflow_model && flutter analyze      # 0 issues
```

总包：

```text
flutter analyze   # 0 issues
flutter test      # 一致性基线测试（§44.3 可单测条目）
cd example && flutter run -d chrome
```
