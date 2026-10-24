/// `MicroFlowApp` — the Flutter Renderer entry point (framework design §1/§3):
/// a MicroFlow project model + resource registry runs as the product.
///
/// The app is framework-owned structure; business logic only enters through
/// registered resources and binding maps. The renderer depends on the
/// runtime module's public API only — the observability pipeline attaches
/// through the [MFEmissionSink] boundary.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:microflow_model/microflow_model.dart';
import 'package:microflow_runtime/microflow_runtime.dart';

import 'interpreter.dart';
import 'primitives.dart';

/// Run a MicroFlow project on Flutter.
class MicroFlowApp extends StatefulWidget {
  const MicroFlowApp({
    super.key,
    required this.project,
    required this.registry,
    required this.runtime,
    this.themeSeedColor = Colors.indigo,
  });

  /// 已就绪的运行时（含发射管道）；由外层完成 runtime + observability 的装配。
  final MFRuntime runtime;
  final MFProject project;
  final MFRegistry registry;
  final Color themeSeedColor;

  @override
  State<MicroFlowApp> createState() => _MicroFlowAppState();
}

class _MicroFlowAppState extends State<MicroFlowApp> {
  MFRuntime get runtime => widget.runtime;

  @override
  void dispose() {
    runtime.generation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final project = widget.project;
    final action = project.tokens[project.manifest.defaultTheme]?.resolve('color.action');
    final seed = action == null ? widget.themeSeedColor : resolveTokenColor(action);
    return MaterialApp(
      title: project.manifest.projectId,
      theme: ThemeData(useMaterial3: true, colorScheme: ColorScheme.fromSeed(seedColor: seed)),
      home: ValueListenableBuilder<int>(
        valueListenable: runtime.generation,
        builder: (_, _, _) => _PageHost(app: this),
      ),
    );
  }
}

class _PageHost extends StatelessWidget {
  const _PageHost({required this.app});
  final _MicroFlowAppState app;

  @override
  Widget build(BuildContext context) {
    final runtime = app.runtime;
    if (runtime.stack.isEmpty) {
      // Must not start inside build; schedule once after frame.
      unawaited(() async {
        await runtime.start();
        runtime.generation.value++;
      }());
      return const Center(child: CircularProgressIndicator());
    }
    final page = runtime.current!;
    final interpreter = MFInterpreter(
      runtime: runtime,
      table: MFPrimitiveTable(),
      localize: (messageId, locale) => _localize(runtime, page, messageId, locale),
      resolveColor: (name) => _tokenValue(runtime, name),
      primitiveContracts: _primitiveContracts(runtime),
    );
    return Scaffold(
      appBar: AppBar(title: Text(page.definition.route)),
      body: interpreter.renderPage(page),
    );
  }

  /// Token 解析：跨项目 Token 集查找（§36.2）。
  Object? _tokenValue(MFRuntime runtime, String name) {
    for (final set in runtime.project.tokens.values) {
      final v = set.resolve(name);
      if (v != null) return v;
    }
    return null;
  }

  String _localize(MFRuntime runtime, MFPageInstance page, String messageId, String locale) {
    final resolved = runtime.project.i18n.resolve(messageId, page.frozen.locale);
    final text = resolved.text;
    if (text == null) {
      // Missing translation is diagnosable, never silent (§42.5, baseline 5).
      runtime.diagnostics.add(
        MFDiag(MFCodes.i18nMissingTranslation, 'message $messageId 缺失翻译（locale=$locale）'),
      );
      return messageId;
    }
    return text;
  }

  Map<String, ComponentContract> _primitiveContracts(MFRuntime runtime) {
    final out = <String, ComponentContract>{};
    for (final e in runtime.registry.all()) {
      if (e.kind == 'primitive') {
        out[e.id] = e.contract;
      }
    }
    return out;
  }
}
