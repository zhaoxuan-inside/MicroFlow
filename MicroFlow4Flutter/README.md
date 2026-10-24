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
    └── microflow_observability        遥测信封/有界队列/实验冻结/Debug 会话（§24、§29、§31）
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
| microflow_model | 0.1.0 | `MFProject/MFManifest/MFPage/MFNode`、`ComponentContract/InfoContract/LayoutCapability`、`MFBindingMap/MFExpr/MFAction`、`MFI18nCatalog`、`MFTokenSet`、`MFDiag/MFCodes/mfDiagnosticRegistry` |
| microflow_runtime | 0.1.0 | `MFRegistry/MFResourceEntry`、`MFRuntime/MFPageInstance/MFFrozenContext/MFActionResult`、`MFValidator/MFValidationResult`、`MFStateStore`、`MFEmissionSink`、`MFExprEvaluator`、`MFBoundaryHandler` |
| microflow_observability | 0.1.0 | `MFEventEnvelope/MFTelemetryQueue/MFTelemetrySink/MFInMemorySink`、`MFStandardEvents`、`MFExperimentState/MFExperimentAssignment`、`MFDebugSession/MFDebugSnapshot` |
| microflow_renderer_flutter | 0.1.0 | `MFPrimitiveTable/MFTierA/MFInterpreter`、`MicroFlowApp`、`resolveTokenColor` |
| microflow4_flutter（总包） | 0.2.0 | 上述全部再导出 + `MicroFlowFramework.create`（校验门禁 + 装配） |

## 已实现能力（按 §38.2 分级如实声明）

- **Level 0 已实现**：项目模型 / 契约 / 静态校验器 / 诊断注册表 / i18n / Token；
- **Level 1 已实现（解释模式）**：页面实例 / 导航 / 状态层 / 绑定映射 /
  并发策略 / guard / 超时 unknown / 错误边界；Tier A 元组件渲染；
- **Level 2 协议面已定义并部分实现**：遥测信封 Schema 校验与有界队列、
  标准运营事件族零埋点（`ops.page.viewed/left`、`ops.feature.used`）、
  实验分配校验冻结停用、Debug 权限门与快照屏蔽；接收端服务、实验平台、
  远程诊断仍由业务层/承载方实现（§27）。

尚未实现（对照设计章节）：编译模式产物（§13.3 编译侧）、完整样式片/主题
覆盖链（§36.3–§36.6）、Tier B 全集、Business Fact 可靠通道、增量编译与
性能预算度量管线（§22.2）。

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
