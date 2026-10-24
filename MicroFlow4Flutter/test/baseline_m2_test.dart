import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// M2（PLAN.md）观测与恢复闭环的一致性基线测试：
/// 基线 5、8、11、17、27、28（§44.3；4 与 26/27 的其余子面在
/// test/microflow4_flutter_test.dart）。测试名遵循 tool/baseline_coverage.dart
/// 的「基线 N」标记约定。

MFRegistry m2Registry({MFAdapterImpl? slowImpl, MFAdapterImpl? factImpl}) {
  final r = MFRegistry();
  const pageContract = ComponentContract(
    props: {'label': TString()},
    events: {'press': TString()},
    slots: ['content'],
    layout: LayoutCapability(display: ['block'], sizing: ['hug']),
  );
  r.register('primitive', 'Stack', pageContract, MFHostComponentImpl((children, props) => Object()));
  r.register('primitive', 'Text', pageContract, MFHostComponentImpl((children, props) => Object()));
  r.register(
    'adapter',
    'adapter.checkout',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['ok'])},
      telemetry: MFTelemetryAnnotation(
        events: {
          'entry': 'ops.checkout.submitted',
          'success': 'ops.checkout.confirmed',
          'failure': 'diag.checkout.adapter-failed',
        },
        privacyClass: 'operational',
      ),
      trace: MFTracePropagation(direction: 'outbound', carrier: ['mf_trace']),
    ),
    MFAdapterImpl((args) async => {'ok': true, 'external_run_ref': 'run-1'}),
    description: '带注记与追踪传播声明的演示适配器',
  );
  r.register(
    'adapter',
    'adapter.no-trace-ref',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['ok'])},
      trace: MFTracePropagation(direction: 'outbound'),
    ),
    MFAdapterImpl((args) async => {'ok': true}),
    description: '声明传播但不返回运行引用的适配器',
  );
  r.register(
    'function',
    'fn.slow',
    const ComponentContract(),
    slowImpl ??
        MFAdapterImpl(
          (args) async => Future.delayed(const Duration(milliseconds: 200), () => {'ok': true}),
          timeoutMs: 30,
        ),
    description: '超时演示（unknown 台账）',
  );
  r.register(
    'function',
    'fn.fact-confirm',
    const ComponentContract(),
    factImpl ?? MFAdapterImpl((args) async => {'external_run_ref': 'run-9'}),
    description: 'Business Fact 确认演示',
  );
  r.register(
    'function',
    'fn.fact-hang',
    const ComponentContract(),
    MFAdapterImpl((args) async => Future.delayed(const Duration(milliseconds: 200), () => {'external_run_ref': 'late'})),
    description: 'Business Fact 超时演示',
  );
  return r;
}

MFProject m2Project({
  Map<String, MFFinding> findings = const {},
  Map<String, MFRecoveryContract> recoveryContracts = const {},
  bool pageWithFindings = false,
  String? findingsGhostRef,
}) {
  return MFProject(
    manifest: const MFManifest(
      projectId: 'm2-demo',
      entryPage: 'p1',
      defaultTheme: 'theme-light',
    ),
    pages: [
      MFPage(
        id: 'p1',
        route: '/p1',
        tree: MFNode(
          id: 'root',
          type: 'Stack',
          children: [MFNode(id: 'title', type: 'Text', t: 'p1.title')],
        ),
        stateMembers: const ['v'],
        findings: pageWithFindings ? const ['finding-reg-1'] : (findingsGhostRef != null ? [findingsGhostRef] : const []),
      ),
      MFPage(
        id: 'p2',
        route: '/p2',
        tree: const MFNode(id: 'root2', type: 'Stack'),
        stateMembers: const ['v2'],
      ),
    ],
    navigation: const MFNavigationSpec(edges: [MFNavEdge(from: 'p1', to: 'p2')]),
    bindingMaps: const {
      'm2-map': MFBindingMap(
        id: 'm2-map',
        bindings: [
          MFBinding(
            id: 'checkout-run',
            on: 'root.press',
            actions: [MFAdapterAction(kind: 'adapter', call: 'adapter.checkout')],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'no-trace-ref-run',
            on: 'title.press',
            actions: [MFAdapterAction(kind: 'adapter', call: 'adapter.no-trace-ref')],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'slow-load',
            on: 'root.press',
            actions: [MFAdapterAction(kind: 'function', call: 'fn.slow')],
            policy: MFPolicy.rejectNew,
          ),
        ],
      ),
    },
    tokens: const {
      'theme-light': MFTokenSet(id: 'theme-light', tokens: {'color.action': '#2563eb'}),
    },
    i18n: const MFI18nCatalog(
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN', 'en'],
      fallback: {'en': 'zh-CN'},
      messages: {
        'p1.title': {'zh-CN': '页面一', 'en': 'Page One'},
        'p1.only-zh': {'zh-CN': '仅中文'},
      },
    ),
    findings: findings,
    recoveryContracts: recoveryContracts,
  );
}

