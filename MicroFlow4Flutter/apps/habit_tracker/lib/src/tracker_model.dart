/// 打卡平台的项目模型与资源注册（全部经 MicroFlow 契约面声明）：
/// 页面/绑定/导航在模型里；习惯业务是宿主注册的真实适配器实现（§23）。
library;

import 'dart:async';

import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'habit_store.dart';

/// 声明使用的元组件注册（渲染实现由解释器内建表承担；注册承担
/// 静态校验与依赖发现，§23.6）。未注册的 Tier A 由 validator 按 warning 上报。
void registerTrackerPrimitives(MFRegistry registry) {
  void reg(String id, ComponentContract contract) {
    registry.register('primitive', id, contract, MFHostComponentImpl((children, props) => Object()));
  }

  reg('Stack', const ComponentContract(layout: LayoutCapability(display: ['block'], sizing: ['hug', 'fill', 'fixed'])));
  reg('Text', const ComponentContract(props: {'text': TString()}, layout: LayoutCapability()));
  reg(
    'Button',
    const ComponentContract(
      props: {'label': TString()},
      events: {'press': TString()},
      layout: LayoutCapability(),
    ),
  );
  reg(
    'Input',
    const ComponentContract(
      props: {'placeholder': TString(), 'value': TString()},
      events: {'change': TString()},
      layout: LayoutCapability(),
    ),
  );
  reg(
    'Select',
    const ComponentContract(
      props: {'label': TString(), 'options': TList(), 'value': TString()},
      events: {'change': TString()},
      layout: LayoutCapability(),
    ),
  );
  reg(
    'List',
    const ComponentContract(
      props: {'items': TList()},
      layout: LayoutCapability(display: ['block'], sizing: ['fill']),
    ),
  );
  reg(
    'Icon',
    const ComponentContract(props: {'name': TString(), 'size': TNumber()}, layout: LayoutCapability()),
  );
}

/// 业务适配器（真实实现：HabitStore 本地持久化 + 连击计算）。
/// `runtimeReady` 由装配方在 runtime 建成后 complete——打卡适配器经
/// Business Fact 通道提交事实（§24.7 唯一显式例外）。
void registerTrackerAdapters(MFRegistry registry, HabitStore habits, Completer<MFRuntime> runtimeReady) {
  registry.register(
    'function',
    'function.habits-query',
    const ComponentContract(),
    MFFunctionImpl((args) async => habits.snapshot()),
    description: '习惯列表与今日进度（本地持久化）',
  );
  registry.register(
    'function',
    'function.habit-create',
    const ComponentContract(
      telemetry: MFTelemetryAnnotation(
        events: {'success': 'ops.habit.created'},
        privacyClass: 'operational',
        args: ['name', 'icon'],
      ),
    ),
    MFFunctionImpl((args) async => habits.createHabit(args['name'] as String, (args['icon'] as String?) ?? 'star')),
    description: '新建习惯（幂等无：创建动作可重复产生不同 id）',
  );
  registry.register(
    'function',
    'function.check-in-write',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['record_id'])},
    ),
    MFFunctionImpl((args) async {
      final r = habits.checkIn(args['id'] as String);
      // record_id 即打卡记录的运行引用（§24.8）：确认必须可关联。
      return {...r, 'external_run_ref': r['record_id']};
    }),
    description: '打卡写入（幂等键=习惯@日期）；record_id 即外部运行引用',
  );
  registry.register(
    'function',
    'function.stats-all',
    const ComponentContract(),
    MFFunctionImpl((args) async => habits.statsAll()),
    description: '习惯统计与最近打卡记录',
  );
  // 打卡事实提交（经 Business Fact 通道）：
  //  - 幂等键 = 习惯@日期：同日重复提交幂等返回既有确认记录（基线 28 语义）；
  //  - 写入实现返回 record_id 作为外部运行引用（§24.8），确认必须可关联；
  //  - 超时进入 unknown（可查询、不自动重试）。
  registry.register(
    'adapter',
    'adapter.check-in',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['state', 'message'])},
      telemetry: MFTelemetryAnnotation(
        events: {
          'success': 'ops.habit.checked-in',
          'failure': 'diag.habit.check-in-failed',
        },
        privacyClass: 'operational',
        args: ['id', 'name'],
      ),
    ),
    MFFunctionImpl((args) async {
      final runtime = await runtimeReady.future;
      final record = await runtime.facts.submit(
        factRef: 'habit-check-in',
        idempotencyKey: '${args['id']}@${HabitStore.dayKey(DateTime.now())}',
        call: 'function.check-in-write',
        args: args,
        timeoutMs: 3000,
      );
      return <String, Object?>{
        'state': record.state,
        'message': switch (record.state) {
          'confirmed' when record.reason == null => '打卡成功',
          'confirmed' => '打卡成功（重复提交已按去重身份幂等确认）',
          _ => '结果未知：本次打卡稍后可在统计页确认（unknown 不自动重试）',
        },
      };
    }, timeoutMs: 5000),
    description: '打卡事实提交（幂等键=习惯@日期，确认关联运行引用）',
  );
}

