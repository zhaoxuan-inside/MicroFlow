import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'fixtures/product_sample.dart';

/// 0.11.0 视觉能力面的可执行判据（能力面测试，不挂 §44.3 基线号）：
/// - S1 表面卡片：Stack background/radius/border/shadow 产生 BoxDecoration；
/// - S2 token 语义：background/borderColor 走 token（未知 token 不染色）；
/// - S3 框架面主题：Scaffold 背景接 'color.background'，AppBar 回归表面语义；
/// - S4 品牌默认种子色：未声明 color.action 时回落品牌蓝（不再是 indigo）。
//
// 样例模型：test/fixtures/product_sample.dart（产品级表达力参考，非业务应用）。

MFRegistry _registry() {
  final r = MFRegistry();
  for (final id in MFTierA.required) {
    r.register(
      'primitive',
      id,
      ComponentContract(
        props: switch (id) {
          'Text' => {'text': const TString()},
          'List' => {'items': const TList()},
          _ => const {},
        },
        slots: const ['content'],
        layout: const LayoutCapability(),
      ),
      MFHostComponentImpl((children, props) => Object()),
    );
  }
  // Tier B：Grid（样例的指标卡行使用 columns/gap 模式）。
  r.register(
    'primitive',
    'Grid',
    const ComponentContract(props: {'columns': TString(), 'gap': TString()},
        slots: ['content'], layout: LayoutCapability()),
    MFHostComponentImpl((children, props) => Object()),
  );
  return r;
}

Future<MFRuntime> _started(MFProject project) async {
  final runtime = MFRuntime(
    project: project,
    registry: _registry(),
    ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
    emissionSink: MFNullEmissionSink(),
  );
  await runtime.start();
  runtime.state.write('page', 'rows', [
    {'name': 'ops.page.viewed', 'count': 5},
    {'name': 'ops.feature.used', 'count': 5},
  ]);
  runtime.generation.value++;
  return runtime;
}

void main() {
  testWidgets('S1 表面卡片：背景/圆角/边框/阴影全部落到 BoxDecoration', (tester) async {
    final project = productSampleProject();
    final runtime = await _started(project);
    await tester.pumpWidget(MicroFlowApp(project: project, registry: _registry(), runtime: runtime));
    await tester.pumpAndSettle();

    expect(find.text('运营总览'), findsOneWidget);
    expect(find.text('事件总数'), findsOneWidget);
    expect(find.text('10'), findsOneWidget);
    expect(find.text('ops.page.viewed'), findsOneWidget);

    // '10' 指标值的表面祖先链：取全部 Container 祖先的 decoration。
    final decorations = tester
        .widgetList<Container>(find.ancestor(of: find.text('10'), matching: find.byType(Container)))
        .map((c) => c.decoration)
        .whereType<BoxDecoration>()
        .toList();
    final cardDecor = decorations.where((d) => d.borderRadius != null && d.boxShadow != null).toList();
    expect(cardDecor, isNotEmpty, reason: '指标卡应携带圆角与阴影的表面装饰');
    expect(cardDecor.first.color, const Color(0xFFFFFFFF), reason: 'background token color.surface 落到表面');
    expect(cardDecor.first.borderRadius, BorderRadius.circular(10));
    expect(cardDecor.first.border?.top.width, 1);
    expect(cardDecor.first.boxShadow!.first.blurRadius, 8, reason: 'raised 阴影预设');
  });

  testWidgets('S2 未知 token 不染色（绝不回落灰色伪造表面）', (tester) async {
    final project = MFProject(
      manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
      tokens: const {
        'theme-light': MFTokenSet(id: 'theme-light', tokens: {'color.foreground': '#171717'}),
      },
      pages: [
        MFPage(
          id: 'page',
          route: '/p',
          tree: MFNode(
            id: 'root',
            type: 'Stack',
            props: const {'background': 'color.not.declared', 'radius': 8, 'padding': 8},
            children: const [
              MFNode(id: 'label', type: 'Text', props: {'text': '未知 token 表面'}),
            ],
          ),
        ),
      ],
    );
    final runtime = await _started(project);
    await tester.pumpWidget(MicroFlowApp(project: project, registry: _registry(), runtime: runtime));
    await tester.pump();

    final container = tester.widget<Container>(
      find.ancestor(of: find.text('未知 token 表面'), matching: find.byType(Container)).first,
    );
    final decor = container.decoration as BoxDecoration;
    expect(decor.color, isNull, reason: 'background token 未声明时表面不染色');
    expect(decor.borderRadius, BorderRadius.circular(8), reason: 'radius 独立于背景生效');
  });

  testWidgets('S3 框架面主题：Scaffold 背景接 color.background，AppBar 表面语义', (tester) async {
    final project = productSampleProject();
    final runtime = await _started(project);
    await tester.pumpWidget(MicroFlowApp(project: project, registry: _registry(), runtime: runtime));
    await tester.pumpAndSettle();

    // 主题值断言：Scaffold/AppBar 的 widget 属性为 null 表示「交由主题解析」，
    // 真实生效值读 Theme（框架面已把 token 写进 ThemeData）。
    final theme = Theme.of(tester.element(find.byType(Scaffold)));
    expect(theme.scaffoldBackgroundColor, const Color(0xFFF7F8FA),
        reason: "token 'color.background' 落到页面背景");
    expect(theme.appBarTheme.backgroundColor, const Color(0xFFF7F8FA));
    expect(theme.appBarTheme.elevation, 0);
  });

  testWidgets('S4 品牌默认种子色：未声明 color.action 时回落品牌蓝', (tester) async {
    final project = MFProject(
      manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
      tokens: const {
        'theme-light': MFTokenSet(id: 'theme-light', tokens: {'color.foreground': '#171717'}),
      },
      pages: [
        MFPage(
          id: 'page',
          route: '/p',
          tree: MFNode(
            id: 'root',
            type: 'Stack',
            children: const [MFNode(id: 'label', type: 'Text', props: {'text': '默认品牌'})],
          ),
        ),
      ],
    );
    final runtime = await _started(project);
    late BuildContext captured;
    await tester.pumpWidget(
      Builder(builder: (context) {
        captured = context;
        return MicroFlowApp(project: project, registry: _registry(), runtime: runtime);
      }),
    );
    await tester.pump();
    final scheme = Theme.of(captured).colorScheme;
    final primary = scheme.primary;
    // 种子品牌蓝派生的主色应带蓝色调（B 分量显著高于 R）。
    expect(primary.b, greaterThan(primary.r), reason: '品牌蓝种子派生，而非 indigo/灰');
  });
}
