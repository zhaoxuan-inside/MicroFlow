/// MicroFlow4Flutter — MicroFlow 前端框架的 Flutter 实现总包。
///
/// 模块划分（对应 docs/design/frontend-framework-design.md v1.12 的实现分层，
/// 每个模块独立版本、独立升级，模块间只走公共 API）：
///
/// ```text
///   microflow_model           模型/契约/诊断/i18n/Token（§4-§11、§36.2、§39、§41、§42）
///      ↑                ↑                ↑
///   microflow_runtime   microflow_observability   （遥测/实验/Debug，§24、§29、§31）
/// （注册/校验/解释运行时）
///      ↑
///   microflow_renderer_flutter  Flutter 渲染与应用入口（§12、§13.3、§38）
/// ```
///
/// 依赖方向：observability 与 renderer 都只依赖 runtime + model；运行时通过
/// 稳定的 MFEmissionSink 接口向 observability 发射事件，采集与运行时互不耦合。
library;

// 模型与运行时核心（Level 0 / Level 1）。
export 'package:microflow_model/microflow_model.dart';
export 'package:microflow_runtime/microflow_runtime.dart';

// 观测契约面（Level 2 协议 + 本地承载）。
export 'package:microflow_observability/microflow_observability.dart';

// Flutter Renderer 与应用入口。
export 'package:microflow_renderer_flutter/microflow_renderer_flutter.dart';

// 上层工具接入面（§14 结构化命令，阶段六）。
export 'package:microflow_authoring/microflow_authoring.dart';

import 'package:microflow_runtime/microflow_runtime.dart';

import 'package:microflow_model/microflow_model.dart';

import 'package:microflow_observability/microflow_observability.dart';

/// 框架装配器：用一次调用完成 runtime + 遥测管道 + 实验冻结上下文的接线，
/// 并在启动前执行静态校验门禁（§22.4）。业务层一般来说只需要它。
class MicroFlowFramework {
  MicroFlowFramework._(this.runtime, this.telemetry, this.experiment);

  final MFRuntime runtime;
  final MFTelemetryQueue telemetry;
  final MFExperimentState experiment;

  /// Validate + assemble; throws [StateError] when the project fails static
  /// validation (baseline enforcement before any running instance exists).
  static MicroFlowFramework create({
    required MFProject project,
    required MFRegistry registry,
    String environment = 'preview',
    String releaseId = 'release-local',
    MFTelemetrySink? telemetrySink,
    String Function()? themeProvider,
  }) {
    final validation = MFValidator(project: project, registry: registry).validate();
    if (!validation.ok) {
      throw StateError(
        '项目未通过静态校验：${validation.diagnostics.where((d) => d.severity == Severity.error).join('; ')}',
      );
    }
    final telemetry = MFTelemetryQueue(sink: telemetrySink ?? MFInMemorySink());
    final experiment = MFExperimentState();
    final runtime = MFRuntime(
      project: project,
      registry: registry,
      ids: MFInstanceIdentifiers(
        projectId: project.manifest.projectId,
        releaseId: releaseId,
        environment: environment,
      ),
      emissionSink: telemetry,
      experimentAssignments: experiment.frozenAssignments,
      themeProvider: themeProvider,
    );
    return MicroFlowFramework._(runtime, telemetry, experiment);
  }
}
