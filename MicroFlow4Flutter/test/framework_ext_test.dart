import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// 产品级能力扩展的可执行判据（不挂基线号——这些是实现能力面，非 §44.3 条目）：
/// - 声明式列表绑定：List items + item 模板作用域 + 项事件上下文；
/// - 事件载荷：Input/Select 的 change 值经契约校验进入绑定执行（prop.value）；
/// - prev 深路径：结构化动作结果 `prev.<as>.<path>`；
/// - 信封恢复 fromJson：event_id/occurred_at 保留（§30.2 查询消费面）；
/// - 查询分组维度：`session_id` 与 `payload.<key>`；
/// - 恢复快照序列化 toJson/fromJson（§16.1 跨会话）；
/// - 注记 args：声明键进入事件 payload，未声明键不进入。

void main() {
  group('表达式与执行上下文', () {
    test('item 作用域求值与 prev 深路径', () {
      final store = MFStateStore()..write('page', 'habits', [
            {'id': 'h1', 'name': '晨跑'},
          ]);
      final ctx = EvalContext(
        state: store,
        prev: {'as:stats': {'total': 7, 'ranking': [{'name': '晨跑'}]}},
        item: {'id': 'h1', 'name': '晨跑', 'streak': 3},
      );
      const ev = MFExprEvaluator();
      expect(ev.eval(const MFRef('item.name'), ctx), '晨跑');
      expect(ev.eval(const MFRef('item.streak'), ctx), 3);
      expect(ev.eval(const MFRef('item.missing.deep'), ctx), isNull);
      expect(ev.eval(const MFRef('prev.stats.total'), ctx), 7);
      expect(ev.eval(const MFRef('prev.stats.ranking.0.name'), ctx), '晨跑');
      expect(ev.eval(const MFRef('prev.stats.absent'), ctx), isNull);
      expect(ev.eval(const MFRef('prev.stats'), ctx), isA<Map>());
    });
  });

  group('事件载荷与契约校验', () {
    test('dispatchEvent 载荷进入绑定执行（prop.value）；不符契约载荷进错误边界', () async {
      final registry = MFRegistry()
        ..register(
          'primitive',
          'Stack',
          const ComponentContract(
            events: {'press': TString()},
            layout: LayoutCapability(),
          ),
          MFHostComponentImpl((children, props) => Object()),
        )
        ..register(
          'primitive',
          'Input',
          const ComponentContract(
            props: {'placeholder': TString()},
            events: {'change': TString()},
            layout: LayoutCapability(),
          ),
          MFHostComponentImpl((children, props) => Object()),
        )
        ..register(
          'function',
          'fn.echo',
          const ComponentContract(),
          MFFunctionImpl((args) async => {'echo': args['v']}),
        );
      final project = MFProject(
        manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
        pages: [
          MFPage(
            id: 'page',
            route: '/p',
            tree: const MFNode(id: 'root', type: 'Stack', children: [
              MFNode(id: 'name-input', type: 'Input', props: {'placeholder': '名称'}),
            ]),
            stateMembers: const ['draft'],
          ),
        ],
        bindingMaps: const {
          'm': MFBindingMap(
            id: 'm',
            bindings: [
              MFBinding(
                id: 'mirror',
                on: 'name-input.change',
                actions: [
                  MFAdapterAction(kind: 'function', call: 'fn.echo', arguments: {'v': MFRef('prop.value')}, as: 'r'),
                  MFStateAction(target: 'draft', value: MFRef('prev.r.echo')),
                ],
                policy: MFPolicy.rejectNew,
              ),
            ],
          ),
        },
      );
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
        emissionSink: MFNullEmissionSink(),
      );
      await runtime.start();
      await runtime.dispatchEvent('name-input', 'change', payload: {'value': '晨跑'});
      expect(runtime.state.peek('page', 'draft'), '晨跑', reason: '载荷经 prop.value 进入动作链');

      // 契约声明 TString，分发布尔值 → mf.reg.contract-mismatch + 错误边界。
      await runtime.dispatchEvent('name-input', 'change', payload: {'value': false});
      expect(runtime.diagnostics.any((d) => d.code == MFCodes.regContractMismatch), isTrue);
      expect(runtime.boundaryHandler.captured, isNotEmpty);
      expect(runtime.state.peek('page', 'draft'), '晨跑', reason: '违例分发不执行绑定');
    });
  });

  group('信封恢复与查询维度', () {
    test('fromJson 保留 event_id 与 occurred_at；分组支持 session_id 与 payload.*', () {
      final original = MFEventEnvelope(
        eventName: 'ops.habit.checked-in',
        payload: const {'id': 'h1'},
        sessionId: 'ses-1',
        pageInstanceId: 'pg-1',
        route: '/habits',
        releaseId: 'r1',
        rendererVersion: 'v',
        environment: 'dev',
        traceId: 'tr-1',
      );
      final restored = MFEventEnvelope.fromJson(original.toJson());
      expect(restored.eventId, original.eventId);
      expect(restored.occurredAt, original.occurredAt);
      expect(restored.clientSentAt, original.clientSentAt);
      expect(restored.payload['id'], 'h1');
      expect(restored.eventName, 'ops.habit.checked-in');

      final other = MFEventEnvelope(
        eventName: 'ops.habit.checked-in',
        payload: const {'id': 'h2'},
        sessionId: 'ses-2',
        pageInstanceId: 'pg-2',
        route: '/habits',
        releaseId: 'r1',
        rendererVersion: 'v',
        environment: 'dev',
        traceId: 'tr-2',
      );
      final engine = MFLocalQueryEngine(events: () => [original, other]);
      final now = DateTime.now().toUtc();
      final grouped = engine.queryEvents(
        from: now.subtract(const Duration(hours: 1)),
        to: now.add(const Duration(hours: 1)),
        groupBy: const ['session_id'],
      );
      final sessions = (grouped['groups'] as List).length;
      expect(sessions, 2, reason: '按会话去重分组');
      final byHabit = engine.queryEvents(
        from: now.subtract(const Duration(hours: 1)),
        to: now.add(const Duration(hours: 1)),
        groupBy: const ['payload.id'],
      );
      final habits = (byHabit['groups'] as List).length;
      expect(habits, 2, reason: '按载荷维度分组（习惯维度运营指标）');
    });
  });

  group('恢复快照序列化', () {
    test('快照 toJson/fromJson 往返保持全部字段（§16.1 跨会话恢复）', () {
      final snap = MFRecoverySnapshot(
        snapshotVersion: '1.0',
        releaseId: 'r1',
        createdAt: DateTime.utc(2026, 10, 24, 8),
        route: 'habits-page',
        parameters: const {'from': 'notification'},
        pageState: const {'draftName': '阅读'},
        sessionState: const {'theme': 'dark'},
        pendingActions: const ['save-habit'],
        stateRevision: 12,
        unknownSideEffects: const [
          {'call': 'fn.slow', 'state': 'unknown', 'auto_retry': false},
        ],
      );
      final restored = MFRecoverySnapshot.fromJson(snap.toJson());
      expect(restored.snapshotVersion, '1.0');
      expect(restored.releaseId, 'r1');
      expect(restored.createdAt, snap.createdAt);
      expect(restored.route, 'habits-page');
      expect(restored.parameters['from'], 'notification');
      expect(restored.pageState['draftName'], '阅读');
      expect(restored.sessionState['theme'], 'dark');
      expect(restored.pendingActions, ['save-habit']);
      expect(restored.stateRevision, 12);
      expect(restored.unknownSideEffects.first['auto_retry'], false);
    });
  });

  group('注记 args 定向内容', () {
    test('只有声明的参数键进入注记事件 payload', () async {
      final sink = MFInMemorySink();
      final queue = MFTelemetryQueue(sink: sink, batchMax: 64);
      final registry = MFRegistry()
        ..register(
          'primitive',
          'Stack',
          const ComponentContract(
            events: {'press': TString()},
            layout: LayoutCapability(),
          ),
          MFHostComponentImpl((children, props) => Object()),
        )
        ..register(
          'adapter',
          'adapter.check-in',
          const ComponentContract(
            telemetry: MFTelemetryAnnotation(
              events: {'success': 'ops.habit.checked-in'},
              args: ['id'],
            ),
          ),
          MFAdapterImpl((args) async => {'ok': true}),
        );
      final project = MFProject(
        manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
        pages: [
          MFPage(
            id: 'page',
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
                id: 'do-check',
                on: 'root.press',
                actions: [
                  MFAdapterAction(
                    kind: 'adapter',
                    call: 'adapter.check-in',
                    arguments: {'id': MFRef('item.id'), 'secret_note': MFLiteral('内部备注')},
                  ),
                ],
                policy: MFPolicy.rejectNew,
              ),
            ],
          ),
        },
      );
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
        emissionSink: queue,
      );
      await runtime.start();
      await runtime.execute('do-check', item: const {'id': 'h1'});
      await queue.flush();
      final event = sink.delivered.firstWhere((e) => e.eventName == 'ops.habit.checked-in');
      expect(event.payload['id'], 'h1', reason: '声明键进入 payload');
      expect(event.payload.containsKey('secret_note'), isFalse, reason: '未声明键不进入采集面（§24.7 定向内容）');
    });
  });

  group('声明式列表绑定（widget）', () {
    testWidgets('List items 渲染项模板；项内按钮事件携带项上下文执行', (tester) async {
      final registry = MFRegistry()
        ..register(
          'primitive',
          'Stack',
          const ComponentContract(
            events: {'press': TString()},
            layout: LayoutCapability(display: ['block'], sizing: ['hug']),
          ),
          MFHostComponentImpl((children, props) => Object()),
        )
        ..register(
          'primitive',
          'Text',
          const ComponentContract(props: {'text': TString()}, layout: LayoutCapability()),
          MFHostComponentImpl((children, props) => Object()),
        )
        ..register(
          'primitive',
          'Button',
          const ComponentContract(props: {'label': TString()}, events: {'press': TString()}, layout: LayoutCapability()),
          MFHostComponentImpl((children, props) => Object()),
        )
        ..register(
          'primitive',
          'List',
          const ComponentContract(props: {'items': TList()}, layout: LayoutCapability()),
          MFHostComponentImpl((children, props) => Object()),
        )
        ..register(
          'function',
          'fn.mark',
          const ComponentContract(),
          MFFunctionImpl((args) async => {'marked': args['id']}),
        );
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
                  id: 'habit-list',
                  type: 'List',
                  props: {'items': MFRef('state.habits')},
                  children: const [
                    MFNode(id: 'row', type: 'Stack', props: {'direction': 'horizontal'}, children: [
                      MFNode(id: 'name', type: 'Text', props: {'text': MFRef('item.name')}),
                      MFNode(id: 'check-btn', type: 'Button', props: {'label': MFRef('item.action')}),
                    ]),
                  ],
                ),
              ],
            ),
            stateMembers: const ['habits', 'marked'],
          ),
        ],
        bindingMaps: const {
          'm': MFBindingMap(
            id: 'm',
            bindings: [
              MFBinding(
                id: 'check-in',
                on: 'check-btn.press',
                actions: [
                  MFAdapterAction(kind: 'function', call: 'fn.mark', arguments: {'id': MFRef('item.id')}, as: 'r'),
                  MFStateAction(target: 'marked', value: MFRef('prev.r.marked')),
                ],
                policy: MFPolicy.rejectNew,
              ),
            ],
          ),
        },
      );
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
        emissionSink: MFNullEmissionSink(),
      );
      await runtime.start();
      runtime.state.write('page', 'habits', [
        {'id': 'h1', 'name': '晨跑', 'action': '打卡'},
        {'id': 'h2', 'name': '阅读', 'action': '打卡'},
      ]);
      runtime.generation.value++;

      await tester.pumpWidget(MicroFlowApp(project: project, registry: registry, runtime: runtime));
      await tester.pump();

      expect(find.text('晨跑'), findsOneWidget);
      expect(find.text('阅读'), findsOneWidget);
      expect(find.text('打卡'), findsNWidgets(2), reason: '每项各渲染一份模板');

      // 项内按钮：点击“阅读”行 → 事件携带该行项上下文（item.id=h2）。
      await tester.tap(find.text('打卡').last);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(runtime.state.peek('page', 'marked'), 'h2', reason: '项事件携带 item 上下文执行');
    });
  });
}
