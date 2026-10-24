/// `MicroFlowApp` — the Flutter Renderer entry point (framework design §1/§3):
/// a MicroFlow project model + resource registry runs as the product.
///
/// The app is framework-owned structure; business logic only enters through
/// registered resources and binding maps. The renderer depends on the
/// runtime module's public API only — the observability pipeline attaches
/// through the [MFEmissionSink] boundary.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:microflow_model/microflow_model.dart';
import 'package:microflow_runtime/microflow_runtime.dart';

import 'interpreter.dart';
import 'primitives.dart';

/// i18n 解析（§42.5，基线 5）：message 经回退链解析展示；缺失翻译上报
/// `mf.i18n.missing-translation` 并回退 messageId，不静默、不报错中断。
String mfLocalizePageMessage({
  required MFProject project,
  required MFPageInstance instance,
  required String messageId,
  List<MFDiag>? diagnostics,
}) {
  final resolved = project.i18n.resolve(messageId, instance.frozen.locale);
  final text = resolved.text;
  if (text == null) {
    diagnostics?.add(
      MFDiag(MFCodes.i18nMissingTranslation, 'message $messageId 缺失翻译（locale=${instance.frozen.locale}）'),
    );
    return messageId;
  }
  if (resolved.fellBack) {
    // 原始 locale 缺失、按回退链展示：同样上报缺失翻译（§42.5，基线 5），
    // 但有回退文案可用，降级为 warning。
    diagnostics?.add(
      MFDiag(
        MFCodes.i18nMissingTranslation,
        'message $messageId 在 locale ${instance.frozen.locale} 缺失翻译，按回退链展示（§42.5）',
        severity: Severity.warning,
      ),
    );
  }
  return text;
}

/// Run a MicroFlow project on Flutter.
class MicroFlowApp extends StatefulWidget {
  const MicroFlowApp({
    super.key,
    required this.project,
    required this.registry,
    required this.runtime,
    this.themeSeedColor = Colors.indigo,
    this.themeSelection,
    this.themeNames = const [],
    this.onThemeSelected,
  });

  /// 已就绪的运行时（含发射管道）；由外层完成 runtime + observability 的装配。
  final MFRuntime runtime;
  final MFProject project;
  final MFRegistry registry;
  final Color themeSeedColor;

  /// 双层主题切换演示面（§36.3，基线 7）：`themeSelection` 持有当前主题 id，
  /// 切换只影响新建实例（frozen context），运行中实例保持创建时的主题。
  final ValueListenable<String>? themeSelection;
  final List<String> themeNames;
  final void Function(String themeId)? onThemeSelected;

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

  /// 主题种子色从选中主题的有效 token 解析（§36.2/§36.3）。
  Color _seedFor(String themeId) {
    final resolver = MFStyleResolver(
      tokenSets: widget.project.tokens,
      styleSheets: widget.project.styleSheets,
      themes: widget.project.themes,
      defaultThemeId: widget.project.manifest.defaultTheme ?? 'theme-default',
    );
    final action = resolver.effectiveTokens(themeId)['color.action'];
    return action == null ? widget.themeSeedColor : resolveTokenColor(action);
  }

  @override
  Widget build(BuildContext context) {
    final project = widget.project;
    final selection = widget.themeSelection;
    final body = ValueListenableBuilder<int>(
      valueListenable: runtime.generation,
      builder: (_, _, _) => _PageHost(app: this),
    );
    if (selection == null || widget.themeNames.isEmpty) {
      final themeId = project.manifest.defaultTheme ?? 'theme-default';
      return MaterialApp(
        title: project.manifest.projectId,
        theme: ThemeData(useMaterial3: true, colorScheme: ColorScheme.fromSeed(seedColor: _seedFor(themeId))),
        home: body,
      );
    }
    return ValueListenableBuilder<String>(
      valueListenable: selection,
      builder: (_, selected, _) => MaterialApp(
        title: project.manifest.projectId,
        theme: ThemeData(useMaterial3: true, colorScheme: ColorScheme.fromSeed(seedColor: _seedFor(selected))),
        home: body,
      ),
    );
  }

  /// 主题切换菜单：选择后由宿主回调驱动（实例冻结语义在 runtime 侧保证）。
  List<Widget> themeActions(String selected) => [
        PopupMenuButton<String>(
          icon: const Icon(Icons.palette_outlined),
          tooltip: '切换主题（只影响新建实例）',
          itemBuilder: (_) => [
            for (final t in widget.themeNames)
              PopupMenuItem(
                value: t,
                child: Row(children: [
                  if (t == selected) const Icon(Icons.check, size: 16),
                  if (t == selected) const SizedBox(width: 4),
                  Text(t),
                ]),
              ),
          ],
          onSelected: widget.onThemeSelected,
        ),
      ];
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
    final themeSwitch = app.widget.themeNames.isEmpty
        ? null
        : app.themeActions(app.widget.themeSelection?.value ?? page.frozen.theme);
    return Scaffold(
      appBar: AppBar(
        title: Text(page.definition.route),
        actions: themeSwitch,
      ),
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

  String _localize(MFRuntime runtime, MFPageInstance page, String messageId, String locale) =>
      mfLocalizePageMessage(
        project: runtime.project,
        instance: page,
        messageId: messageId,
        diagnostics: runtime.diagnostics,
      );

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
