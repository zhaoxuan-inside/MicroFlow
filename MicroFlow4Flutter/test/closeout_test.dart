import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// M2 收尾清零（遗留项修复）验证：
/// - 运行时：queue 并发策略真排队（§39.1）、product 作用域落位（§11）、
///   页面级默认错误边界（§13.2）、渲染修订号（§12.1）、标准事件族手工
///   上报拦截（§24.7）；
/// - 静态：Tier A 元组件集门禁（§38.1）、样式面声明（§36.5）、图层归属
///   悬空（§7.1）；
/// - 渲染合一：显式图层结构化渲染（§7.1/基线 12）、节点自约束映射
///   （§7.2/§7.3）、条件布局方案消费（§7.4/基线 20）、插槽区分（§23.9）、
///   Tier B Split/Anchor（§38.1）、Renderer Contract 生产消费点（§12.1）。

MFRuntime buildRuntime(MFProject project, MFRegistry registry, {MFInMemorySink? sink}) => MFRuntime(
      project: project,
      registry: registry,
      ids: MFInstanceIdentifiers(projectId: project.manifest.projectId, releaseId: 'r1', environment: 'dev'),
      emissionSink: MFTelemetryQueue(sink: sink ?? MFInMemorySink(), batchMax: 64),
    );

MFRegistry closeoutRegistry({List<String> only = const ['Stack', 'Text']}) {
  final r = MFRegistry();
  for (final id in only) {
    r.register(
      'primitive',
      id,
      ComponentContract(
        props: switch (id) {
          'Text' => {'text': const TString()},
          'Split' => {'direction': const TString(), 'weights': const TList()},
          'Anchor' => {'anchor': const TString()},
          _ => const {},
        },
        events: const {'press': TString()},
        slots: const ['content'],
        layout: const LayoutCapability(display: ['block'], sizing: ['hug', 'fill', 'fixed']),
      ),
      MFHostComponentImpl((children, props) => Object()),
    );
  }
  return r;
}

