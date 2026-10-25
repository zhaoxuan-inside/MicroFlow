/// 运营管理平台的 MicroFlow 项目模型（§4）：六个运营页面的声明式页面树、
/// 绑定图、i18n、Token 与双层主题。所有数据经注册函数读取同源共享遥测
/// 日志，页面与交互不携带可执行逻辑（§2.9）。
///
/// 结构约定与 habit_tracker 一致：页面根节点与页面同 id（`onEnter` 生命周期
/// 锚点，见 registry.dart 说明）；顶层节点按 `layer` 归入 site-header /
/// site-content 显式分区（§7.1）。导航节点 id 形如 `nav-<源页>-<目标页>`，
/// 全项目唯一（绑定锚点按全局节点 id 解析）。
library;

import 'package:microflow4_flutter/microflow4_flutter.dart';

MFProject buildOpsProject() {
  return MFProject(
    manifest: const MFManifest(
      projectId: 'ops-admin',
      syntaxVersion: '1.0',
      targets: ['web'],
      entryPage: 'overview-page',
      defaultTheme: 'theme-light',
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN'],
    ),
    pages: [
      _overviewPage(),
      _pagesPage(),
      _featuresPage(),
      _logsPage(),
      _exportPage(),
      _collectionPage(),
    ],
    bindingMaps: {'ops-map': _opsBindings()},
    i18n: const MFI18nCatalog(
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN'],
      messages: {
        'app.overview.title': {'zh-CN': '运营概览'},
        'app.pages.title': {'zh-CN': '页面分析'},
        'app.features.title': {'zh-CN': '功能使用'},
        'app.logs.title': {'zh-CN': '日志检索'},
        'app.export.title': {'zh-CN': '导出与保留'},
        'app.collection.title': {'zh-CN': '采集控制'},
        'app.overview.kpi': {'zh-CN': '运营指标'},
        'app.overview.quality': {'zh-CN': '数据质量'},
        'app.overview.habits': {'zh-CN': '习惯打卡统计'},
      },
    ),
    tokens: const {
      'theme-light': MFTokenSet(
        id: 'theme-light',
        tokens: {
          'color.action': '#7c3aed',
          'color.bg.surface': '#ffffff',
          'color.bg.inverse': '#111827',
          'color.text.primary': '#111827',
          'color.text.inverse': '#f9fafb',
          'color.foreground': '#111827',
          'color.background': '#ffffff',
        },
      ),
    },
    themes: const {
      'theme-dark': MFTheme(
        id: 'theme-dark',
        extendsId: 'theme-light',
        overrides: {
          'color.foreground': {'ref': 'color.text.inverse'},
          'color.background': {'ref': 'color.bg.inverse'},
        },
      ),
    },
    styleSheets: const {
      'style-title': MFStyleSheet(
        id: 'style-title',
        base: {'foreground': 'color.text.primary'},
      ),
    },
    navigation: const MFNavigationSpec(edges: [
      MFNavEdge(from: 'overview-page', to: 'pages-page'),
      MFNavEdge(from: 'overview-page', to: 'features-page'),
      MFNavEdge(from: 'overview-page', to: 'logs-page'),
      MFNavEdge(from: 'overview-page', to: 'export-page'),
      MFNavEdge(from: 'overview-page', to: 'collection-page'),
      MFNavEdge(from: 'pages-page', to: 'overview-page'),
      MFNavEdge(from: 'features-page', to: 'overview-page'),
      MFNavEdge(from: 'logs-page', to: 'overview-page'),
      MFNavEdge(from: 'export-page', to: 'overview-page'),
      MFNavEdge(from: 'collection-page', to: 'overview-page'),
    ]),
  );
}

const _layerRegions = [
  MFRegionConstraint(id: 'site-header', region: 'header'),
  MFRegionConstraint(id: 'site-content', region: 'content', scroll: true),
];

/// 页面代码（导航节点 id 的一段）与页面 id 的唯一对应。
const _pageCodes = <String, String>{
  'overview-page': 'ov',
  'pages-page': 'pg',
  'features-page': 'ft',
  'logs-page': 'lg',
  'export-page': 'ex',
  'collection-page': 'cl',
};

const _pageLabels = <String, String>{
  'overview-page': '运营概览',
  'pages-page': '页面分析',
  'features-page': '功能使用',
  'logs-page': '日志检索',
  'export-page': '导出与保留',
  'collection-page': '采集控制',
};

