/// 管理平台的项目模型与资源注册（§30.2 查询/导出契约的消费方）：
/// 概览指标、事件明细、追踪查询、数据质量四个运营面，全部经
/// 项目模型 + 绑定映射驱动，适配器是 §30.2 本地查询引擎的真实封装。
library;

import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'admin_data.dart';

void registerAdminPrimitives(MFRegistry registry) {
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
    'List',
    const ComponentContract(
      props: {'items': TList()},
      layout: LayoutCapability(display: ['block'], sizing: ['fill']),
    ),
  );
}

void registerAdminAdapters(MFRegistry registry, AdminData data) {
  registry.register(
    'function',
    'function.admin-overview',
    const ComponentContract(),
    MFFunctionImpl((args) async {
      final events = data.loadTrackerEvents();
      final engine = data.engine(events);
      final now = DateTime.now().toUtc();
      final grouped = engine.queryEvents(
        from: now.subtract(const Duration(days: 30)),
        to: now.add(const Duration(minutes: 1)),
        groupBy: const ['event_name'],
        pageSize: 20,
      );
      final checks = events.where((e) => e.eventName == 'ops.habit.checked-in').length;
      final creates = events.where((e) => e.eventName == 'ops.habit.created').length;
      final sessions = events.map((e) => e.sessionId).toSet().length;
      final dq = engine.getDataQuality();
      final latest = events.length > 8 ? events.sublist(events.length - 8).reversed.toList() : events.reversed.toList();
      return <String, Object?>{
        'totalLabel': '事件总数 ${events.length}',
        'checksLabel': '打卡事件 $checks',
        'createsLabel': '创建习惯 $creates',
        'sessionsLabel': '活跃会话 $sessions',
        'lossLabel': '丢失率 ${((dq['loss_rate'] as num) * 100).toStringAsFixed(1)}%'
            '（丢弃 ${(dq['dropped'] as num).toInt()} 条，口径与交付同源）',
        'hint': events.isEmpty ? '暂无事件：先在打卡平台产生数据（同源部署共享存储）' : '',
        'preview': [
          for (final e in latest)
            {'time': AdminData.fmtTime(e.occurredAt), 'name': e.eventName, 'route': e.route},
        ],
        'byEvent': [
          for (final g in (grouped['groups'] as List).cast<Map>())
            {'event': (g['key'] as String?) ?? '_', 'count': '${g['count']} 条'},
        ],
      };
    }),
    description: '运营概览（事件/会话/丢失率口径）',
  );
  registry.register(
    'function',
    'function.admin-events',
    const ComponentContract(),
    MFFunctionImpl((args) async {
      final events = data.loadTrackerEvents();
      final engine = data.engine(events);
      final now = DateTime.now().toUtc();
      final res = engine.queryEvents(
        from: now.subtract(const Duration(days: 30)),
        to: now.add(const Duration(minutes: 1)),
        pageSize: 50,
      );
      return <String, Object?>{
        'events': [
          for (final e in (res['events'] as List).cast<Map>())
            {'time': AdminData.fmtTime(e['occurred_at']), 'name': e['event_name'], 'route': e['route'] ?? ''},
        ],
        'hint': '事件明细（近 30 天，共 ${(res['total'] as num).toInt()} 条）',
      };
    }),
    description: '事件明细查询（query_events，时间范围 + 分页上限）',
  );
  registry.register(
    'function',
    'function.admin-trace',
    const ComponentContract(),
    MFFunctionImpl((args) async {
      final traceId = (args['trace'] as String?)?.trim() ?? '';
      if (traceId.isEmpty) {
        return <String, Object?>{'events': const [], 'message': ''};
      }
      final events = data.loadTrackerEvents();
      final res = data.engine(events).getTrace(traceId);
      final rows = (res['events'] as List).cast<Map>();
      return <String, Object?>{
        'events': [
          for (final e in rows)
            {'time': AdminData.fmtTime(e['occurred_at']), 'name': e['event_name'], 'route': e['route'] ?? ''},
        ],
        'message': rows.isEmpty ? '未找到该追踪下的事件（get_trace: $traceId）' : '追踪 $traceId 共 ${rows.length} 条',
      };
    }),
    description: '追踪查询（get_trace）',
  );
  registry.register(
    'function',
    'function.admin-quality',
    const ComponentContract(),
    MFFunctionImpl((args) async {
      final events = data.loadTrackerEvents();
      final dq = data.engine(events).getDataQuality();
      return <String, Object?>{
        'qualityRows': [
          {'k': '已交付事件', 'v': '${events.length}'},
          {'k': '丢弃事件', 'v': '${(dq['dropped'] as num).toInt()}'},
          {'k': '丢失率', 'v': '${((dq['loss_rate'] as num) * 100).toStringAsFixed(1)}%'},
        ],
      };
    }),
    description: '数据质量（get_data_quality 口径）',
  );
}

