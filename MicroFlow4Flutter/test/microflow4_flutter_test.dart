import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// MicroFlow4Flutter consistency tests, anchored on the frontend-framework-
/// design §44.3 baseline (只测静态可决定与运行时可判定的子集).

/// 收集总包与子包下的 Dart 文件。
Set<File> _dartFiles(List<String> roots, {String suffix = '.dart', bool underLib = false}) {
  return {
    for (final rel in roots)
      if (Directory(rel).existsSync())
        ...Directory(rel)
            .listSync(recursive: true)
            .whereType<File>()
            .where((f) => f.path.endsWith(suffix) && (!underLib || f.path.startsWith('lib/') || f.path.contains('/lib/'))),
  };
}

/// 从当前目录向上回溯定位仓库内文件（baselines.json 位于 MicroFlow4Flutter/）。
File? _locateRepoFile(String rel) {
  var dir = Directory.current.path;
  for (var i = 0; i < 4; i++) {
    final candidate = File('$dir/$rel');
    if (candidate.existsSync()) return candidate;
    final parent = File('$dir/..').resolveSymbolicLinksSync();
    if (parent == dir) break;
    dir = parent;
  }
  return null;
}

MFRegistry demoRegistry() {
  final r = MFRegistry();
  for (final id in MFTierA.required) {
    final contract = ComponentContract(
      props: switch (id) {
        'Text' => {'text': const TString()},
        'Button' => {'label': const TString(), 'variant': const TEnum(['primary', 'secondary', 'danger'])},
        'Input' => {'placeholder': const TString(), 'readOnly': const TBool()},
        'Icon' => {'size': const TNumber(), 'color': const TString()},
        'Image' => {'src': const TString()},
        'Checkbox' => {'value': const TBool()},
        'Select' => {'label': const TString()},
        _ => const {},
      },
      events: switch (id) {
        'Button' => {'press': const TString()},
        'Input' => {'change': const TString()},
        'Checkbox' => {'change': const TString()},
        'Select' => {'change': const TString()},
        _ => const {},
      },
      slots: const ['content'],
      layout: const LayoutCapability(display: ['block', 'inline'], sizing: ['hug', 'fill', 'fixed']),
    );
    r.register('primitive', id, contract, MFHostComponentImpl((children, props) => Object()));
  }
  return r;
}

/// 模型组合组件 + 双实例（§2.6，基线 1）。
MFProject demoProject() {
  return MFProject(
    manifest: const MFManifest(
      projectId: 'notes-demo',
      entryPage: 'notes-page',
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN', 'en'],
    ),
    pages: [
      MFPage(
        id: 'notes-page',
        route: '/notes',
        tree: MFNode(
          id: 'root',
          type: 'Stack',
          children: [
            MFNode(id: 'title', type: 'Text', props: {}),
          ],
        ),
        stateMembers: ['hasChanges', 'count'],
      ),
    ],
    i18n: const MFI18nCatalog(
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN', 'en'],
      fallback: {'en': 'zh-CN'},
      messages: {
        'notes.title': {'zh-CN': '备忘'},
      },
    ),
  );
}