MFPageInstance m2Instance(MFProject project, {String locale = 'en'}) => MFPageInstance(
      id: 'pg-test',
      definition: project.page('p1')!,
      params: const {},
      frozen: MFFrozenContext(configVersion: 'config-1', theme: 'theme-light', locale: locale),
      provided: const {},
    );

void main() {
  group('基线 5 —— i18n 回退链与缺失翻译诊断', () {
    test('基线 5：缺失翻译按回退链展示并上报 mf.i18n.missing-translation', () {
      final project = m2Project();
      final instance = m2Instance(project, locale: 'en');
      final diags = <MFDiag>[];
      // en 命中：直接展示，无诊断。
      final direct = mfLocalizePageMessage(
          project: project, instance: instance, messageId: 'p1.title', diagnostics: diags);
      expect(direct, 'Page One');
      expect(diags, isEmpty);
      // en 缺失、回退链 en→zh-CN 命中：按回退链展示并上报缺失翻译（§42.5）。
      final fellBack = mfLocalizePageMessage(
          project: project, instance: instance, messageId: 'p1.only-zh', diagnostics: diags);
      expect(fellBack, '仅中文');
      expect(diags.any((d) => d.code == MFCodes.i18nMissingTranslation), isTrue);
      // 完全缺失：上报并回退 messageId，不静默、不中断。
      final missing = mfLocalizePageMessage(
          project: project, instance: instance, messageId: 'p1.never', diagnostics: diags);
      expect(missing, 'p1.never');
      expect(diags.where((d) => d.code == MFCodes.i18nMissingTranslation).length, 2);
    });
  });

  group('基线 8 —— 采集注记走完整校验管道', () {
    test('基线 8：注记事件经运行时零埋点发射并通过信封校验入队', () async {
      final project = m2Project();
      final registry = m2Registry();
      final sink = MFInMemorySink();
      final telemetry = MFTelemetryQueue(sink: sink, batchMax: 64);
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'm2-demo', releaseId: 'r1', environment: 'dev'),
        emissionSink: telemetry,
      );
      await runtime.start();
      // 业务侧零埋点：只执行绑定，注记事件由运行时在适配器拦截边界产生。
      await runtime.execute('checkout-run');
      await telemetry.flush();
      final names = sink.delivered.map((e) => e.eventName).toList();
      expect(names, contains('ops.checkout.submitted'), reason: 'entry 触点注记事件');
      expect(names, contains('ops.checkout.confirmed'), reason: 'success 触点注记事件');
      final confirmed = sink.delivered.firstWhere((e) => e.eventName == 'ops.checkout.confirmed');
      expect(confirmed.privacyClass, 'operational');
      expect(confirmed.actionRequestId, isNotNull, reason: '走完整管道：身份字段注入齐全');
      expect(confirmed.traceId, isNotEmpty);
    });

    test('基线 8（静态）：注记引用未登记事件/隐私分类/采样策略非法是构建错误', () {
      final project = m2Project();
      final badRegistry = MFRegistry()
        ..register(
          'adapter',
          'adapter.bad',
          const ComponentContract(
            telemetry: MFTelemetryAnnotation(
              events: {'entry': 'not-registered-event'},
              privacyClass: 'public',
              samplingRatio: 1.5,
            ),
          ),
          MFAdapterImpl((args) async => {'ok': true}),
        );
      final diags = MFValidator(project: project, registry: badRegistry).validate().diagnostics;
      final invalid = diags.where((d) => d.code == MFCodes.teleAnnotationInvalid).toList();
      expect(invalid.length, 3, reason: '事件未登记、隐私分类非法、采样比例非法各一条');
    });
  });

  group('基线 11 —— 追踪传播与外部运行引用', () {
    test('基线 11：出站上下文运行时注入；外部运行引用记录；缺引用记录原因不当作失败', () async {
      final project = m2Project();
      Map<String, Object?>? seen;
      final registry = m2Registry(
        // 捕获出站参数
      );
      registry.register(
        'adapter',
        'adapter.checkout',
        registry.entry('adapter.checkout')!.contract,
        MFAdapterImpl((args) async {
          seen = args;
          return {'ok': true, 'external_run_ref': 'run-1'};
        }),
      );
      final telemetry = MFTelemetryQueue(sink: MFInMemorySink(), batchMax: 64);
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'm2-demo', releaseId: 'r1', environment: 'dev'),
        emissionSink: telemetry,
      );
      await runtime.start();
      await runtime.execute('checkout-run');
      // 出站上下文由运行时注入（§24.8 最小集）。
      final trace = seen!['mf_trace'] as Map<String, Object?>;
      expect(trace['trace_id'], runtime.ids.traceId);
      expect(trace['release_id'], 'r1');
      expect(trace['page_instance_id'], runtime.current!.id);
      expect(trace['action_request_id'], isNotNull);
      // 外部运行引用按不透明标识记录。
      expect(runtime.externalRunRefs, contains('run-1'));
      expect(runtime.debugContext()['external_run_refs'], contains('run-1'));

      // 声明了传播但未返回运行引用：记录原因，不视为调用失败。
      final diagsBefore = runtime.diagnostics.length;
      final result = await runtime.execute('no-trace-ref-run');
      expect(result.results['last'], isA<Map>(), reason: '调用本身成功');
      expect(runtime.diagnostics.length, greaterThan(diagsBefore));
      expect(
        runtime.diagnostics.any((d) => d.code == MFCodes.teleTraceRefMissing),
        isTrue,
      );
    });

    test('基线 11（Business Fact 侧）：未获得运行引用的确认进入 unknown', () async {
      final project = m2Project();
      final registry = m2Registry();
      registry.register(
        'function',
        'fn.fact-confirm',
        const ComponentContract(),
        MFAdapterImpl((args) async => {'ok': true}), // 无 external_run_ref
      );
      final telemetry = MFTelemetryQueue(sink: MFInMemorySink(), batchMax: 64);
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'm2-demo', releaseId: 'r1', environment: 'dev'),
        emissionSink: telemetry,
      );
      await runtime.start();
      final record = await runtime.facts.submit(
        factRef: 'order-create',
        idempotencyKey: 'order-1',
        call: 'fn.fact-confirm',
      );
      expect(record.state, 'unknown', reason: '§24.8：无可关联运行引用的确认只能是 unknown');
      expect(record.reason, 'no-external-run-ref');
    });
  });

  group('基线 17 —— findings 回流', () {
    test('基线 17：findings 按 schema 版本回流并进入校验报告（回归基线可消费）', () {
      final session = MFAuthoringSession(project: m2Project(), registry: m2Registry());
      final result = session.registerFinding(
        findingId: 'finding-reg-1',
        findingType: 'regression-key',
        targetRef: 'p1',
        summary: '幽灵依赖回归集群',
        sourceRef: 'analysis:ops-2026-10',
        checkRef: 'test:microflow4_flutter_test:容器信息契约',
      );
      expect(result.ok, isTrue, reason: '结构化登记走同一门禁：${result.diagnostics}');
      final project = session.project;
      expect(project.findings['finding-reg-1']!.schemaVersion, '1.0');
      expect(project.page('p1')!.findings, contains('finding-reg-1'), reason: 'target 资源携带 findings 引用');
      final validation = session.validateProject();
      expect(validation.findingsReport, isNotEmpty);
      final entry = validation.findingsReport.firstWhere((e) => e['finding'] == 'finding-reg-1');
      expect(entry['target'], 'p1');
      expect(entry['finding_type'], 'regression-key');
      expect(entry['check_ref'], isNotNull);
    });

    test('基线 17（静态）：自由文本替代（未登记引用）与 regression-key 未绑定校验是静态错误', () {
      // 自由文本替代：页面携带未登记的 findings 引用。
      final ghost = MFValidator(
        project: m2Project(findingsGhostRef: '随手记的一段话'),
        registry: m2Registry(),
      ).validate();
      expect(ghost.diagnostics.any((d) => d.code == MFCodes.refDangling), isTrue);

      // regression-key 未绑定可执行校验。
      final unbound = MFValidator(
        project: m2Project(findings: {
          'f1': const MFFinding(
            findingId: 'f1',
            findingType: 'regression-key',
            targetRef: 'p1',
          ),
        }),
        registry: m2Registry(),
      ).validate();
      expect(unbound.diagnostics.any((d) => d.code == MFCodes.regFindingInvalid), isTrue);

      // 类型枚举外 + target 不可解析。
      final badType = MFValidator(
        project: m2Project(findings: {
          'f2': const MFFinding(findingId: 'f2', findingType: 'note', targetRef: 'nowhere'),
        }),
        registry: m2Registry(),
      ).validate();
      expect(badType.diagnostics.where((d) => d.code == MFCodes.regFindingInvalid).length, 1);
      expect(badType.diagnostics.any((d) => d.code == MFCodes.refDangling), isTrue);
    });
  });

  group('基线 27 —— Recovery 执行器', () {
    test('基线 27（静态）：auto_retry=true 的恢复契约是构建错误', () {
      final diags = MFValidator(
        project: m2Project(recoveryContracts: {
          'bad': const MFRecoveryContract(id: 'bad', unknownSideEffectsAutoRetry: true),
        }),
        registry: m2Registry(),
      ).validate().diagnostics;
      expect(diags.any((d) => d.code == MFCodes.buildRecoveryAutoRetry), isTrue);
    });

    test('基线 27：恢复后未知结果副作用只进入 unknown 且可查询，不自动重试', () async {
      var invocations = 0;
      final registry = m2Registry(
        slowImpl: MFAdapterImpl((args) async {
          invocations++;
          return Future.delayed(const Duration(milliseconds: 200), () => {'ok': true});
        }, timeoutMs: 30),
      );
      final telemetry = MFTelemetryQueue(sink: MFInMemorySink(), batchMax: 64);
      final runtime = MFRuntime(
        project: m2Project(recoveryContracts: {
          'default': const MFRecoveryContract(id: 'default'),
        }),
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'm2-demo', releaseId: 'r1', environment: 'dev'),
        emissionSink: telemetry,
      );
      await runtime.start();
      runtime.state.writeDeep('page', 'v', 'before');
      await runtime.execute('slow-load');
      expect(runtime.unknownResults, hasLength(1), reason: '超时副作用进入 unknown 台账');
      expect(runtime.unknownResults.first['auto_retry'], false);

      final contract = runtime.project.recoveryContracts['default']!;
      final snapshot = runtime.recovery.collect(contract);
      final outcome = await runtime.recovery.restore(snapshot, contract: contract);
      expect(outcome.restored, isTrue, reason: '同 release 且版本匹配：恢复');
      // 未知结果副作用 surface-as-unknown：台账原样保留、可查询、不重试。
      expect(runtime.unknownResults, hasLength(1));
      expect(runtime.unknownResults.first['state'], 'unknown');
      expect(invocations, 1, reason: '恢复不重放/不重试未知副作用');
      // 页面状态按声明成员回放。
      expect(runtime.state.peek('page', 'v'), 'before');
    });

    test('基线 27：快照版本不匹配进入错误边界；过期与无迁移器全新启动', () async {
      final contract = const MFRecoveryContract(id: 'default', maxAgeSeconds: 60);
      final telemetry = MFTelemetryQueue(sink: MFInMemorySink(), batchMax: 64);
      final runtime = MFRuntime(
        project: m2Project(recoveryContracts: {'default': contract}),
        registry: m2Registry(),
        ids: MFInstanceIdentifiers(projectId: 'm2-demo', releaseId: 'r2', environment: 'dev'),
        emissionSink: telemetry,
      );
      await runtime.start();

      // 版本不匹配 → 错误边界（§16.1）。
      final mismatch = MFRecoverySnapshot(
        snapshotVersion: '0.9',
        releaseId: 'r1',
        createdAt: DateTime.now().toUtc(),
        route: 'p1',
      );
      final out1 = await runtime.recovery.restore(mismatch, contract: contract);
      expect(out1.restored, isFalse);
      expect(out1.reason, 'fresh-start:snapshot-version-mismatch');
      expect(runtime.boundaryHandler.captured, isNotEmpty,
          reason: '快照 schema 版本不匹配进错误边界');

      // 过期 → 按声明全新启动。
      final expired = MFRecoverySnapshot(
        snapshotVersion: '1.0',
        releaseId: 'r2',
        createdAt: DateTime.now().toUtc().subtract(const Duration(seconds: 120)),
        route: 'p1',
      );
      final out2 = await runtime.recovery.restore(expired, contract: contract);
      expect(out2.restored, isFalse);
      expect(out2.reason, 'fresh-start:expired');

      // release 变化且无迁移器 → 全新启动；登记迁移器后显式迁移恢复。
      final fromOldRelease = MFRecoverySnapshot(
        snapshotVersion: '1.0',
        releaseId: 'r1',
        createdAt: DateTime.now().toUtc(),
        route: 'p1',
        pageState: {'v': 'old-release-value'},
      );
      final out3 = await runtime.recovery.restore(fromOldRelease, contract: contract);
      expect(out3.restored, isFalse);
      expect(out3.reason, 'fresh-start:release-migration-missing');

      runtime.recovery.registerMigrator('mig-r1-r2', (state) => {...state, 'v': 'migrated'});
      final migrated = const MFRecoveryContract(id: 'default', maxAgeSeconds: 60, migrators: ['mig-r1-r2']);
      final out4 = await runtime.recovery.restore(fromOldRelease, contract: migrated);
      expect(out4.restored, isTrue);
      expect(runtime.state.peek('page', 'v'), 'migrated');
    });
  });

  test('§29：Debug 控制面——订阅拦截事件流与检查点暂停/继续', () async {
    final project = m2Project();
    final registry = m2Registry();
    final telemetry = MFTelemetryQueue(sink: MFInMemorySink(), batchMax: 64);
    final runtime = MFRuntime(
      project: project,
      registry: registry,
      ids: MFInstanceIdentifiers(projectId: 'm2-demo', releaseId: 'r1', environment: 'dev'),
      emissionSink: telemetry,
    );
    // 订阅先于启动：拦截边界事件流从首个导航事件起可达（§29）。
    final session = MFDebugSession(
      sessionId: 'dbg-1',
      principal: 'dev-a',
      level: MFDebugLevel.local,
      scopeReleaseId: 'r1',
      scopePageInstanceId: 'pg-any',
      authorizedGrants: const ['read-context', 'subscribe', 'checkpoint-pause'],
    );
    final controller = MFDebugController(session: session, runtime: runtime);
    final events = <Map<String, Object?>>[];
    final sub = controller.subscribe(events.add);
    await runtime.start();

    // 检查点：挂起 → 读快照 → 继续（§29「在已声明的检查点暂停、继续和读取快照」）。
    runtime.declareCheckpoints(const ['checkout-run']);
    controller.pauseAt('checkout-run');
    final executing = runtime.execute('checkout-run');
    Future<void> waitFor(bool Function() cond) async {
      for (var i = 0; i < 500 && !cond(); i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
    }
    await waitFor(() => events.any((e) => e['kind'] == 'checkpoint'));
    expect(runtime.inFlightBindings, contains('checkout-run'), reason: '检查点处挂起');
    final snap = controller.snapshot();
    expect((snap.context['stack'] as List).isNotEmpty, isTrue, reason: '暂停时可读快照');
    await controller.resume('checkout-run');
    final result = await executing;
    expect(result.results['last'], isA<Map>());
    expect(events.any((e) => e['kind'] == 'navigation'), isTrue, reason: '拦截边界事件流：导航');
    expect(events.any((e) => e['kind'] == 'action'), isTrue, reason: '拦截边界事件流：动作');
    sub.cancel();

    // 逐 grant 授权：未授予 subscribe 拒绝。
    final denied = MFDebugSession(
      sessionId: 'dbg-2',
      principal: 'x',
      level: MFDebugLevel.preview,
      scopeReleaseId: 'r1',
      scopePageInstanceId: 'pg',
      authorizedGrants: const ['read-context'],
    );
    expect(
      () => MFDebugController(session: denied, runtime: runtime).subscribe(events.add),
      throwsA(isA<MFDebugUnauthorized>()),
    );
  });

  test('§30：Ingest 参考实现与 Query/Export——批量/退避/断网缓存与口径一致', () async {
    var failNext = 2; // 前两次传输失败，模拟断网
    final deliveredBatches = <List<MFEventEnvelope>>[];
    final ingest = MFReliableIngest(
      transport: (batch) async {
        if (failNext > 0) {
          failNext--;
          throw StateError('transport-down');
        }
        deliveredBatches.add(batch);
      },
      batchMax: 2,
      maxAttempts: 2,
      backoff: (_) => Duration.zero,
    );
    MFEventEnvelope env(int i) => MFEventEnvelope(
          eventName: i.isEven ? 'ops.page.viewed' : 'ops.feature.used',
          payload: {'i': i},
          sessionId: 's',
          pageInstanceId: 'pg-$i',
          route: '/r',
          releaseId: 'r1',
          rendererVersion: 'v',
          environment: 'dev',
          traceId: 'tr-1',
        );
    final batch = [env(0), env(1), env(2), env(3), env(4)];
    await ingest.accept(batch);
    // 传输失败 → 退避重试 → 最终进入有界断网缓存并记录缺口窗口。
    expect(ingest.dataQuality()['delivered'], 0);
    expect(ingest.dataQuality()['offline_cached'], greaterThan(0));
    expect(ingest.offlineWindows, isNotEmpty, reason: '断网窗口 = 缺口区间来源');
    failNext = 0;
    await ingest.drainOffline();
    expect(ingest.dataQuality()['delivered'], 5, reason: '恢复后补齐断网缓存');
    expect(ingest.dataQuality()['attempts'], greaterThanOrEqualTo(4), reason: '退避重试计数');

    // event_id 去重：同一信封重复投递幂等。
    final before = ingest.dataQuality()['deduplicated'];
    await ingest.accept([batch.first]);
    expect(ingest.dataQuality()['deduplicated'], (before as int) + 1);

    // Query/Export（§30.2）：与 Ingest 同源数据与口径。
    final engine = MFLocalQueryEngine(
      events: () => [for (final b in deliveredBatches) ...b],
      dataQuality: ingest.dataQuality,
      gapWindows: () => [for (final w in ingest.offlineWindows) Map<String, String>.of(w)],
    );
    final now = DateTime.now().toUtc();
    final res = engine.queryEvents(
      from: now.subtract(const Duration(hours: 1)),
      to: now.add(const Duration(hours: 1)),
      eventName: 'ops.page.viewed',
      pageSize: 2,
    );
    expect(res['total'], 3, reason: '过滤出 3 条 viewed 事件');
    expect((res['events'] as List).length, 2, reason: '分页上限生效');
    expect(res['page_token'], isNotNull);
    expect(res['loss_rate'], ingest.dataQuality()['loss_rate'], reason: '丢失率口径一致');
    final trace = engine.getTrace('tr-1');
    expect((trace['events'] as List).length, 5, reason: '追踪汇集按 trace_id');
    final exported = engine.exportEvents(
      from: now.subtract(const Duration(hours: 1)),
      to: now.add(const Duration(hours: 1)),
    );
    expect((exported['gap_intervals'] as List).isNotEmpty, isTrue, reason: '导出携带缺口区间声明');
    expect(exported['cursor'], isNull, reason: '一批导完（6 条 ≤ maxPageSize）');
    expect(engine.getEventSchema('ops.page.viewed')['family'], 'operational-standard');
    expect(engine.getEventSchema('diag.x.y')['family'], 'diagnostic');
    expect(engine.getDataQuality()['delivered'], ingest.dataQuality()['delivered']);
  });

  group('基线 28 —— Business Fact 幂等确认', () {
    test('基线 28：按去重身份幂等确认；超时进入 unknown 可查询', () async {
      final project = m2Project();
      final registry = m2Registry();
      final telemetry = MFTelemetryQueue(sink: MFInMemorySink(), batchMax: 64);
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'm2-demo', releaseId: 'r1', environment: 'dev'),
        emissionSink: telemetry,
      );
      await runtime.start();

      final first = await runtime.facts.submit(
        factRef: 'order-create',
        idempotencyKey: 'order-1',
        call: 'fn.fact-confirm',
      );
      expect(first.state, 'confirmed', reason: '确认关联外部运行引用（§24.8）');
      expect(first.externalRunRef, 'run-9');
      expect(runtime.externalRunRefs, contains('run-9'));

      // 去重身份：重复提交幂等返回既有记录 + info 诊断。
      final duplicate = await runtime.facts.submit(
        factRef: 'order-create',
        idempotencyKey: 'order-1',
        call: 'fn.fact-confirm',
      );
      expect(identical(duplicate, first), isTrue);
      expect(runtime.diagnostics.any((d) => d.code == MFCodes.dataFactDuplicate), isTrue);

      // 超时进入 unknown，可查询。
      final timedOut = await runtime.facts.submit(
        factRef: 'file-write',
        idempotencyKey: 'order-2',
        call: 'fn.fact-hang',
        timeoutMs: 30,
      );
      expect(timedOut.state, 'unknown');
      expect(runtime.facts.query('order-2')!.state, 'unknown');
      expect(runtime.facts.query('order-1')!.state, 'confirmed');
      expect(runtime.facts.all, hasLength(2));
    });
  });
}