MFProject buildAdminProject() {
  return MFProject(
    manifest: const MFManifest(
      projectId: 'habit-admin',
      syntaxVersion: '1.0',
      targets: ['web'],
      entryPage: 'overview-page',
      defaultTheme: 'theme-light',
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN'],
    ),
    pages: [
      MFPage(
        id: 'overview-page',
        route: '/admin/overview',
        stateMembers: const [
          'totalLabel', 'checksLabel', 'createsLabel', 'sessionsLabel',
          'lossLabel', 'hint', 'preview', 'byEvent',
        ],
        onEnter: 'admin-init',
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
            MFNode(id: 'title', type: 'Text', props: {'text': '习惯打卡 · 运营管理'}, style: 'style-title'),
            MFNode(id: 'total', type: 'Text', props: {'text': MFRef('state.totalLabel')}),
            MFNode(
              id: 'metrics',
              type: 'Stack',
              props: {'direction': 'horizontal'},
              children: [
                MFNode(id: 'checks', type: 'Text', props: {'text': MFRef('state.checksLabel')}),
                MFNode(id: 'creates', type: 'Text', props: {'text': MFRef('state.createsLabel')}),
                MFNode(id: 'sessions', type: 'Text', props: {'text': MFRef('state.sessionsLabel')}),
              ],
            ),
            MFNode(id: 'loss', type: 'Text', props: {'text': MFRef('state.lossLabel')}),
            MFNode(id: 'hint', type: 'Text', props: {'text': MFRef('state.hint')}),
            MFNode(
              id: 'event-groups',
              type: 'List',
              props: {'items': MFRef('state.byEvent')},
              children: [
                MFNode(
                  id: 'group-row',
                  type: 'Stack',
                  props: {'direction': 'horizontal'},
                  children: [
                    MFNode(id: 'group-name', type: 'Text', props: {'text': MFRef('item.event')}),
                    MFNode(id: 'group-count', type: 'Text', props: {'text': MFRef('item.count')}),
                  ],
                ),
              ],
            ),
            MFNode(
              id: 'preview-list',
              type: 'List',
              props: {'items': MFRef('state.preview')},
              children: [
                MFNode(
                  id: 'preview-row',
                  type: 'Stack',
                  props: {'direction': 'horizontal'},
                  children: [
                    MFNode(id: 'preview-time', type: 'Text', props: {'text': MFRef('item.time')}),
                    MFNode(id: 'preview-name', type: 'Text', props: {'text': MFRef('item.name')}),
                    MFNode(id: 'preview-route', type: 'Text', props: {'text': MFRef('item.route')}),
                  ],
                ),
              ],
            ),
            MFNode(id: 'view-events', type: 'Button', props: {'label': '事件明细与追踪查询'}),
            MFNode(id: 'view-quality', type: 'Button', props: {'label': '数据质量'}),
          ],
        ),
      ),
      MFPage(
        id: 'events-page',
        route: '/admin/events',
        stateMembers: const ['eventRows', 'eventsHint', 'traceRows', 'traceMsg', 'traceId'],
        onEnter: 'events-init',
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
            MFNode(id: 'title', type: 'Text', props: {'text': '事件明细与追踪'}, style: 'style-title'),
            MFNode(id: 'events-hint', type: 'Text', props: {'text': MFRef('state.eventsHint')}),
            MFNode(
              id: 'trace-row',
              type: 'Stack',
              props: {'direction': 'horizontal'},
              children: [
                MFNode(
                  id: 'trace-input',
                  type: 'Input',
                  props: {'placeholder': '输入 trace_id 查询追踪', 'value': MFRef('state.traceId')},
                ),
                MFNode(id: 'trace-btn', type: 'Button', props: {'label': '查询追踪'}),
              ],
            ),
            MFNode(id: 'trace-msg', type: 'Text', props: {'text': MFRef('state.traceMsg')}),
            MFNode(
              id: 'trace-list',
              type: 'List',
              props: {'items': MFRef('state.traceRows')},
              children: [
                MFNode(
                  id: 'trace-row',
                  type: 'Stack',
                  props: {'direction': 'horizontal'},
                  children: [
                    MFNode(id: 'trace-time', type: 'Text', props: {'text': MFRef('item.time')}),
                    MFNode(id: 'trace-name', type: 'Text', props: {'text': MFRef('item.name')}),
                    MFNode(id: 'trace-route', type: 'Text', props: {'text': MFRef('item.route')}),
                  ],
                ),
              ],
            ),
            MFNode(id: 'refresh-events', type: 'Button', props: {'label': '刷新事件明细'}),
            MFNode(
              id: 'event-list',
              type: 'List',
              props: {'items': MFRef('state.eventRows')},
              children: [
                MFNode(
                  id: 'event-row',
                  type: 'Stack',
                  props: {'direction': 'horizontal'},
                  children: [
                    MFNode(id: 'event-time', type: 'Text', props: {'text': MFRef('item.time')}),
                    MFNode(id: 'event-name', type: 'Text', props: {'text': MFRef('item.name')}),
                    MFNode(id: 'event-route', type: 'Text', props: {'text': MFRef('item.route')}),
                  ],
                ),
              ],
            ),
            MFNode(id: 'back-btn', type: 'Button', props: {'label': '返回概览'}),
          ],
        ),
      ),
      MFPage(
        id: 'quality-page',
        route: '/admin/quality',
        stateMembers: const ['qualityRows'],
        onEnter: 'quality-init',
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
            MFNode(id: 'title', type: 'Text', props: {'text': '数据质量'}, style: 'style-title'),
            MFNode(
              id: 'quality-list',
              type: 'List',
              props: {'items': MFRef('state.qualityRows')},
              children: [
                MFNode(
                  id: 'quality-row',
                  type: 'Stack',
                  props: {'direction': 'horizontal'},
                  children: [
                    MFNode(id: 'quality-k', type: 'Text', props: {'text': MFRef('item.k')}),
                    MFNode(id: 'quality-v', type: 'Text', props: {'text': MFRef('item.v')}),
                  ],
                ),
              ],
            ),
            MFNode(id: 'back-btn', type: 'Button', props: {'label': '返回概览'}),
          ],
        ),
      ),
    ],
    navigation: const MFNavigationSpec(edges: [
      MFNavEdge(from: 'overview-page', to: 'events-page'),
      MFNavEdge(from: 'overview-page', to: 'quality-page'),
      MFNavEdge(from: 'events-page', to: 'overview-page'),
      MFNavEdge(from: 'quality-page', to: 'overview-page'),
    ]),
    bindingMaps: {
      'admin-map': MFBindingMap(
        id: 'admin-map',
        bindings: [
          MFBinding(
            id: 'admin-init',
            on: 'overview-page.onEnter',
            actions: [
              MFAdapterAction(kind: 'function', call: 'function.admin-overview', as: 'o'),
              MFStateAction(target: 'totalLabel', value: MFRef('prev.o.totalLabel')),
              MFStateAction(target: 'checksLabel', value: MFRef('prev.o.checksLabel')),
              MFStateAction(target: 'createsLabel', value: MFRef('prev.o.createsLabel')),
              MFStateAction(target: 'sessionsLabel', value: MFRef('prev.o.sessionsLabel')),
              MFStateAction(target: 'lossLabel', value: MFRef('prev.o.lossLabel')),
              MFStateAction(target: 'hint', value: MFRef('prev.o.hint')),
              MFStateAction(target: 'preview', value: MFRef('prev.o.preview')),
              MFStateAction(target: 'byEvent', value: MFRef('prev.o.byEvent')),
            ],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'view-events',
            on: 'view-events.press',
            actions: [MFNavigationAction(target: 'events-page')],
            policy: MFPolicy.cancelPrevious,
          ),
          MFBinding(
            id: 'view-quality',
            on: 'view-quality.press',
            actions: [MFNavigationAction(target: 'quality-page')],
            policy: MFPolicy.cancelPrevious,
          ),
          MFBinding(
            id: 'events-init',
            on: 'events-page.onEnter',
            actions: [
              MFAdapterAction(kind: 'function', call: 'function.admin-events', as: 'e'),
              MFStateAction(target: 'eventRows', value: MFRef('prev.e.events')),
              MFStateAction(target: 'eventsHint', value: MFRef('prev.e.hint')),
            ],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'trace-change',
            on: 'trace-input.change',
            actions: [MFStateAction(target: 'traceId', value: MFRef('prop.value'))],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'trace-run',
            on: 'trace-btn.press',
            guard: MFExpr.parse({'neq': [{'ref': 'state.traceId'}, '']}),
            actions: [
              MFAdapterAction(
                kind: 'function',
                call: 'function.admin-trace',
                arguments: {'trace': MFRef('state.traceId')},
                as: 't',
              ),
              MFStateAction(target: 'traceRows', value: MFRef('prev.t.events')),
              MFStateAction(target: 'traceMsg', value: MFRef('prev.t.message')),
            ],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'refresh-events',
            on: 'refresh-events.press',
            actions: [
              MFAdapterAction(kind: 'function', call: 'function.admin-events', as: 'e'),
              MFStateAction(target: 'eventRows', value: MFRef('prev.e.events')),
              MFStateAction(target: 'eventsHint', value: MFRef('prev.e.hint')),
            ],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'quality-init',
            on: 'quality-page.onEnter',
            actions: [
              MFAdapterAction(kind: 'function', call: 'function.admin-quality', as: 'q'),
              MFStateAction(target: 'qualityRows', value: MFRef('prev.q.qualityRows')),
            ],
            policy: MFPolicy.rejectNew,
          ),
          MFBinding(
            id: 'back-to-overview',
            on: 'back-btn.press',
            actions: [MFNavigationAction(target: 'overview-page')],
            policy: MFPolicy.cancelPrevious,
          ),
        ],
      ),
    },
    tokens: const {
      'theme-light': MFTokenSet(
        id: 'theme-light',
        tokens: {'color.action': '#0f766e', 'color.foreground': '#111827', 'color.brand': '#0070F3'},
      ),
    },
    styleSheets: const {
      'style-title': MFStyleSheet(id: 'style-title', base: {'foreground': 'color.foreground'}),
      'style-brand': MFStyleSheet(id: 'style-brand', base: {'foreground': 'color.brand'}),
    },
  );
}