/// 项目模型：习惯列表页 + 统计页；声明式列表绑定渲染习惯行，
/// 项内按钮事件携带项上下文（item.id）执行打卡绑定。
MFProject buildTrackerProject() {
  return MFProject(
    manifest: const MFManifest(
      projectId: 'habit-tracker',
      syntaxVersion: '1.0',
      targets: ['web'],
      entryPage: 'habits-page',
      defaultTheme: 'theme-light',
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN'],
    ),
    pages: [
      MFPage(
        id: 'habits-page',
        route: '/habits',
        stateMembers: const ['habits', 'todayLabel', 'newName', 'newIcon', 'checkMsg'],
        onEnter: 'habits-init',
        tree: MFNode(
          id: 'root',
          type: 'Stack',
          props: const {'expand': true},
          children: [
            MFNode(
              id: 'brand',
              type: 'Stack',
              props: const {'direction': 'horizontal'},
              children: [
                MFNode(id: 'brand-micro', type: 'Text', props: {'text': 'Micro'}),
                MFNode(id: 'brand-flow', type: 'Text', props: {'text': 'Flow'}, style: 'style-brand'),
              ],
            ),
            MFNode(id: 'title', type: 'Text', t: 'habits.title', style: 'style-title'),
            MFNode(id: 'today', type: 'Text', props: {'text': MFRef('state.todayLabel')}),
            MFNode(
              id: 'habit-list',
              type: 'List',
              props: {'items': MFRef('state.habits')},
              children: [
                MFNode(
                  id: 'row',
                  type: 'Stack',
                  props: {'direction': 'horizontal', 'align': 'space-between'},
                  children: [
                    MFNode(
                      id: 'row-left',
                      type: 'Stack',
                      props: {'direction': 'horizontal'},
                      children: [
                        MFNode(id: 'row-icon', type: 'Icon', props: {'name': MFRef('item.icon'), 'size': 20}),
                        MFNode(id: 'row-name', type: 'Text', props: {'text': MFRef('item.name')}),
                        MFNode(id: 'row-streak', type: 'Text', props: {'text': MFRef('item.streakLabel')}),
                      ],
                    ),
                    MFNode(id: 'check-btn', type: 'Button', props: {'label': MFRef('item.actionLabel')}),
                  ],
                ),
              ],
            ),
            MFNode(id: 'check-msg', type: 'Text', props: {'text': MFRef('state.checkMsg')}),
            MFNode(
              id: 'create-row',
              type: 'Stack',
              props: {'direction': 'horizontal'},
              children: [
                MFNode(
                  id: 'name-input',
                  type: 'Input',
                  props: {'placeholder': '新习惯名称', 'value': MFRef('state.newName')},
                  constraints: const MFSelfConstraint(width: 'fill'),
                ),
                MFNode(
                  id: 'icon-select',
                  type: 'Select',
                  props: {
                    'label': '图标',
                    'value': MFRef('state.newIcon'),
                    'options': [
                      {'value': 'star', 'label': '⭐ 通用'},
                      {'value': 'run', 'label': '🏃 运动'},
                      {'value': 'book', 'label': '📖 阅读'},
                      {'value': 'water', 'label': '💧 喝水'},
                    ],
                  },
                  constraints: const MFSelfConstraint(width: 'fill'),
                ),
                MFNode(id: 'add-btn', type: 'Button', props: {'label': '添加习惯'}),
              ],
            ),
            MFNode(id: 'view-stats', type: 'Button', props: {'label': '查看统计'}),
          ],
        ),
      ),
      MFPage(
        id: 'stats-page',
        route: '/stats',
        stateMembers: const ['stats', 'recent'],
        onEnter: 'stats-init',
        tree: MFNode(
          id: 'root',
          type: 'Stack',
          props: const {'expand': true},
          children: [
            MFNode(
              id: 'brand',
              type: 'Stack',
              props: const {'direction': 'horizontal'},
              children: [
                MFNode(id: 'brand-micro', type: 'Text', props: {'text': 'Micro'}),
                MFNode(id: 'brand-flow', type: 'Text', props: {'text': 'Flow'}, style: 'style-brand'),
              ],
            ),
            MFNode(id: 'title', type: 'Text', t: 'stats.title', style: 'style-title'),
            MFNode(
              id: 'stat-list',
              type: 'List',
              props: {'items': MFRef('state.stats')},
              children: [
                MFNode(
                  id: 'stat-row',
                  type: 'Stack',
                  props: {'direction': 'horizontal'},
                  children: [
                    MFNode(id: 'stat-icon', type: 'Icon', props: {'name': MFRef('item.icon'), 'size': 20}),
                    MFNode(id: 'stat-name', type: 'Text', props: {'text': MFRef('item.name')}),
                    MFNode(id: 'stat-streak', type: 'Text', props: {'text': MFRef('item.streakLabel')}),
                    MFNode(id: 'stat-total', type: 'Text', props: {'text': MFRef('item.totalLabel')}),
                  ],
                ),
              ],
            ),
            MFNode(id: 'recent-title', type: 'Text', t: 'stats.recent'),
            MFNode(
              id: 'recent-list',
              type: 'List',
              props: {'items': MFRef('state.recent')},
              children: [
                MFNode(
                  id: 'recent-row',
                  type: 'Stack',
                  props: {'direction': 'horizontal'},
                  children: [
                    MFNode(id: 'recent-habit', type: 'Text', props: {'text': MFRef('item.habit')}),
                    MFNode(id: 'recent-time', type: 'Text', props: {'text': MFRef('item.timeLabel')}),
                  ],
                ),
              ],
            ),
            MFNode(id: 'back-btn', type: 'Button', props: {'label': '返回打卡'}),
          ],
        ),
      ),
    ],
    navigation: const MFNavigationSpec(edges: [
      MFNavEdge(from: 'habits-page', to: 'stats-page'),
      MFNavEdge(from: 'stats-page', to: 'habits-page'),
    ]),
    bindingMaps: {
      'tracker-map': MFBindingMap(
        id: 'tracker-map',
        bindings: [
          MFBinding(
            id: 'habits-init',
            on: 'habits-page.onEnter',
            actions: [
              MFAdapterAction(kind: 'function', call: 'function.habits-query', as: 'd'),
              MFStateAction(target: 'habits', value: MFRef('prev.d.habits')),
              MFStateAction(target: 'todayLabel', value: MFRef('prev.d.label')),
            ],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'name-change',
            on: 'name-input.change',
            actions: [MFStateAction(target: 'newName', value: MFRef('prop.value'))],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'icon-change',
            on: 'icon-select.change',
            actions: [MFStateAction(target: 'newIcon', value: MFRef('prop.value'))],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'habit-create',
            on: 'add-btn.press',
            guard: MFExpr.parse({'neq': [{'ref': 'state.newName'}, '']}),
            actions: [
              MFAdapterAction(
                kind: 'function',
                call: 'function.habit-create',
                arguments: {'name': MFRef('state.newName'), 'icon': MFRef('state.newIcon')},
              ),
              MFAdapterAction(kind: 'function', call: 'function.habits-query', as: 'd'),
              MFStateAction(target: 'habits', value: MFRef('prev.d.habits')),
              MFStateAction(target: 'todayLabel', value: MFRef('prev.d.label')),
              MFStateAction(target: 'newName', value: MFLiteral('')),
              MFNavigationAction(target: 'habits-page'),
            ],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'habit-check-in',
            on: 'check-btn.press',
            actions: [
              MFAdapterAction(
                kind: 'adapter',
                call: 'adapter.check-in',
                arguments: {'id': MFRef('item.id'), 'name': MFRef('item.name')},
                as: 'c',
              ),
              MFAdapterAction(kind: 'function', call: 'function.habits-query', as: 'd'),
              MFStateAction(target: 'habits', value: MFRef('prev.d.habits')),
              MFStateAction(target: 'todayLabel', value: MFRef('prev.d.label')),
              MFStateAction(target: 'checkMsg', value: MFRef('prev.c.message')),
            ],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'view-stats',
            on: 'view-stats.press',
            actions: [MFNavigationAction(target: 'stats-page')],
            policy: MFPolicy.cancelPrevious,
          ),
          MFBinding(
            id: 'stats-init',
            on: 'stats-page.onEnter',
            actions: [
              MFAdapterAction(kind: 'function', call: 'function.stats-all', as: 's'),
              MFStateAction(target: 'stats', value: MFRef('prev.s.stats')),
              MFStateAction(target: 'recent', value: MFRef('prev.s.recent')),
            ],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'back-to-habits',
            on: 'back-btn.press',
            actions: [MFNavigationAction(target: 'habits-page')],
            policy: MFPolicy.cancelPrevious,
          ),
        ],
      ),
    },
    i18n: const MFI18nCatalog(
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN'],
      messages: {
        'habits.title': {'zh-CN': '习惯打卡'},
        'stats.title': {'zh-CN': '习惯统计'},
        'stats.recent': {'zh-CN': '最近打卡'},
      },
    ),
    tokens: const {
      'theme-light': MFTokenSet(
        id: 'theme-light',
        tokens: {'color.action': '#2563eb', 'color.foreground': '#111827', 'color.brand': '#0070F3'},
      ),
    },
    styleSheets: const {
      'style-title': MFStyleSheet(id: 'style-title', base: {'foreground': 'color.foreground'}),
      'style-brand': MFStyleSheet(id: 'style-brand', base: {'foreground': 'color.brand'}),
    },
    recoveryContracts: const {
      'recovery-default': MFRecoveryContract(id: 'recovery-default', maxAgeSeconds: 604800),
    },
  );
}