void main() {
  test('注册/未注册引用检查（基线 13、15）', () {
    final validator = MFValidator(
      project: demoProject(),
      registry: demoRegistry(),
    );
    final v = validator.validate();
    expect(v.ok, isTrue);
  });

  test('未注册类型引用是静态错误（基线 13）', () {
    final project = demoProject();
    final broken = MFProject(
      manifest: project.manifest,
      pages: [
        MFPage(
          id: 'notes-page',
          route: '/notes',
          tree: const MFNode(id: 'bad', type: 'NoSuchWidget'),
        ),
      ],
      i18n: project.i18n,
    );
    final v = MFValidator(project: broken, registry: demoRegistry()).validate();
    expect(v.ok, isFalse);
    expect(v.diagnostics.any((d) => d.code == 'mf.reg.unregistered-ref'), isTrue);
  });

  test('未声明并发策略的绑定是静态错误（基线 26）', () {
    final project = demoProject();
    final withBinding = MFProject(
      manifest: project.manifest,
      pages: [
        MFPage(
          id: 'notes-page',
          route: '/notes',
          tree: const MFNode(id: 'btn', type: 'Button', props: {'label': '保存'}),
          stateMembers: const ['hasChanges'],
        ),
      ],
      bindingMaps: {
        'm1': MFBindingMap(
          id: 'm1',
          bindings: [
            MFBinding(id: 'b1', on: 'btn.press', policy: MFPolicy.rejectNew),
            MFBinding(id: 'b2', on: 'btn.press'),
          ],
        ),
      },
      i18n: project.i18n,
    );
    final v = MFValidator(project: withBinding, registry: demoRegistry()).validate();
    expect(v.diagnostics.any((d) => d.code == 'mf.binding.no-concurrency'), isTrue);
    expect(v.ok, isFalse, reason: '并发策略声明完整是 §39.3 静态检查项（缺失为错误）');
  });

  test('导航目标不存在 / 孤立页面 / 入口缺失（§9）', () {
    final project = demoProject();
    final bad = MFProject(
      manifest: project.manifest,
      pages: [
        MFPage(
          id: 'notes-page',
          route: '/notes',
          tree: MFNode(
            id: 'root',
            type: 'Stack',
            children: [const MFNode(id: 'btn', type: 'Button', props: {'label': 'go'})],
          ),
          stateMembers: const [],
        ),
        MFPage(id: 'orphan', route: '/orphan', tree: const MFNode(id: 'orphan-root', type: 'Text', props: {'text': 'x'})),
      ],
      bindingMaps: {
        'm': MFBindingMap(
          id: 'm',
          bindings: [MFBinding(id: 'b', on: 'ghost-node.press', policy: MFPolicy.rejectNew)],
        ),
      },
      i18n: project.i18n,
    );
    final v = MFValidator(project: bad, registry: demoRegistry()).validate();
    expect(v.diagnostics.any((d) => d.code == 'mf.nav.isolated-page'), isTrue);
    expect(v.diagnostics.any((d) => d.code == 'mf.binding.event-unknown'), isTrue);
  });

  test('i18n t+text 互斥与 message 引用缺失（§42，基线 30 部分）', () {
    final project = demoProject();
    final bad = MFProject(
      manifest: project.manifest,
      pages: [
        MFPage(
          id: 'notes-page',
          route: '/notes',
          tree: const MFNode(id: 't', type: 'Text', props: {'text': 'hello'}, t: 'notes.title'),
        ),
      ],
      i18n: project.i18n,
    );
    final v = MFValidator(project: bad, registry: demoRegistry()).validate();
    expect(v.diagnostics.any((d) => d.code == 'mf.i18n.channel-conflict'), isTrue);
  });

  test('运行时：启动、双实例隔离、导航与标准事件族零埋点产出（基线 1、29）', () async {
    final sink = MFInMemorySink();
    final fw = MicroFlowFramework.create(
      project: demoProject(),
      registry: demoRegistry(),
      environment: 'preview',
      releaseId: 'r1',
      telemetrySink: sink,
    );
    final runtime = fw.runtime;
    await runtime.start();
    expect(runtime.current, isNotNull);
    expect(runtime.current!.definition.id, 'notes-page');
    await fw.telemetry.flush();
    final names = sink.delivered.map((e) => e.eventName).where((n) => n.startsWith('ops.'));
    expect(names, contains('ops.page.viewed'));
    final envelope = sink.delivered.first;
    expect(envelope.releaseId, 'r1');
    expect(envelope.pageInstanceId, isNotEmpty);
    expect(envelope.identity.containsKey('user_ref'), isTrue);
    // 凭据不得进入事件（§24.2 envelope schema validation）
    final badEnvelope = MFEventEnvelope(
      eventName: 'diag.test',
      payload: {},
      sessionId: 's',
      pageInstanceId: 'p',
      route: '/r',
      releaseId: 'r',
      rendererVersion: 'v',
      environment: 'dev',
      traceId: 't',
      identity: {'user_token': 'abc'},
    );
    expect(badEnvelope.validate(), isNotNull);
  });

  test('绑定执行：guard 为假不执行且不报错；状态写入触发 generation（基线 2）', () async {
    final model = MFProject(
      manifest: const MFManifest(projectId: 'p1', entryPage: 'page'),
      pages: [
        MFPage(
          id: 'page',
          route: '/p',
          tree: MFNode(
            id: 'root',
            type: 'Stack',
            children: [const MFNode(id: 'btn', type: 'Button', props: {'label': 'go'})],
          ),
          stateMembers: const ['count'],
        ),
      ],
      bindingMaps: {
        'm': MFBindingMap(
          id: 'm',
          bindings: [
            MFBinding(
              id: 'guard-binding',
              on: 'btn.press',
              guard: MFExpr.parse({'gt': [{'ref': 'state.count'}, 0]}),
              actions: [MFStateAction(target: 'count', value: MFLiteral(1))],
              policy: MFPolicy.rejectNew,
            ),
            MFBinding(
              id: 'set-binding',
              on: 'btn.press',
              actions: [MFStateAction(target: 'count', value: MFLiteral(1))],
              policy: MFPolicy.cancelPrevious,
            ),
          ],
        ),
      },
    );
    final sink = MFInMemorySink();
    final fw = MicroFlowFramework.create(
      project: model,
      registry: demoRegistry(),
      environment: 'dev',
      releaseId: 'r',
      telemetrySink: sink,
    );
    final runtime = fw.runtime;
    await runtime.start();
    final before = runtime.state.peek('page', 'count');
    expect(before, isNull);
    // 先建一个 count 值供 guard 读取
    runtime.state.write('page', 'count', 0);
    final r1 = await runtime.execute('guard-binding');
    expect(r1.results['guard'], false);
    expect(runtime.state.peek('page', 'count'), 0);
    final r2 = await runtime.execute('set-binding');
    expect(r2.results['last'], 1);
    expect(runtime.state.peek('page', 'count'), 1);
    await fw.telemetry.flush();
    expect(sink.delivered.where((e) => e.eventName == 'ops.feature.used').length, 2);
  });

  test('动作函数：注册、调用、超时进入 unknown 不当作失败（基线 3、27）', () async {
    final registry = demoRegistry();
    registry.register(
      'function',
      'local.slow',
      ComponentContract(props: {'output': const TObject()}),
      MFFunctionImpl((args) => Future.delayed(const Duration(milliseconds: 200)), timeoutMs: 20),
    );
    final project = MFProject(
      manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
      pages: [MFPage(id: 'page', route: '/p', tree: MFNode(id: 'root', type: 'Stack', children: [const MFNode(id: 'btn', type: 'Button', props: {'label': 'call'})]), stateMembers: const ['result'])],
      bindingMaps: {
        'm': MFBindingMap(
          id: 'm',
          bindings: [
            MFBinding(
              id: 'call-slow',
              on: 'btn.press',
              actions: [
                MFAdapterAction(kind: 'function', call: 'local.slow', as: 'value'),
                MFStateAction(target: 'result', value: MFRef('prev.value')),
              ],
              policy: MFPolicy.rejectNew,
            ),
          ],
        ),
      },
    );
    final fw = MicroFlowFramework.create(
      project: project,
      registry: registry,
      environment: 'dev',
      releaseId: 'r',
    );
    final runtime = fw.runtime;
    final _ = fw; // observability 面未直接使用
    await runtime.start();
    final result = await runtime.execute('call-slow');
    expect(result.results['last'], isA<MFUnknownResult>());
    expect(runtime.diagnostics.where((d) => d.code == 'mf.data.timeout'), isNotEmpty);
  });

  test('实验冻结：停用不改写历史，运行实例读取冻结值（基线 7）', () {
    final ex = MFExperimentState();
    ex.acceptCandidate({
      'experiment_id': 'exp-1',
      'assignment_id': 'a1',
      'variant': 'treatment',
      'known_variant_check': true,
    }, knownVariants: ['control', 'treatment']);
    expect(ex.variantOf('exp-1'), 'treatment');
    ex.acceptCandidate({'experiment_id': 'exp-2', 'assignment_id': 'a2', 'variant': 'unknown-variant'}, knownVariants: const ['control', 'treatment']);
    expect(ex.variantOf('exp-2'), isNull); // 回退，不写入运行上下文
    expect(ex.shouldConfirmExposure('exp-1', visible: true), isTrue);
    expect(ex.shouldConfirmExposure('exp-1', visible: false), isFalse);
  });

  test('Debug 会话权限门（§29）', () {
    final session = MFDebugSession(
      sessionId: 'dbg-1',
      principal: 'op-agent',
      level: MFDebugLevel.productionControlled,
      scopeReleaseId: 'r1',
      scopePageInstanceId: 'pg-1',
      authorizedGrants: ['read-context'],
    );
    final snapshot = requireSnapshot(session: session, context: {'token': 'abc', 'state': 'ok'});
    expect(snapshot.export()['snapshot'], containsPair('state', 'ok'));
    expect((snapshot.export()['snapshot'] as Map).containsKey('token'), isFalse);
    final noGrant = MFDebugSession(
      sessionId: 'dbg-2',
      principal: 'op-agent',
      level: MFDebugLevel.productionControlled,
      scopeReleaseId: 'r1',
      scopePageInstanceId: 'pg-1',
      authorizedGrants: const [],
    );
    expect(() => requireSnapshot(session: noGrant, context: {}), throwsA(isA<MFDebugUnauthorized>()));
  });

  test('输出 Schema 不匹配产生类型化错误，不静默截断（基线 4）', () async {
    final registry = demoRegistry();
    registry.register(
      'adapter',
      'adapter.notes-list',
      ComponentContract(props: {'output': const TList(item: TString())}),
      MFAdapterImpl((args) async => 42), // 与 output Schema 不符
    );
    final project = MFProject(
      manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
      pages: [MFPage(id: 'page', route: '/p', tree: MFNode(id: 'root', type: 'Stack', children: const [MFNode(id: 'btn', type: 'Button', props: {'label': 'load'})]), stateMembers: const ['rows'])],
      bindingMaps: {
        'm': MFBindingMap(
          id: 'm',
          bindings: [
            MFBinding(
              id: 'load',
              on: 'btn.press',
              actions: [MFAdapterAction(kind: 'adapter', call: 'adapter.notes-list', as: 'rows')],
              policy: MFPolicy.rejectNew,
            ),
          ],
        ),
      },
    );
    final fw = MicroFlowFramework.create(
      project: project,
      registry: registry,
      environment: 'dev',
      releaseId: 'r',
    );
    await fw.runtime.start();
    final result = await fw.runtime.execute('load');
    expect(result.results['last'], isA<MFUnknownResult>(), reason: '不符 Schema 的输出不得进入状态（§40.3）');
    expect(fw.runtime.diagnostics.where((d) => d.code == 'mf.data.output-invalid'), isNotEmpty);
  });

  test('manifest 类型方言版本不受支持时构建失败（基线 14）', () {
    final project = demoProject();
    final bad = MFProject(
      manifest: const MFManifest(
        projectId: 'p',
        entryPage: 'notes-page',
        typeDialectVersion: '9.9',
      ),
      pages: project.pages,
      i18n: project.i18n,
    );
    final v = MFValidator(project: bad, registry: demoRegistry()).validate();
    expect(v.diagnostics.any((d) => d.code == 'mf.schema.dialect-unsupported'), isTrue);
    expect(v.ok, isFalse, reason: '方言版本不满足时构建失败（§4.6）');
  });

  test('容器信息契约：consumes 解析到上游 provides；provides 变更命中影响分析（基线 16 部分）', () {
    final base = MFProject(
      manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
      pages: [
        MFPage(
          id: 'page',
          route: '/p',
          tree: const MFNode(id: 'root', type: 'Stack', children: [MFNode(id: 'badge', type: 'user-badge')]),
          stateMembers: const [],
          info: const InfoContract(consumes: {'userProfile': true}),
        ),
      ],
      components: {
        'user-badge': MFComponentDefinition(
          id: 'user-badge',
          tree: const MFNode(id: 'b-root', type: 'Text'),
          contract: const ComponentContract(
            props: {},
            info: InfoContract(provides: {'userProfile': 'string'}),
          ),
        ),
      },
    );
    final ok = MFValidator(project: base, registry: demoRegistry()).validate();
    expect(ok.diagnostics.any((d) => d.code == 'mf.state.ghost-dependency'), isFalse,
        reason: 'consumes 可解析到树内上游组件的 provides（§2.8）');
    // 影响分析：provides 的组件被哪些容器消费（§4.3 反向索引）。
    expect(ok.index.usedBy('user-badge'), contains('page'));
    // 移除上游组件后，required consumes 成为幽灵依赖（静态错误）。
    final broken = MFProject(
      manifest: base.manifest,
      pages: [
        MFPage(
          id: 'page',
          route: '/p',
          tree: const MFNode(id: 'root', type: 'Stack'),
          stateMembers: const [],
          info: const InfoContract(consumes: {'userProfile': true}),
        ),
      ],
      i18n: base.i18n,
    );
    final v = MFValidator(project: broken, registry: demoRegistry()).validate();
    expect(v.diagnostics.any((d) => d.code == 'mf.state.ghost-dependency'), isTrue);
  });

  test('结构树属性内联可执行逻辑是静态错误（基线 31 部分）', () {
    final project = demoProject();
    final bad = MFProject(
      manifest: project.manifest,
      pages: [
        MFPage(
          id: 'notes-page',
          route: '/notes',
          tree: const MFNode(
            id: 'evil',
            type: 'Button',
            props: {'label': 'ok', 'handler': {'eval': 'alert(1)'}, 'fn': {'call': 'local.steal'}},
          ),
        ),
      ],
      i18n: project.i18n,
    );
    final v = MFValidator(project: bad, registry: demoRegistry()).validate();
    final inline = v.diagnostics.where((d) => d.code == 'mf.schema.inline-logic').toList();
    expect(inline, isNotEmpty, reason: '§2.9：结构树不得内联命令式逻辑');
    expect(inline.length, 2, reason: 'eval 与 call 两个载体各报一条');
    // 合法的结构化引用不受影响。
    final fine = MFProject(
      manifest: project.manifest,
      pages: [
        const MFPage(
          id: 'notes-page',
          route: '/notes',
          tree: MFNode(id: 't', type: 'Text', props: {'value': {'ref': 'state.count'}}),
          stateMembers: ['count'],
        ),
      ],
      i18n: project.i18n,
    );
    expect(MFValidator(project: fine, registry: demoRegistry()).validate().ok, isTrue);
  });

  test('受控交叉清单外的变体改写面被静态拒绝（基线 32 部分）', () {
    final project = MFProject(
      manifest: demoProject().manifest,
      pages: demoProject().pages,
      i18n: demoProject().i18n,
      crossingList: const MFControlledCrossingList(entries: [
        MFCrossingEntry(surface: 'page.notes-page.theme', source: 'experiment'),
      ]),
    );
    final registered = MFValidator(
      project: project,
      registry: demoRegistry(),
      variantRewrites: const [MFCrossingEntry(surface: 'page.notes-page.theme', source: 'experiment')],
    ).validate();
    expect(registered.ok, isTrue, reason: '已登记改写面通过（§2.9）');
    final outOfScope = MFValidator(
      project: project,
      registry: demoRegistry(),
      variantRewrites: const [
        MFCrossingEntry(surface: 'page.notes-page.tree', source: 'experiment'),
        MFCrossingEntry(surface: 'page.notes-page.theme', source: 'ops-variant'),
        MFCrossingEntry(surface: 'page.notes-page.theme', source: 'hacker'),
      ],
    ).validate();
    final violations = outOfScope.diagnostics.where((d) => d.code == 'mf.exp.variant-out-of-scope').toList();
    expect(violations.length, 3, reason: '未登记面、来源不符与非法来源均被拒绝');
    expect(outOfScope.ok, isFalse);
  });

  test('create_page 纯配置构造：门禁拒绝未注册引用且项目不变（基线 13、§18.3）', () {
    final session = MFAuthoringSession(project: demoProject(), registry: demoRegistry());
    final before = session.project;
    // 引用未注册资源：门禁失败，项目保持原样（§2.7 不存在免门禁通道）。
    final rejected = session.createPage(
      pageId: 'bad-page',
      route: '/bad',
      tree: const MFNode(id: 'root', type: 'NoSuchWidget'),
    );
    expect(rejected.ok, isFalse);
    expect(rejected.diagnostics.any((d) => d.code == 'mf.reg.unregistered-ref'), isTrue);
    expect(identical(session.project, before), isTrue, reason: '门禁失败不产生隐式状态');
    expect(session.revisions, isEmpty);
    // 重复页面 id / 路由是静态错误（§9）。
    final dup = session.createPage(
      pageId: 'notes-page',
      route: '/other',
      tree: const MFNode(id: 'root', type: 'Stack'),
    );
    expect(dup.diagnostics.any((d) => d.code == 'mf.route.duplicate'), isTrue);
    final dupRoute = session.createPage(
      pageId: 'another',
      route: '/notes',
      tree: const MFNode(id: 'root', type: 'Stack'),
    );
    expect(dupRoute.diagnostics.any((d) => d.code == 'mf.route.duplicate'), isTrue);
    // 引用已注册资源但未声明导航：非入口页面被孤立页面门禁拒绝（§9）。
    final isolated = session.createPage(
      pageId: 'about-page',
      route: '/about',
      tree: const MFNode(id: 'root', type: 'Stack'),
    );
    expect(isolated.ok, isFalse);
    expect(isolated.diagnostics.any((d) => d.code == 'mf.nav.isolated-page'), isTrue);
    // 原子声明导航来源：通过门禁，产生修订与前后摘要（§14）。
    final ok = session.createPage(
      pageId: 'about-page',
      route: '/about',
      tree: const MFNode(id: 'root', type: 'Stack', children: [MFNode(id: 't', type: 'Text', props: {'text': 'hi'})]),
      navigationFrom: 'notes-page',
    );
    expect(ok.ok, isTrue, reason: '注册资源可纯配置构造（§2.7）');
    expect(ok.revision, isNotNull);
    expect(ok.beforeSummary, isNot(equals(ok.afterSummary)));
    expect(session.project.page('about-page'), isNotNull);
    // connect_navigation：在既有页面间声明导航边（§14）。
    session.createPage(
      pageId: 'p4',
      route: '/p4',
      tree: const MFNode(id: 'root', type: 'Stack'),
      navigationFrom: 'notes-page',
    );
    final connect = session.connectNavigation(from: 'about-page', to: 'p4');
    expect(connect.ok, isTrue);
    final dangling = session.connectNavigation(from: 'about-page', to: 'ghost-page');
    expect(dangling.diagnostics.any((d) => d.code == 'mf.ref.dangling'), isTrue);
    expect(session.revisions, isNotEmpty);
  });

  test('create_page_from_template：参数实例化为独立页面，模板不被追溯改写（§2.7）', () {
    const template = MFPageTemplate(
      id: 'tpl-detail',
      routePrefix: '/detail/',
      tree: MFNode(
        id: 'root-{{entityId}}',
        type: 'Stack',
        children: [
          MFNode(id: 'title', type: 'Text', props: {'text': '{{entityName}}'}),
        ],
      ),
      stateMembers: ['dirty'],
      parameters: {'entityId': '实体标识', 'entityName': '实体名称'},
    );
    final project = MFProject(
      manifest: demoProject().manifest,
      pages: demoProject().pages,
      i18n: demoProject().i18n,
      pageTemplates: const {'tpl-detail': template},
    );
    final session = MFAuthoringSession(project: project, registry: demoRegistry());
    // 缺参 / 未声明参数是静态错误（§2.7 封闭集合）。
    final missing = session.createPageFromTemplate(templateId: 'tpl-detail', pageId: 'd1', params: {'entityId': 'a'});
    expect(missing.diagnostics.any((d) => d.code == 'mf.schema.template-param-invalid'), isTrue);
    final extra = session.createPageFromTemplate(
        templateId: 'tpl-detail', pageId: 'd1', params: {'entityId': 'a', 'entityName': 'x', 'hax': 'y'});
    expect(extra.diagnostics.any((d) => d.code == 'mf.schema.unknown-field'), isTrue);
    // 正确实例化：参数替换、独立定义、路由来自模板前缀。
    final ok = session.createPageFromTemplate(
        templateId: 'tpl-detail', pageId: 'detail-a',
        params: {'entityId': 'a', 'entityName': 'Alpha'}, navigationFrom: 'notes-page');
    expect(ok.ok, isTrue);
    final page = session.project.page('detail-a')!;
    expect(page.route, '/detail/detail-a');    expect(page.stateMembers, ['dirty']);
    expect(page.tree.id, 'root-a', reason: '节点 id 中 {{param}} 被替换');
    expect((page.tree.children.single.props['text'] as String), 'Alpha');
    // 模板本身不被追溯改写：骨架仍保留占位符，实例是独立对象（§2.6）。
    expect(template.tree.id, 'root-{{entityId}}');
    expect(identical(page.tree, template.tree), isFalse);
  });

  test('validate_project 与 inspect_impact：结构化查询与影响分析（§14、§18.3）', () {
    final session = MFAuthoringSession(project: demoProject(), registry: demoRegistry());
    expect(session.validateProject().ok, isTrue);
    final impact = session.inspectImpact('Stack');
    expect(impact.usedBy, contains('notes-page'), reason: '反向索引命中引用页面（§4.3）');
    expect(session.inspectImpact('notes-page').referencesOf, isNotEmpty);
  });

  test('undo 可回滚最近一次修订，审计记录保留（§14）', () {
    final session = MFAuthoringSession(project: demoProject(), registry: demoRegistry());
    final before = session.project;
    expect(
      session
          .createPage(
            pageId: 'p2',
            route: '/p2',
            tree: const MFNode(id: 'r', type: 'Stack'),
            navigationFrom: 'notes-page',
          )
          .ok,
      isTrue,
    );
    expect(session.canUndo, isTrue);
    final afterUndo = session.undo();
    expect(identical(afterUndo, before), isTrue, reason: '回滚恢复修订前模型');
    expect(session.project.page('p2'), isNull);
    expect(session.revisions, hasLength(1), reason: '审计记录不删除（§32）');
    expect(session.canUndo, isFalse);
    // 回滚后可重新创建同名页面。
    expect(
      session
          .createPage(
            pageId: 'p2',
            route: '/p2',
            tree: const MFNode(id: 'r', type: 'Stack'),
            navigationFrom: 'notes-page',
          )
          .ok,
      isTrue,
    );
  });

  test('§18.3：命令执行后对象 ID 不丢失，未修改页面无差异', () {
    final session = MFAuthoringSession(project: demoProject(), registry: demoRegistry());
    final originalNotes = session.project.page('notes-page');
    session.createPage(
      pageId: 'p3',
      route: '/p3',
      tree: const MFNode(id: 'r', type: 'Stack'),
      navigationFrom: 'notes-page',
    );
    final currentNotes = session.project.page('notes-page');
    expect(identical(originalNotes, currentNotes), isTrue,
        reason: '未修改页面复用同一不可变对象（无无关差异）');
    expect(currentNotes!.tree.find('title'), isNotNull, reason: '对象 ID 不丢失');
  });

  test('Tier A 元组件集完整性（§38.1）', () {
    final contracts = {
      for (final e in demoRegistry().all()) e.id: e.contract,
    };
    expect(tierAContractDiagnostics(contracts), isEmpty);
  });

  test('基线清单机器可读，测试基线引用合法（P1 守卫）', () {
    final file = _locateRepoFile('MicroFlow4Flutter/baselines.json');
    expect(file, isNotNull, reason: 'MicroFlow4Flutter/baselines.json 必须存在于仓库（§44.3 机器可读投影）');
    final doc = jsonDecode(file!.readAsStringSync()) as Map<String, Object?>;
    final baselines = (doc['baselines'] as List).cast<Map<String, Object?>>();
    expect(baselines, hasLength(32));
    for (var i = 0; i < baselines.length; i++) {
      expect(baselines[i]['id'], i + 1, reason: '基线 id 必须 1..32 连续');
      expect((baselines[i]['title'] as String).isNotEmpty, isTrue);
      expect((baselines[i]['refs'] as String).isNotEmpty, isTrue);
    }
    // 测试名称中「基线 N」引用的条目必须存在于清单（防漂移）。
    final marker = RegExp(r'基线\s*(\d+(?:\s*[、,，]\s*\d+)*)');
    final testName = RegExp(r'''(?:test|testWidgets)\(\s*(['"])(.+?)\1''');
    final ids = {for (final b in baselines) b['id'] as int};
    final files = _dartFiles(const ['test', 'packages'], suffix: '_test.dart');
    expect(files, isNotEmpty);
    final refs = <int>{};
    for (final f in files) {
      for (final m in testName.allMatches(f.readAsStringSync())) {
        for (final bm in marker.allMatches(m.group(2)!)) {
          for (final s in bm.group(1)!.split(RegExp(r'[、,，]'))) {
            final id = int.parse(s.trim());
            expect(ids.contains(id), isTrue, reason: '${f.path} 引用了不存在的基线 $id');
            refs.add(id);
          }
        }
      }
    }
    expect(refs, isNotEmpty);
  });

  test('诊断码单一来源：lib 内全部 mf.* 字面量已登记（§41.3，P5 守卫）', () {
    final literal = RegExp(r"'mf\.[a-z][a-z0-9-]*\.[a-z0-9-]+'");
    final files = _dartFiles(const ['lib', 'packages'], underLib: true);
    expect(files, isNotEmpty);
    final registered = mfDiagnosticRegistry.keys.toSet();
    final violations = <String>[];
    for (final f in files) {
      for (final m in literal.allMatches(f.readAsStringSync())) {
        final code = m.group(0)!.substring(1, m.group(0)!.length - 1);
        if (!registered.contains(code)) violations.add('${f.path}: $code');
      }
    }
    expect(violations, isEmpty, reason: '发射未登记诊断码是实现缺陷（§41.3）');
  });
}