void main() {
  group('运行时遗留清零', () {
    test('§39.1：queue 并发策略按声明顺序排队串行执行，不并发不拒绝', () async {
      final events = <String>[];
      final registry = closeoutRegistry()..register(
        'function',
        'fn.mark',
        const ComponentContract(),
        MFAdapterImpl((args) async {
          events.add('start-${args['i']}');
          await Future<void>.delayed(const Duration(milliseconds: 30));
          events.add('end');
          return {'ok': true};
        }, timeoutMs: 2000),
      );
      final project = MFProject(
        manifest: const MFManifest(projectId: 'q', entryPage: 'p'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: const MFNode(id: 'root', type: 'Stack'),
            stateMembers: const ['v'],
          ),
        ],
        bindingMaps: const {
          'm': MFBindingMap(
            id: 'm',
            bindings: [
              MFBinding(
                id: 'q-run',
                on: 'root.press',
                actions: [
                  MFAdapterAction(kind: 'function', call: 'fn.mark', arguments: {'i': MFRef('prop.i')}),
                ],
                policy: MFPolicy.queue,
              ),
            ],
          ),
        },
      );
      final runtime = buildRuntime(project, registry);
      await runtime.start();
      final runs = [
        runtime.execute('q-run', props: const {'i': 1}),
        runtime.execute('q-run', props: const {'i': 2}),
        runtime.execute('q-run', props: const {'i': 3}),
      ];
      final results = await Future.wait(runs);
      expect(results.any((r) => r.results.containsKey('rejected-concurrency')), isFalse,
          reason: 'queue 不拒绝重复触发');
      expect(events, ['start-1', 'end', 'start-2', 'end', 'start-3', 'end'],
          reason: '三次触发严格串行排队执行（§39.1 queue）');
    });

    test('§24.7：标准事件族手工上报被拒绝；运行时标记的零埋点发射进入管道', () async {
      final sink = MFInMemorySink();
      final queue = MFTelemetryQueue(sink: sink, batchMax: 64);
      Map<String, Object?> raw({required bool runtimeMarked}) => {
            'event_name': 'ops.page.viewed',
            'payload': const {},
            if (runtimeMarked) 'mf_source': 'runtime-intercept',
            'session_id': 's',
            'page_instance_id': 'p',
            'route': '/r',
            'release_id': 'r1',
            'renderer_version': 'v',
            'renderer_package': 'microflow4_flutter',
            'environment': 'dev',
            'trace_id': 't',
            'identity': const {'user_ref': null},
            'experiment_assignments': const [],
          };
      queue.emit(raw(runtimeMarked: false));
      expect(queue.diagnostics.any((d) => d.code == MFCodes.teleManualStandardEvent), isTrue,
          reason: '业务代码手工上报标准事件族被拒（§24.7 唯一发射点）');
      queue.emit(raw(runtimeMarked: true));
      await queue.flush();
      expect(sink.delivered, hasLength(1), reason: '运行时拦截边界的发射不受影响');
    });

    test('§11：product 作用域写入如实落位', () async {
      final registry = closeoutRegistry();
      final project = MFProject(
        manifest: const MFManifest(projectId: 'sc', entryPage: 'p'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: const MFNode(id: 'root', type: 'Stack'),
            stateMembers: const ['v'],
          ),
        ],
        bindingMaps: const {
          'm': MFBindingMap(
            id: 'm',
            bindings: [
              MFBinding(
                id: 'product-write',
                on: 'root.press',
                actions: [
                  MFStateAction(target: 'theme-seed', value: MFLiteral('dark'), scope: 'product'),
                  MFStateAction(target: 'v', value: MFLiteral('page-value')),
                ],
                policy: MFPolicy.rejectNew,
              ),
            ],
          ),
        },
      );
      final runtime = buildRuntime(project, registry);
      await runtime.start();
      await runtime.execute('product-write');
      expect(runtime.state.peek('product', 'theme-seed'), 'dark', reason: 'product 不再静默落到 page 层');
      expect(runtime.state.peek('page', 'v'), 'page-value');
      expect(runtime.safeEval(MFRef('product.theme-seed'), EvalContext(
        state: runtime.state,
        props: const {},
        params: const {},
        prev: const {},
        providedRoots: const [],
      )), 'dark', reason: '表达式 product 根可读取');
    });

    test('§13.2：页面级默认错误边界被消费（绑定未声明时回退页面边界）', () async {
      final registry = closeoutRegistry();
      final project = MFProject(
        manifest: const MFManifest(projectId: 'bh', entryPage: 'p'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: const MFNode(id: 'root', type: 'Stack'),
            stateMembers: const ['v'],
            errorBoundary: 'page-bh',
          ),
        ],
        bindingMaps: const {
          'm': MFBindingMap(
            id: 'm',
            bindings: [
              MFBinding(
                id: 'boom',
                on: 'root.press',
                actions: [MFStateAction(target: 'x', value: MFLiteral(1), scope: 'component')],
                policy: MFPolicy.rejectNew,
              ),
            ],
          ),
        },
      );
      final runtime = buildRuntime(project, registry);
      await runtime.start();
      await runtime.dispatchEvent('root', 'press');
      expect(runtime.boundaryHandler.captured, isNotEmpty);
      expect(runtime.boundaryHandler.captured.last.info.boundaryId, 'page-bh',
          reason: '绑定未声明边界时回退页面级 errorBoundary（此前该字段无读取点）');
    });

    test('§12.1：渲染修订号随 generation 推进并进入 Debug 上下文', () async {
      final registry = closeoutRegistry();
      final project = MFProject(
        manifest: const MFManifest(projectId: 'rr', entryPage: 'p'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: const MFNode(id: 'root', type: 'Stack'),
            stateMembers: const ['v'],
          ),
        ],
        bindingMaps: const {
          'm': MFBindingMap(
            id: 'm',
            bindings: [
              MFBinding(
                id: 'w',
                on: 'root.press',
                actions: [MFStateAction(target: 'v', value: MFLiteral(1))],
                policy: MFPolicy.rejectNew,
              ),
            ],
          ),
        },
      );
      final runtime = buildRuntime(project, registry);
      await runtime.start();
      final atStart = (runtime.debugContext()['render_revision'] as num).toInt();
      expect(atStart, greaterThanOrEqualTo(1));
      await runtime.execute('w');
      expect((runtime.debugContext()['render_revision'] as num).toInt(), greaterThan(atStart));
    });
  });

  group('静态门禁清零', () {
    test('§38.1：Tier A 元组件集缺失按 warning 上报（不阻断，发布门禁按 §38.2）', () {
      final project = MFProject(
        manifest: const MFManifest(projectId: 'ta', entryPage: 'p'),
        pages: [MFPage(id: 'p', route: '/p', tree: const MFNode(id: 'root', type: 'Text'))],
      );
      final result = MFValidator(project: project, registry: closeoutRegistry(only: ['Text'])).validate();
      final tierAWarnings = result.diagnostics
          .where((d) => d.code == MFCodes.regUnregisteredImpl && d.severity == Severity.warning)
          .toList();
      expect(tierAWarnings, hasLength(MFTierA.required.length - 1), reason: '缺 11 个必备元组件');
      expect(result.ok, isTrue, reason: 'warning 不阻断静态校验');
    });

    test('§36.5：节点样式片消费的 aspect 未在契约 exposedStyles 声明 → mf.style.face-undeclared', () {
      final registry = closeoutRegistry(only: ['Text'])..register(
        'primitive',
        'Text',
        ComponentContract(
          props: const {'text': TString()},
          exposedStyles: const ['foreground'],
          layout: const LayoutCapability(),
        ),
        MFHostComponentImpl((children, props) => Object()),
      );
      final project = MFProject(
        manifest: const MFManifest(projectId: 'sf', entryPage: 'p', defaultTheme: 'theme-light'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: MFNode(
              id: 'root',
              type: 'Text',
              props: const {'text': 'x'},
              style: 's1',
            ),
          ),
        ],
        tokens: const {
          'theme-light': MFTokenSet(id: 'theme-light', tokens: {'color.bg': '#ffffff'}),
        },
        styleSheets: const {
          's1': MFStyleSheet(id: 's1', base: {'background': 'color.bg'}),
        },
      );
      final diags = MFValidator(project: project, registry: registry).validate().diagnostics;
      expect(diags.any((d) => d.code == MFCodes.styleFaceUndeclared), isTrue,
          reason: 'background 面未在 exposedStyles 声明（此前该码无发射点）');
    });

    test('§7.1：节点图层归属悬空是静态错误', () {
      final project = MFProject(
        manifest: const MFManifest(projectId: 'ly', entryPage: 'p'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: MFNode(
              id: 'root',
              type: 'Stack',
              children: [const MFNode(id: 'h', type: 'Stack', layer: 'nope')],
            ),
            layerRegions: const [MFRegionConstraint(id: 'header', region: 'header')],
          ),
        ],
      );
      final diags = MFValidator(project: project, registry: closeoutRegistry()).validate().diagnostics;
      expect(diags.any((d) => d.code == MFCodes.refDangling && d.message.contains('图层归属')), isTrue);
    });

    test('§42：i18n 伪本地化视图暴露字面量（开发期工具）', () {
      const catalog = MFI18nCatalog(
        defaultLocale: 'zh-CN',
        supportedLocales: ['zh-CN', 'en'],
        fallback: {'en': 'zh-CN'},
        messages: {
          'k': {'zh-CN': '备忘', 'en': 'Notes'},
        },
      );
      final pseudo = catalog.pseudoLocalized();
      expect(pseudo.resolve('k', 'zh-CN').text, '[备忘]');
      expect(pseudo.resolve('k', 'en').text, '[Notes]');
      // 原目录不被改写（实例冻结纪律）。
      expect(catalog.resolve('k', 'zh-CN').text, '备忘');
    });
  });

  group('渲染合一（widget）', () {
    Future<MFRuntime> pumpApp(WidgetTester tester, MFProject project, MFRegistry registry) async {
      final runtime = buildRuntime(project, registry);
      await runtime.start();
      await tester.pumpWidget(MicroFlowApp(project: project, registry: registry, runtime: runtime));
      await tester.pump();
      return runtime;
    }

    testWidgets('§7.1：显式图层按 header/footer/overlay/content 结构化渲染', (tester) async {
      final project = MFProject(
        manifest: const MFManifest(projectId: 'w1', entryPage: 'p'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: MFNode(
              id: 'root',
              type: 'Stack',
              children: [
                MFNode(id: 'h', type: 'Text', props: const {'text': 'HEADER'}, layer: 'header'),
                MFNode(id: 'c', type: 'Text', props: const {'text': 'CONTENT'}),
                MFNode(id: 'f', type: 'Text', props: const {'text': 'FOOTER'}, layer: 'footer'),
                MFNode(id: 'o', type: 'Text', props: const {'text': 'OVERLAY'}, layer: 'overlay'),
              ],
            ),
            layerRegions: const [
              MFRegionConstraint(id: 'header', region: 'header'),
              MFRegionConstraint(id: 'content', region: 'content', scroll: true),
              MFRegionConstraint(id: 'footer', region: 'footer'),
              MFRegionConstraint(id: 'overlay', region: 'overlay'),
            ],
          ),
        ],
      );
      await pumpApp(tester, project, closeoutRegistry());
      expect(find.text('HEADER'), findsOneWidget);
      expect(find.text('FOOTER'), findsOneWidget);
      expect(find.text('OVERLAY'), findsOneWidget);
      expect(find.text('CONTENT'), findsOneWidget);
      expect(find.byType(SingleChildScrollView), findsOneWidget, reason: 'content 分区声明 scroll');
      expect(find.byType(Expanded), findsWidgets, reason: '内容区占据剩余空间');
      expect(find.byType(Stack), findsWidgets, reason: 'overlay 以 Stack 覆盖');
    });

    testWidgets('§7.2/§7.3：节点自约束映射渲染——fixed 固定尺寸、fill 主轴 Expanded', (tester) async {
      final project = MFProject(
        manifest: const MFManifest(projectId: 'w2', entryPage: 'p'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: MFNode(
              id: 'root',
              type: 'Stack',
              props: const {'expand': true},
              children: [
                MFNode(
                  id: 'fixed',
                  type: 'Text',
                  props: const {'text': 'FIXED'},
                  constraints: const MFSelfConstraint(height: 40),
                ),
                MFNode(
                  id: 'fill',
                  type: 'Text',
                  props: const {'text': 'FILL'},
                  constraints: const MFSelfConstraint(height: 'fill'),
                ),
              ],
            ),
          ),
        ],
      );
      await pumpApp(tester, project, closeoutRegistry());
      expect(find.text('FIXED'), findsOneWidget);
      expect(find.text('FILL'), findsOneWidget);
      expect(find.byWidgetPredicate((w) => w is SizedBox && w.height == 40), findsOneWidget,
          reason: 'fixed 约束映射为 SizedBox');
      expect(find.byType(Expanded), findsOneWidget, reason: 'fill 约束映射为主轴 Expanded');
    });

    testWidgets('§7.4：条件布局方案被渲染消费——断点命中覆盖 Stack 方向', (tester) async {
      final project = MFProject(
        manifest: const MFManifest(projectId: 'w3', entryPage: 'p'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: MFNode(
              id: 'root',
              type: 'Stack',
              children: [
                const MFNode(id: 'a', type: 'Text', props: {'text': 'A'}),
                const MFNode(id: 'b', type: 'Text', props: {'text': 'B'}),
              ],
            ),
            conditionalLayouts: [
              const MFConditionalLayout(
                target: 'p',
                schemes: [
                  MFConditionalScheme(
                    when: {'breakpoint': 'desktop'},
                    plan: MFLayoutPlan(direction: 'horizontal'),
                  ),
                ],
                defaultPlan: MFLayoutPlan(direction: 'vertical'),
              ),
            ],
          ),
        ],
      );
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      tester.view.devicePixelRatio = 1.0;

      // 平板宽度（600-1023）→ 不命中 desktop → 默认方案 vertical。
      tester.view.physicalSize = const Size(800, 600);
      await pumpApp(tester, project, closeoutRegistry());
      expect(find.byWidgetPredicate((w) => w is Column && w.children.length == 2), findsWidgets,
          reason: '默认方案 vertical（基线 20 全不命中回退默认）');

      // 桌面宽度（≥1024）→ 命中 desktop → horizontal（新实例重新求值）。
      tester.view.physicalSize = const Size(1200, 800);
      await tester.pumpWidget(const SizedBox.shrink());
      await pumpApp(tester, project, closeoutRegistry());
      expect(find.byWidgetPredicate((w) => w is Row && w.children.length == 2), findsWidgets,
          reason: '命中 desktop 方案 horizontal');
    });

    testWidgets('§38.1：Tier B Split/Anchor 渲染（6/6 齐备）', (tester) async {
      final project = MFProject(
        manifest: const MFManifest(projectId: 'w4', entryPage: 'p'),
        pages: [
          MFPage(
            id: 'p',
            route: '/p',
            tree: MFNode(
              id: 'root',
              type: 'Stack',
              children: [
                MFNode(
                  id: 'split',
                  type: 'Split',
                  props: const {'direction': 'horizontal', 'weights': [2, 1]},
                  children: [
                    const MFNode(id: 'l', type: 'Text', props: {'text': 'LEFT'}),
                    const MFNode(id: 'r', type: 'Text', props: {'text': 'RIGHT'}),
                  ],
                ),
                MFNode(
                  id: 'anchor',
                  type: 'Anchor',
                  props: const {'anchor': 'top-right'},
                  children: [const MFNode(id: 'at', type: 'Text', props: {'text': 'ANCHORED'})],
                ),
              ],
            ),
          ),
        ],
      );
      await pumpApp(tester, project, closeoutRegistry(only: ['Stack', 'Text', 'Split', 'Anchor']));
      expect(find.text('LEFT'), findsOneWidget);
      expect(find.text('RIGHT'), findsOneWidget);
      expect(find.byWidgetPredicate((w) => w is Expanded && w.flex == 2), findsOneWidget,
          reason: 'weights 声明式分配');
      expect(find.byWidgetPredicate((w) => w is Expanded && w.flex == 1), findsOneWidget);
      expect(find.byWidgetPredicate((w) => w is Align && w.alignment == Alignment.topRight),
          findsOneWidget, reason: '锚定仅相对容器边（§7.3）');
      expect(find.text('ANCHORED'), findsOneWidget);
    });

    test('§12.1：Renderer Contract 挂到生产消费点且 allowed_differences 声明一致', () {
      expect(MicroFlowApp.contract, same(mfFlutterRendererContract));
      expect(mfFlutterRendererContract.validate(), isEmpty,
          reason: '§38.2：允许差异全部声明（此前无生产调用方）');
    });
  });
}