MFNode _navButtons(String pageId) => MFNode(
      id: '$pageId-nav',
      type: 'Stack',
      props: const {'direction': 'horizontal'},
      children: [
        for (final entry in _pageCodes.entries)
          if (entry.key != pageId)
            MFNode(
              id: 'nav-${_pageCodes[pageId]}-${entry.value}',
              type: 'Button',
              props: {'label': _pageLabels[entry.key], 'variant': 'secondary'},
            ),
      ],
    );

MFNode _pageHeader({required String pageId, required String titleMessage}) => MFNode(
      id: '$pageId-header',
      type: 'Stack',
      layer: 'site-header',
      props: const {'direction': 'horizontal', 'align': 'space-between', 'crossAlign': 'center'},
      children: [
        MFNode(
          id: '$pageId-title',
          type: 'Text',
          t: titleMessage,
          style: 'style-title',
          // fill：页头行内唯一扩展子项，使整行占满可用宽度，
          // space-between 把导航按钮推到右侧（§7.2）。
          constraints: const MFSelfConstraint(width: 'fill'),
        ),
        _navButtons(pageId),
      ],
    );

/// 两列数据行：label/value（值列为固定宽，label 占满剩余空间）。
MFNode _row({required String id, required String labelRef, required String valueRef}) => MFNode(
      id: id,
      type: 'Stack',
      props: const {'direction': 'horizontal', 'crossAlign': 'center'},
      children: [
        MFNode(
          id: '$id-label',
          type: 'Text',
          props: {'text': {'ref': labelRef}},
          constraints: const MFSelfConstraint(width: 'fill'),
        ),
        MFNode(
          id: '$id-value',
          type: 'Text',
          props: {'text': {'ref': valueRef}},
        ),
      ],
    );

MFNode _refreshButton(String id) => MFNode(
      id: id,
      type: 'Button',
      props: const {'label': '刷新', 'variant': 'secondary'},
    );

