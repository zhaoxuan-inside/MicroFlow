import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// 0.8.0 框架能力扩展的可执行判据（能力面测试，不挂 §44.3 基线号）：
/// - F1 主题 ref 链深解析：基础集语义 ref / 多跳 override 重定向解到底（§36.3）；
/// - F2 列表/映射字面量内嵌 ref 深求值（§37.2 边界撤销）；
/// - F3 List 虚拟化：长列表走 ListView.builder 懒构建；
/// - F4 Table 数据绑定：columns/rows 模式（旧 children 分块模式向后兼容）；
/// - F5 Stack/Split/Grid gap 间距 prop；
/// - F6 节点 visible 条件渲染。

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
  // Tier B：Table（数据绑定 + 旧分块双模式）。
  r.register(
    'primitive',
    'Table',
    const ComponentContract(props: {'columns': TList(), 'rows': TList()}, slots: ['content'], layout: LayoutCapability()),
    MFHostComponentImpl((children, props) => Object()),
  );
  return r;
}

void main() {
  group('F1 主题 ref 链深解析（§36.3）', () {
    final resolver = MFStyleResolver(
      tokenSets: {
        'light': const MFTokenSet(id: 'light', tokens: {
          'color.bg.canvas.light': '#F7F8FA',
          'color.bg.canvas': {'ref': 'color.bg.canvas.light'},
          'color.bg.card': {'ref': 'color.bg.canvas'},
        }),
        'dark': const MFTokenSet(id: 'dark', tokens: {
          'color.bg.canvas.light': '#0B1220',
          'color.bg.canvas': {'ref': 'color.bg.canvas.light'},
          'color.bg.card': {'ref': 'color.bg.canvas'},
        }),
      },
      styleSheets: const {},
      themes: const {
        'dark': MFTheme(id: 'dark', base: 'dark'),
        'light': MFTheme(id: 'light', base: 'light'),
      },
      defaultThemeId: 'dark',
    );

    test('基础集语义 ref 解到底（宿主不再补解析）', () {
      final dark = resolver.effectiveTokens('dark');
      expect(dark['color.bg.canvas'], '#0B1220', reason: '不再是 {ref} 原样合并');
      expect(dark['color.bg.card'], '#0B1220', reason: '两跳链也解到底');
      final light = resolver.effectiveTokens('light');
      expect(light['color.bg.canvas'], '#F7F8FA');
      expect(light['color.bg.card'], '#F7F8FA');
    });

    test('多跳 override 重定向经深解析生效', () {
      final themed = MFStyleResolver(
        tokenSets: {
          'base': const MFTokenSet(id: 'base', tokens: {
            'color.accent': '#2563EB',
            'color.bg.canvas.light': '#0B1220',
            'color.bg.canvas': {'ref': 'color.bg.canvas.light'},
          }),
        },
        styleSheets: const {},
        themes: const {
          // 重定向链（目标 token 均已存在，§36.3 有界重定向）：
          // accent -> canvas -> canvas.light，覆盖旧单跳限制。
          'dark': MFTheme(id: 'dark', base: 'base', overrides: {
            'color.accent': {'ref': 'color.bg.canvas'},
            'color.bg.canvas': {'ref': 'color.bg.canvas.light'},
          }),
        },
        defaultThemeId: 'dark',
      );
      expect(themed.effectiveTokens('dark')['color.accent'], '#0B1220');
    });

    test('ref 环与超深链归 null（与 MFTokenSet.resolve 口径对齐）', () {
      final cyclic = MFStyleResolver(
        tokenSets: {
          'base': const MFTokenSet(id: 'base', tokens: {
            'a': {'ref': 'b'},
            'b': {'ref': 'a'},
            'dangling': {'ref': 'not.existing'},
          }),
        },
        styleSheets: const {},
        themes: const {},

        defaultThemeId: 'base',
      );
      final t = cyclic.effectiveTokens('base');
      expect(t['a'], isNull);
      expect(t['b'], isNull);
      expect(t['dangling'], isNull, reason: '悬空 ref 由 completeness 诊断报缺');
    });
  });

  group('F2 列表/映射字面量内嵌 ref 深求值（§37.2）', () {
    test('嵌套 ref/call 形状求值，普通内容保持字面量', () {
      final store = MFStateStore()
        ..write('page', 'sel', 'OPC')
        ..write('session', 'who', 'hardstone');
      final ctx = EvalContext(state: store);
      const ev = MFExprEvaluator();

      final parsed = MFExpr.parse({
        'kind': 'publish',
        'sel': {'ref': 'state.sel'},
        'tags': [
          {'ref': 'session.who'},
          '静态标签',
        ],
        'nested': {'deep': [{'ref': 'state.sel'}]},
      });
      final out = ev.eval(parsed, ctx) as Map;
      expect(out['kind'], 'publish');
      expect(out['sel'], 'OPC');
      expect(out['tags'], ['hardstone', '静态标签']);
      expect((out['nested'] as Map)['deep'], ['OPC']);

      // 纯字面量往返不变。
      final plain = ev.eval(MFExpr.parse([
        1,
        'a',
        {'k': 'v'},
      ]), ctx);
      expect(plain, [1, 'a', {'k': 'v'}]);
    });

    test('refPaths 递归发现内嵌 ref（静态存在性检查覆盖深结构）', () {
      final expr = MFExpr.parse({
        'items': [
          {'ref': 'state.sel'},
        ],
        'meta': {'who': {'ref': 'session.who'}},
      });
      expect(expr.refPaths().toSet(), {'state.sel', 'session.who'});
    });
  });

  group('F3 List 虚拟化 + F4 Table 数据绑定 + F5 gap + F6 visible（渲染面）', () {
    testWidgets('40 项列表走 ListView.builder 懒构建，滚动后末项出现', (tester) async {
      final registry = _registry();
      final project = MFProject(
        manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
        pages: [
          MFPage(
            id: 'page',
            route: '/p',
            layerRegions: const [
              MFRegionConstraint(id: 'content', region: 'content', scroll: true),
            ],
            tree: MFNode(
              id: 'root',
              type: 'Stack',
              children: [
                MFNode(
                  id: 'feed',
                  type: 'List',
                  props: {'items': MFRef('state.rows'), 'layer': 'content'},
                  children: const [
                    MFNode(id: 'row', type: 'Text', props: {'text': MFRef('item.name')}),
                  ],
                ),
              ],
            ),
            stateMembers: const ['rows'],
          ),
        ],
      );
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
        emissionSink: MFNullEmissionSink(),
      );
      await runtime.start();
      runtime.state.write('page', 'rows', [
        for (var i = 0; i < 40; i++) {'name': '行 $i'},
      ]);
      runtime.generation.value++;

      await tester.pumpWidget(MicroFlowApp(project: project, registry: registry, runtime: runtime));
      await tester.pump();

      expect(find.byType(ListView), findsOneWidget, reason: '超阈值走虚拟化构建器');
      expect(find.text('行 0'), findsOneWidget);

      // 外层滚动（content 分区 scroll）后末项懒构建出现。
      await tester.drag(find.byType(SingleChildScrollView), const Offset(0, -4000));
      await tester.pump();
      expect(find.text('行 39'), findsOneWidget);
    });

    testWidgets('Table 数据绑定：columns/rows 渲染表头与单元格', (tester) async {
      final registry = _registry();
      final project = MFProject(
        manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
        pages: [
          MFPage(
            id: 'page',
            route: '/p',
            tree: MFNode(
              id: 'root',
              type: 'Stack',
              children: [
                MFNode(
                  id: 'grid',
                  type: 'Table',
                  props: {
                    'columns': [
                      {'key': 'name', 'label': '名称'},
                      {'key': 'qty', 'label': '数量', 'width': 80},
                    ],
                    'rows': MFRef('state.rows'),
                  },
                ),
              ],
            ),
            stateMembers: const ['rows'],
          ),
        ],
      );
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
        emissionSink: MFNullEmissionSink(),
      );
      await runtime.start();
      runtime.state.write('page', 'rows', [
        {'name': '晨跑', 'qty': 3},
        {'name': '阅读', 'qty': 12},
      ]);
      runtime.generation.value++;

      await tester.pumpWidget(MicroFlowApp(project: project, registry: registry, runtime: runtime));
      await tester.pump();

      expect(find.text('名称'), findsOneWidget);
      expect(find.text('数量'), findsOneWidget);
      expect(find.text('晨跑'), findsOneWidget);
      expect(find.text('12'), findsOneWidget);
    });

    testWidgets('Table 旧模式：columns 数量 + children 分块（向后兼容）', (tester) async {
      final registry = _registry();
      final project = MFProject(
        manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
        pages: [
          MFPage(
            id: 'page',
            route: '/p',
            tree: MFNode(
              id: 'root',
              type: 'Stack',
              children: [
                MFNode(
                  id: 'grid',
                  type: 'Table',
                  props: {'columns': 2},
                  children: const [
                    MFNode(id: 'h1', type: 'Text', props: {'text': '旧列一'}),
                    MFNode(id: 'h2', type: 'Text', props: {'text': '旧列二'}),
                  ],
                ),
              ],
            ),
          ),
        ],
      );
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
        emissionSink: MFNullEmissionSink(),
      );
      await runtime.start();
      await tester.pumpWidget(MicroFlowApp(project: project, registry: registry, runtime: runtime));
      await tester.pump();
      expect(find.text('旧列一'), findsOneWidget);
      expect(find.text('旧列二'), findsOneWidget);
    });

    testWidgets('Stack gap 主轴间距生效', (tester) async {
      final registry = _registry();
      final project = MFProject(
        manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
        pages: [
          MFPage(
            id: 'page',
            route: '/p',
            tree: MFNode(
              id: 'root',
              type: 'Stack',
              props: {'direction': 'horizontal', 'gap': 24},
              children: const [
                MFNode(id: 'a', type: 'Text', props: {'text': '左'}),
                MFNode(id: 'b', type: 'Text', props: {'text': '右'}),
              ],
            ),
          ),
        ],
      );
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
        emissionSink: MFNullEmissionSink(),
      );
      await runtime.start();
      await tester.pumpWidget(MicroFlowApp(project: project, registry: registry, runtime: runtime));
      await tester.pump();

      final left = tester.getRect(find.text('左'));
      final right = tester.getRect(find.text('右'));
      expect(right.left - left.right, greaterThanOrEqualTo(24), reason: 'gap 声明映射 Row/Column spacing');
    });

    testWidgets('visible false 整体跳过；结构化谓词求值驱动显隐', (tester) async {
      final registry = _registry();
      MFPage pageWith(String id, Object? visible) {
        final maybeProps = <String, Object?>{'text': '条件'};
        if (visible != null) maybeProps['visible'] = visible;
        return MFPage(
          id: id,
          route: '/$id',
          tree: MFNode(
            id: 'root',
            type: 'Stack',
            children: [
              MFNode(id: 'always', type: 'Text', props: {'text': '常显'}),
              MFNode(id: 'maybe', type: 'Text', props: maybeProps),
            ],
          ),
          stateMembers: const ['flag'],
        );
      }
      MFProject projectFor(MFPage page) => MFProject(
            manifest: MFManifest(projectId: 'p', entryPage: page.id),
            pages: [page],
          );
      MFRuntime runtimeFor(MFProject project, {bool flag = false}) {
        final r = MFRuntime(
          project: project,
          registry: registry,
          ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
          emissionSink: MFNullEmissionSink(),
        );
        r.state.write('page', 'flag', flag);
        return r;
      }

      // bool 字面量 false：隐藏。
      final hidden = projectFor(pageWith('page', false));
      final hiddenRuntime = runtimeFor(hidden);
      await hiddenRuntime.start();
      await tester.pumpWidget(MicroFlowApp(project: hidden, registry: registry, runtime: hiddenRuntime));
      await tester.pump();
      expect(find.text('常显'), findsOneWidget);
      expect(find.text('条件'), findsNothing);

      // 结构化谓词：state.flag == true 时显示。
      final pred = projectFor(pageWith('page-pred', MFExpr.parse({'eq': [MFRef('state.flag'), true]})));
      final predRuntime = runtimeFor(pred);
      await predRuntime.start();
      await tester.pumpWidget(MicroFlowApp(project: pred, registry: registry, runtime: predRuntime));
      await tester.pump();
      expect(find.text('条件'), findsNothing, reason: 'flag=false 谓词不成立');
      predRuntime.state.write('page', 'flag', true);
      predRuntime.generation.value++;
      await tester.pump();
      expect(find.text('条件'), findsOneWidget);
    });
  });
}