MFPage _overviewPage() => MFPage(
      id: 'overview-page',
      route: '/admin/overview',
      stateMembers: const ['kpiRows', 'qualityRows', 'habitRows', 'updatedText'],
      onEnter: 'overview-enter',
      layerRegions: _layerRegions,
      tree: MFNode(
        id: 'overview-page',
        type: 'Stack',
        children: [
          _pageHeader(pageId: 'overview-page', titleMessage: 'app.overview.title'),
          MFNode(
            id: 'overview-content',
            type: 'Stack',
            layer: 'site-content',
            children: [
              MFNode(id: 'overview-updated', type: 'Text', props: {'text': {'ref': 'state.updatedText'}}),
              _refreshButton('overview-refresh'),
              MFNode(id: 'overview-kpi-title', type: 'Text', t: 'app.overview.kpi'),
              MFNode(
                id: 'overview-kpi-list',
                type: 'List',
                props: {'items': {'ref': 'state.kpiRows'}},
                children: [
                  _row(id: 'overview-kpi-row', labelRef: 'item.label', valueRef: 'item.value'),
                ],
              ),
              MFNode(id: 'overview-quality-title', type: 'Text', t: 'app.overview.quality'),
              MFNode(
                id: 'overview-quality-list',
                type: 'List',
                props: {'items': {'ref': 'state.qualityRows'}},
                children: [
                  _row(id: 'overview-quality-row', labelRef: 'item.label', valueRef: 'item.value'),
                ],
              ),
              MFNode(id: 'overview-habit-title', type: 'Text', t: 'app.overview.habits'),
              MFNode(
                id: 'overview-habit-list',
                type: 'List',
                props: {'items': {'ref': 'state.habitRows'}},
                children: [
                  MFNode(
                    id: 'overview-habit-row',
                    type: 'Stack',
                    props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                    children: [
                      MFNode(
                        id: 'overview-habit-name',
                        type: 'Text',
                        props: {'text': {'ref': 'item.name'}},
                        constraints: const MFSelfConstraint(width: 'fill'),
                      ),
                      MFNode(
                        id: 'overview-habit-count',
                        type: 'Text',
                        props: {'text': {'ref': 'item.checkinsText'}},
                        constraints: const MFSelfConstraint(width: 96),
                      ),
                      MFNode(
                        id: 'overview-habit-last',
                        type: 'Text',
                        props: {'text': {'ref': 'item.lastText'}},
                        constraints: const MFSelfConstraint(width: 132),
                      ),
                    ],
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );

MFPage _pagesPage() => MFPage(
      id: 'pages-page',
      route: '/admin/pages',
      stateMembers: const ['pageRows'],
      onEnter: 'pages-enter',
      layerRegions: _layerRegions,
      tree: MFNode(
        id: 'pages-page',
        type: 'Stack',
        children: [
          _pageHeader(pageId: 'pages-page', titleMessage: 'app.pages.title'),
          MFNode(
            id: 'pages-content',
            type: 'Stack',
            layer: 'site-content',
            children: [
              _refreshButton('pages-refresh'),
              MFNode(
                id: 'pages-list',
                type: 'List',
                props: {'items': {'ref': 'state.pageRows'}},
                children: [
                  MFNode(
                    id: 'pages-row',
                    type: 'Stack',
                    props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                    children: [
                      MFNode(
                        id: 'pages-row-route',
                        type: 'Text',
                        props: {'text': {'ref': 'item.route'}},
                        constraints: const MFSelfConstraint(width: 'fill'),
                      ),
                      MFNode(
                        id: 'pages-row-views',
                        type: 'Text',
                        props: {'text': {'ref': 'item.viewsText'}},
                        constraints: const MFSelfConstraint(width: 64),
                      ),
                      MFNode(
                        id: 'pages-row-exits',
                        type: 'Text',
                        props: {'text': {'ref': 'item.exitsText'}},
                        constraints: const MFSelfConstraint(width: 64),
                      ),
                      MFNode(
                        id: 'pages-row-stay',
                        type: 'Text',
                        props: {'text': {'ref': 'item.avgStayText'}},
                        constraints: const MFSelfConstraint(width: 96),
                      ),
                    ],
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );

MFPage _featuresPage() => MFPage(
      id: 'features-page',
      route: '/admin/features',
      stateMembers: const ['featureRows'],
      onEnter: 'features-enter',
      layerRegions: _layerRegions,
      tree: MFNode(
        id: 'features-page',
        type: 'Stack',
        children: [
          _pageHeader(pageId: 'features-page', titleMessage: 'app.features.title'),
          MFNode(
            id: 'features-content',
            type: 'Stack',
            layer: 'site-content',
            children: [
              _refreshButton('features-refresh'),
              MFNode(
                id: 'features-list',
                type: 'List',
                props: {'items': {'ref': 'state.featureRows'}},
                children: [
                  MFNode(
                    id: 'features-row',
                    type: 'Stack',
                    props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                    children: [
                      MFNode(
                        id: 'features-row-feature',
                        type: 'Text',
                        props: {'text': {'ref': 'item.feature'}},
                        constraints: const MFSelfConstraint(width: 'fill'),
                      ),
                      MFNode(
                        id: 'features-row-route',
                        type: 'Text',
                        props: {'text': {'ref': 'item.route'}},
                        constraints: const MFSelfConstraint(width: 'fill'),
                      ),
                      MFNode(
                        id: 'features-row-uses',
                        type: 'Text',
                        props: {'text': {'ref': 'item.usesText'}},
                        constraints: const MFSelfConstraint(width: 64),
                      ),
                      MFNode(
                        id: 'features-row-last',
                        type: 'Text',
                        props: {'text': {'ref': 'item.lastText'}},
                        constraints: const MFSelfConstraint(width: 132),
                      ),
                    ],
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );

MFPage _logsPage() => MFPage(
      id: 'logs-page',
      route: '/admin/logs',
      stateMembers: const ['eventFilter', 'windowFilter', 'routeFilter', 'logRows', 'totalText', 'nextPageToken'],
      onEnter: 'logs-enter',
      layerRegions: _layerRegions,
      tree: MFNode(
        id: 'logs-page',
        type: 'Stack',
        children: [
          _pageHeader(pageId: 'logs-page', titleMessage: 'app.logs.title'),
          MFNode(
            id: 'logs-content',
            type: 'Stack',
            layer: 'site-content',
            children: [
              MFNode(
                id: 'logs-filters',
                type: 'Stack',
                props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                children: [
                  MFNode(
                    id: 'logs-event-select',
                    type: 'Select',
                    constraints: const MFSelfConstraint(width: 190),
                    props: {
                      'label': '事件',
                      'options': [
                        {'value': '', 'label': '全部事件'},
                        {'value': 'ops.page.viewed', 'label': '页面浏览'},
                        {'value': 'ops.page.left', 'label': '页面退出'},
                        {'value': 'ops.feature.used', 'label': '功能调用'},
                        {'value': 'ops.habit.checked-in', 'label': '打卡'},
                        {'value': 'ops.habit.created', 'label': '建习惯'},
                        {'value': 'ops.habit.deleted', 'label': '删习惯'},
                      ],
                      'value': {'ref': 'state.eventFilter'},
                    },
                  ),
                  MFNode(
                    id: 'logs-window-select',
                    type: 'Select',
                    constraints: const MFSelfConstraint(width: 190),
                    props: {
                      'label': '时间范围',
                      'options': [
                        {'value': '1h', 'label': '近 1 小时'},
                        {'value': '24h', 'label': '近 24 小时'},
                        {'value': '7d', 'label': '近 7 天'},
                        {'value': 'all', 'label': '全部'},
                      ],
                      'value': {'ref': 'state.windowFilter'},
                    },
                  ),
                  MFNode(
                    id: 'logs-route-input',
                    type: 'Input',
                    props: const {'placeholder': '路由包含…'},
                    constraints: const MFSelfConstraint(width: 'fill'),
                  ),
                  const MFNode(id: 'logs-query-btn', type: 'Button', props: {'label': '查询'}),
                ],
              ),
              MFNode(id: 'logs-total', type: 'Text', props: {'text': {'ref': 'state.totalText'}}),
              MFNode(
                id: 'logs-list',
                type: 'List',
                props: {'items': {'ref': 'state.logRows'}},
                children: [
                  MFNode(
                    id: 'logs-row',
                    type: 'Stack',
                    props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                    children: [
                      MFNode(
                        id: 'logs-row-time',
                        type: 'Text',
                        props: {'text': {'ref': 'item.timeText'}},
                        constraints: const MFSelfConstraint(width: 132),
                      ),
                      MFNode(
                        id: 'logs-row-name',
                        type: 'Text',
                        props: {'text': {'ref': 'item.name'}},
                        constraints: const MFSelfConstraint(width: 'fill'),
                      ),
                      MFNode(
                        id: 'logs-row-route',
                        type: 'Text',
                        props: {'text': {'ref': 'item.route'}},
                        constraints: const MFSelfConstraint(width: 150),
                      ),
                      MFNode(
                        id: 'logs-row-info',
                        type: 'Text',
                        props: {'text': {'ref': 'item.infoText'}},
                        constraints: const MFSelfConstraint(width: 150),
                      ),
                    ],
                  ),
                ],
              ),
              const MFNode(id: 'logs-more-btn', type: 'Button', props: {'label': '加载更多'}),
            ],
          ),
        ],
      ),
    );

MFPage _exportPage() => MFPage(
      id: 'export-page',
      route: '/admin/export',
      stateMembers: const ['range', 'exportResult'],
      onEnter: 'export-enter',
      layerRegions: _layerRegions,
      tree: MFNode(
        id: 'export-page',
        type: 'Stack',
        children: [
          _pageHeader(pageId: 'export-page', titleMessage: 'app.export.title'),
          MFNode(
            id: 'export-content',
            type: 'Stack',
            layer: 'site-content',
            children: [
              MFNode(
                id: 'export-form',
                type: 'Stack',
                props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                children: [
                  MFNode(
                    id: 'export-range-select',
                    type: 'Select',
                    constraints: const MFSelfConstraint(width: 190),
                    props: {
                      'label': '导出范围',
                      'options': [
                        {'value': '24h', 'label': '近 24 小时'},
                        {'value': '7d', 'label': '近 7 天'},
                        {'value': 'all', 'label': '全部'},
                      ],
                      'value': {'ref': 'state.range'},
                    },
                  ),
                  const MFNode(id: 'export-run-btn', type: 'Button', props: {'label': '导出 JSONL'}),
                  const MFNode(
                    id: 'export-prune-btn',
                    type: 'Button',
                    props: {'label': '清理 7 天前日志', 'variant': 'danger'},
                  ),
                ],
              ),
              MFNode(id: 'export-result', type: 'Text', props: {'text': {'ref': 'state.exportResult'}}),
            ],
          ),
        ],
      ),
    );

MFPage _collectionPage() => MFPage(
      id: 'collection-page',
      route: '/admin/collection',
      stateMembers: const ['collectEnabled', 'statusText', 'metricRows'],
      onEnter: 'collection-enter',
      layerRegions: _layerRegions,
      tree: MFNode(
        id: 'collection-page',
        type: 'Stack',
        children: [
          _pageHeader(pageId: 'collection-page', titleMessage: 'app.collection.title'),
          MFNode(
            id: 'collection-content',
            type: 'Stack',
            layer: 'site-content',
            children: [
              MFNode(id: 'collection-status', type: 'Text', props: {'text': {'ref': 'state.statusText'}}),
              MFNode(
                id: 'collection-switch-row',
                type: 'Stack',
                props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                children: [
                  MFNode(
                    id: 'collection-switch',
                    type: 'Checkbox',
                    props: {'value': {'ref': 'state.collectEnabled'}},
                  ),
                  const MFNode(
                    id: 'collection-switch-label',
                    type: 'Text',
                    props: {'text': '开启日志收集（控制开关由采集端每次投递前读取）'},
                  ),
                ],
              ),
              MFNode(
                id: 'collection-metric-list',
                type: 'List',
                props: {'items': {'ref': 'state.metricRows'}},
                children: [
                  _row(id: 'collection-metric-row', labelRef: 'item.label', valueRef: 'item.value'),
                ],
              ),
            ],
          ),
        ],
      ),
    );

/// 事件查询动作链（过滤参数来自页面状态；翻页时把已有行与页令牌传入）。
List<MFAction> _queryActions({required MFExpr existing, required MFExpr pageToken}) => [
      MFAdapterAction(
        kind: 'function',
        call: 'fn.ops.events-query',
        arguments: {
          'eventName': MFRef('state.eventFilter'),
          'routeContains': MFRef('state.routeFilter'),
          'window': MFRef('state.windowFilter'),
          'existing': existing,
          'pageToken': pageToken,
        },
        as: 'r',
      ),
      MFStateAction(target: 'logRows', value: MFRef('prev.r.rows')),
      MFStateAction(target: 'totalText', value: MFRef('prev.r.totalText')),
      MFStateAction(target: 'nextPageToken', value: MFRef('prev.r.pageToken')),
    ];

MFBindingMap _opsBindings() => MFBindingMap(
      id: 'ops-map',
      syntaxVersion: '1.0',
      bindings: [
        // —— 运营概览 ——
        MFBinding(
          id: 'overview-enter',
          on: 'overview-page.onEnter',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.ops.overview', as: 'o'),
            MFAdapterAction(kind: 'function', call: 'fn.ops.quality', as: 'q'),
            MFAdapterAction(kind: 'function', call: 'fn.ops.habits', as: 'h'),
            MFStateAction(target: 'kpiRows', value: MFRef('prev.o.rows')),
            MFStateAction(target: 'updatedText', value: MFRef('prev.o.updatedText')),
            MFStateAction(target: 'qualityRows', value: MFRef('prev.q.rows')),
            MFStateAction(target: 'habitRows', value: MFRef('prev.h.rows')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'overview-refresh',
          on: 'overview-refresh.press',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.ops.overview', as: 'o'),
            MFAdapterAction(kind: 'function', call: 'fn.ops.quality', as: 'q'),
            MFAdapterAction(kind: 'function', call: 'fn.ops.habits', as: 'h'),
            MFStateAction(target: 'kpiRows', value: MFRef('prev.o.rows')),
            MFStateAction(target: 'updatedText', value: MFRef('prev.o.updatedText')),
            MFStateAction(target: 'qualityRows', value: MFRef('prev.q.rows')),
            MFStateAction(target: 'habitRows', value: MFRef('prev.h.rows')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        // —— 页面分析 ——
        MFBinding(
          id: 'pages-enter',
          on: 'pages-page.onEnter',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.ops.pages', as: 'p'),
            MFStateAction(target: 'pageRows', value: MFRef('prev.p.rows')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'pages-refresh',
          on: 'pages-refresh.press',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.ops.pages', as: 'p'),
            MFStateAction(target: 'pageRows', value: MFRef('prev.p.rows')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        // —— 功能使用 ——
        MFBinding(
          id: 'features-enter',
          on: 'features-page.onEnter',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.ops.features', as: 'f'),
            MFStateAction(target: 'featureRows', value: MFRef('prev.f.rows')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'features-refresh',
          on: 'features-refresh.press',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.ops.features', as: 'f'),
            MFStateAction(target: 'featureRows', value: MFRef('prev.f.rows')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        // —— 日志检索 ——
        MFBinding(
          id: 'logs-enter',
          on: 'logs-page.onEnter',
          actions: [
            MFStateAction(target: 'eventFilter', value: MFLiteral('')),
            MFStateAction(target: 'windowFilter', value: MFLiteral('24h')),
            MFStateAction(target: 'routeFilter', value: MFLiteral('')),
            ..._queryActions(existing: const MFLiteral(null), pageToken: const MFLiteral(null)),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'logs-filter-event',
          on: 'logs-event-select.change',
          actions: [
            MFStateAction(target: 'eventFilter', value: MFRef('prop.value')),
            ..._queryActions(existing: const MFLiteral(null), pageToken: const MFLiteral(null)),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'logs-filter-window',
          on: 'logs-window-select.change',
          actions: [
            MFStateAction(target: 'windowFilter', value: MFRef('prop.value')),
            ..._queryActions(existing: const MFLiteral(null), pageToken: const MFLiteral(null)),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'logs-filter-route',
          on: 'logs-route-input.change',
          actions: [MFStateAction(target: 'routeFilter', value: MFRef('prop.value'))],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'logs-query',
          on: 'logs-query-btn.press',
          actions: _queryActions(existing: const MFLiteral(null), pageToken: const MFLiteral(null)),
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'logs-more',
          on: 'logs-more-btn.press',
          guard: MFCompare('neq', [MFRef('state.nextPageToken'), const MFLiteral(null)]),
          actions: _queryActions(existing: MFRef('state.logRows'), pageToken: MFRef('state.nextPageToken')),
          policy: MFPolicy.rejectNew,
        ),
        // —— 导出与保留 ——
        MFBinding(
          id: 'export-enter',
          on: 'export-page.onEnter',
          actions: [
            MFStateAction(target: 'range', value: MFLiteral('7d')),
            MFStateAction(target: 'exportResult', value: MFLiteral('')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'export-range',
          on: 'export-range-select.change',
          actions: [MFStateAction(target: 'range', value: MFRef('prop.value'))],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'export-run',
          on: 'export-run-btn.press',
          actions: [
            MFAdapterAction(
              kind: 'adapter',
              call: 'adapter.ops.export',
              arguments: {'range': MFRef('state.range')},
              as: 'r',
            ),
            MFStateAction(target: 'exportResult', value: MFRef('prev.r.resultText')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'export-prune',
          on: 'export-prune-btn.press',
          actions: [
            MFAdapterAction(kind: 'adapter', call: 'adapter.ops.prune', as: 'p'),
            MFStateAction(target: 'exportResult', value: MFRef('prev.p.resultText')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        // —— 采集控制 ——
        MFBinding(
          id: 'collection-enter',
          on: 'collection-page.onEnter',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.ops.status', as: 's'),
            MFStateAction(target: 'collectEnabled', value: MFRef('prev.s.enabled')),
            MFStateAction(target: 'statusText', value: MFRef('prev.s.statusText')),
            MFStateAction(target: 'metricRows', value: MFRef('prev.s.rows')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'collection-toggle',
          on: 'collection-switch.change',
          actions: [
            MFStateAction(
              target: 'collectEnabled',
              value: MFLogic('not', [MFRef('state.collectEnabled')]),
            ),
            MFAdapterAction(
              kind: 'adapter',
              call: 'adapter.ops.set-collection',
              arguments: {'enabled': MFRef('state.collectEnabled')},
              as: 'r',
            ),
            MFStateAction(target: 'statusText', value: MFRef('prev.r.statusText')),
            MFAdapterAction(kind: 'function', call: 'fn.ops.status', as: 's'),
            MFStateAction(target: 'metricRows', value: MFRef('prev.s.rows')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        // —— 导航（每页 5 个直达按钮） ——
        for (final from in _pageCodes.values)
          for (final target in _pageCodes.entries)
            if (target.value != from)
              MFBinding(
                id: 'go-$from-${target.value}',
                on: 'nav-$from-${target.value}.press',
                actions: [MFNavigationAction(target: target.key)],
                policy: MFPolicy.rejectNew,
              ),
      ],
    );
