/// 个人习惯打卡平台的 MicroFlow 项目模型（§4）：页面树、绑定图、i18n、
/// Token 与双层主题全部以声明式模型承载，页面与交互不携带可执行逻辑
/// （§2.9 三平面分离）。
///
/// 结构说明：
/// - 页面根节点与页面同 id，其契约声明 `onEnter` 事件——页面生命周期绑定
///   的 §39 锚点（运行时在页面打开时直接执行，见 registry.dart 说明）；
/// - 顶层子节点按 `layer` 声明归入显式分区（§7.1）：site-header 固定头部、
///   site-content 滚动内容区；
/// - 数据经 List 声明式列表绑定渲染，`item.<field>` 项作用域来自注册函数
///   返回的结构化行（§39 事件上下文）。
library;

import 'package:microflow4_flutter/microflow4_flutter.dart';

/// 构建打卡平台项目。页面树、绑定与导航图三者互为引用，任何一方的悬空
/// 引用都会被静态校验门禁拒绝。
MFProject buildHabitProject() {
  return MFProject(
    manifest: const MFManifest(
      projectId: 'habit-tracker',
      syntaxVersion: '1.0',
      targets: ['web'],
      entryPage: 'today-page',
      defaultTheme: 'theme-light',
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN'],
    ),
    pages: [_todayPage(), _habitsPage(), _statsPage()],
    bindingMaps: {'habit-map': _habitBindings()},
    i18n: const MFI18nCatalog(
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN'],
      messages: {
        'app.today.title': {'zh-CN': '今日打卡'},
        'app.habits.title': {'zh-CN': '习惯管理'},
        'app.stats.title': {'zh-CN': '数据统计'},
        'app.stats.total-label': {'zh-CN': '累计打卡'},
        'app.stats.active-label': {'zh-CN': '活跃天数'},
        'app.stats.best-label': {'zh-CN': '最长连续'},
      },
    ),
    // Token（§36.2）：产品主题投影的语义值基础集。
    tokens: const {
      'theme-light': MFTokenSet(
        id: 'theme-light',
        tokens: {
          'color.action': '#2563eb',
          'color.bg.surface': '#ffffff',
          'color.bg.inverse': '#111827',
          'color.text.primary': '#111827',
          'color.text.inverse': '#f9fafb',
          'color.foreground': '#111827',
          'color.background': '#ffffff',
        },
      ),
    },
    // 双层主题（§36.3，基线 7）：theme-dark 经 extends 继承 light，仅重定向
    // 已有 token；切换只影响新建实例。
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
    // 样式片（§36.4）：值只允许 token 引用，字面量是静态错误。
    styleSheets: const {
      'style-title': MFStyleSheet(
        id: 'style-title',
        base: {'foreground': 'color.text.primary'},
      ),
    },
    // 导航图（§9）：三页全互联，静态校验检查入口可达性。
    navigation: const MFNavigationSpec(edges: [
      MFNavEdge(from: 'today-page', to: 'habits-page'),
      MFNavEdge(from: 'today-page', to: 'stats-page'),
      MFNavEdge(from: 'habits-page', to: 'today-page'),
      MFNavEdge(from: 'habits-page', to: 'stats-page'),
      MFNavEdge(from: 'stats-page', to: 'today-page'),
      MFNavEdge(from: 'stats-page', to: 'habits-page'),
    ]),
  );
}

const _layerRegions = [
  MFRegionConstraint(id: 'site-header', region: 'header'),
  MFRegionConstraint(id: 'site-content', region: 'content', scroll: true),
];

/// 页头：标题 + 本页导航按钮。节点 id 全项目唯一（绑定锚点按全局节点
/// id 解析，跨页重复 id 会相互误触发）。
MFNode _pageHeader({
  required String pageId,
  required String titleMessage,
  required List<MFNode> navButtons,
}) =>
    MFNode(
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
        MFNode(
          id: '$pageId-nav',
          type: 'Stack',
          props: const {'direction': 'horizontal'},
          children: navButtons,
        ),
      ],
    );

const _todayNav = [
  MFNode(id: 'today-nav-habits', type: 'Button', props: {'label': '习惯管理', 'variant': 'secondary'}),
  MFNode(id: 'today-nav-stats', type: 'Button', props: {'label': '数据统计', 'variant': 'secondary'}),
];

const _habitsNav = [
  MFNode(id: 'habits-nav-today', type: 'Button', props: {'label': '返回今日', 'variant': 'secondary'}),
  MFNode(id: 'habits-nav-stats', type: 'Button', props: {'label': '数据统计', 'variant': 'secondary'}),
];

const _statsNav = [
  MFNode(id: 'stats-nav-today', type: 'Button', props: {'label': '返回今日', 'variant': 'secondary'}),
  MFNode(id: 'stats-nav-habits', type: 'Button', props: {'label': '习惯管理', 'variant': 'secondary'}),
];

MFPage _todayPage() => MFPage(
      id: 'today-page',
      route: '/today',
      stateMembers: const ['todayItems', 'summary', 'emptyText'],
      onEnter: 'today-enter',
      layerRegions: _layerRegions,
      tree: MFNode(
        id: 'today-page',
        type: 'Stack',
        children: [
          _pageHeader(pageId: 'today-page', titleMessage: 'app.today.title', navButtons: _todayNav),
          MFNode(
            id: 'today-content',
            type: 'Stack',
            layer: 'site-content',
            children: [
              MFNode(id: 'today-summary', type: 'Text', props: {'text': {'ref': 'state.summary'}}),
              MFNode(id: 'today-empty', type: 'Text', props: {'text': {'ref': 'state.emptyText'}}),
              MFNode(
                id: 'today-list',
                type: 'List',
                props: {'items': {'ref': 'state.todayItems'}},
                children: [
                  MFNode(
                    id: 'today-row',
                    type: 'Stack',
                    props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                    children: [
                      MFNode(
                        id: 'today-row-icon',
                        type: 'Icon',
                        props: const {'name': 'star', 'size': 20},
                      ),
                      MFNode(
                        id: 'today-row-name',
                        type: 'Text',
                        props: {'text': {'ref': 'item.name'}},
                        constraints: const MFSelfConstraint(width: 'fill'),
                      ),
                      MFNode(
                        id: 'today-row-streak',
                        type: 'Text',
                        props: {'text': {'ref': 'item.streakText'}},
                      ),
                      MFNode(
                        id: 'today-row-action',
                        type: 'Button',
                        props: {'label': {'ref': 'item.actionLabel'}, 'variant': {'ref': 'item.variant'}},
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

MFPage _habitsPage() => MFPage(
      id: 'habits-page',
      route: '/habits',
      stateMembers: const ['habitItems', 'draftName', 'error', 'emptyText'],
      onEnter: 'habits-enter',
      layerRegions: _layerRegions,
      tree: MFNode(
        id: 'habits-page',
        type: 'Stack',
        children: [
          _pageHeader(pageId: 'habits-page', titleMessage: 'app.habits.title', navButtons: _habitsNav),
          MFNode(
            id: 'habits-content',
            type: 'Stack',
            layer: 'site-content',
            children: [
              MFNode(
                id: 'habits-form',
                type: 'Stack',
                props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                children: [
                  MFNode(
                    id: 'habits-draft-input',
                    type: 'Input',
                    props: const {'placeholder': '习惯名称'},
                    constraints: const MFSelfConstraint(width: 'fill'),
                  ),
                  const MFNode(id: 'habits-submit', type: 'Button', props: {'label': '添加'}),
                ],
              ),
              MFNode(id: 'habits-error', type: 'Text', props: {'text': {'ref': 'state.error'}}),
              MFNode(id: 'habits-empty', type: 'Text', props: {'text': {'ref': 'state.emptyText'}}),
              MFNode(
                id: 'habits-list',
                type: 'List',
                props: {'items': {'ref': 'state.habitItems'}},
                children: [
                  MFNode(
                    id: 'habit-row',
                    type: 'Stack',
                    props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                    children: [
                      MFNode(
                        id: 'habit-row-icon',
                        type: 'Icon',
                        props: {'name': {'ref': 'item.icon'}, 'size': 20},
                      ),
                      MFNode(
                        id: 'habit-row-name',
                        type: 'Text',
                        props: {'text': {'ref': 'item.name'}},
                        constraints: const MFSelfConstraint(width: 'fill'),
                      ),
                      MFNode(
                        id: 'habit-row-created',
                        type: 'Text',
                        props: {'text': {'ref': 'item.createdAtText'}},
                      ),
                      MFNode(
                        id: 'habit-row-checkins',
                        type: 'Text',
                        props: {'text': {'ref': 'item.checkinsText'}},
                      ),
                      const MFNode(
                        id: 'habit-row-delete',
                        type: 'Button',
                        props: {'label': '删除', 'variant': 'danger'},
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

MFPage _statsPage() => MFPage(
      id: 'stats-page',
      route: '/stats',
      stateMembers: const ['statItems', 'totalText', 'activeDaysText', 'bestStreakText', 'emptyText'],
      onEnter: 'stats-enter',
      layerRegions: _layerRegions,
      tree: MFNode(
        id: 'stats-page',
        type: 'Stack',
        children: [
          _pageHeader(pageId: 'stats-page', titleMessage: 'app.stats.title', navButtons: _statsNav),
          MFNode(
            id: 'stats-content',
            type: 'Stack',
            layer: 'site-content',
            children: [
              MFNode(
                id: 'stats-kpis',
                type: 'Stack',
                props: const {'direction': 'horizontal', 'align': 'space-between'},
                children: [
                  MFNode(
                    id: 'stats-kpi-total',
                    type: 'Stack',
                    children: [
                      MFNode(id: 'stats-kpi-total-label', type: 'Text', t: 'app.stats.total-label'),
                      MFNode(
                        id: 'stats-kpi-total-value',
                        type: 'Text',
                        props: {'text': {'ref': 'state.totalText'}},
                      ),
                    ],
                  ),
                  MFNode(
                    id: 'stats-kpi-active',
                    type: 'Stack',
                    children: [
                      MFNode(id: 'stats-kpi-active-label', type: 'Text', t: 'app.stats.active-label'),
                      MFNode(
                        id: 'stats-kpi-active-value',
                        type: 'Text',
                        props: {'text': {'ref': 'state.activeDaysText'}},
                      ),
                    ],
                  ),
                  MFNode(
                    id: 'stats-kpi-best',
                    type: 'Stack',
                    children: [
                      MFNode(id: 'stats-kpi-best-label', type: 'Text', t: 'app.stats.best-label'),
                      MFNode(
                        id: 'stats-kpi-best-value',
                        type: 'Text',
                        props: {'text': {'ref': 'state.bestStreakText'}},
                      ),
                    ],
                  ),
                ],
              ),
              MFNode(id: 'stats-empty', type: 'Text', props: {'text': {'ref': 'state.emptyText'}}),
              MFNode(
                id: 'stats-list',
                type: 'List',
                props: {'items': {'ref': 'state.statItems'}},
                children: [
                  MFNode(
                    id: 'stats-row',
                    type: 'Stack',
                    props: const {'direction': 'horizontal', 'crossAlign': 'center'},
                    children: [
                      MFNode(
                        id: 'stats-row-name',
                        type: 'Text',
                        props: {'text': {'ref': 'item.name'}},
                        constraints: const MFSelfConstraint(width: 'fill'),
                      ),
                      MFNode(
                        id: 'stats-row-total',
                        type: 'Text',
                        props: {'text': {'ref': 'item.totalText'}},
                        constraints: const MFSelfConstraint(width: 64),
                      ),
                      MFNode(
                        id: 'stats-row-streak',
                        type: 'Text',
                        props: {'text': {'ref': 'item.streakText'}},
                        constraints: const MFSelfConstraint(width: 88),
                      ),
                      MFNode(
                        id: 'stats-row-last7',
                        type: 'Text',
                        props: {'text': {'ref': 'item.last7Text'}},
                        constraints: const MFSelfConstraint(width: 72),
                      ),
                      MFNode(
                        id: 'stats-row-last30',
                        type: 'Text',
                        props: {'text': {'ref': 'item.last30Text'}},
                        constraints: const MFSelfConstraint(width: 72),
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

MFBindingMap _habitBindings() => MFBindingMap(
      id: 'habit-map',
      syntaxVersion: '1.0',
      bindings: [
        // —— 今日页 ——
        MFBinding(
          id: 'today-enter',
          on: 'today-page.onEnter',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.habits.today', as: 'load'),
            MFStateAction(target: 'todayItems', value: MFRef('prev.load.items')),
            MFStateAction(target: 'summary', value: MFRef('prev.load.summary')),
            MFStateAction(target: 'emptyText', value: MFRef('prev.load.emptyText')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'today-check',
          on: 'today-row-action.press',
          actions: [
            MFAdapterAction(
              kind: 'adapter',
              call: 'adapter.habits.toggle',
              arguments: {'habitId': MFRef('item.id'), 'name': MFRef('item.name')},
              as: 'toggled',
            ),
            MFAdapterAction(kind: 'function', call: 'fn.habits.today', as: 'load'),
            MFStateAction(target: 'todayItems', value: MFRef('prev.load.items')),
            MFStateAction(target: 'summary', value: MFRef('prev.load.summary')),
            MFStateAction(target: 'emptyText', value: MFRef('prev.load.emptyText')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'today-open-habits',
          on: 'today-nav-habits.press',
          actions: [MFNavigationAction(target: 'habits-page')],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'today-open-stats',
          on: 'today-nav-stats.press',
          actions: [MFNavigationAction(target: 'stats-page')],
          policy: MFPolicy.rejectNew,
        ),
        // —— 习惯管理页 ——
        MFBinding(
          id: 'habits-enter',
          on: 'habits-page.onEnter',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.habits.all', as: 'load'),
            MFStateAction(target: 'habitItems', value: MFRef('prev.load.items')),
            MFStateAction(target: 'emptyText', value: MFRef('prev.load.emptyText')),
            MFStateAction(target: 'draftName', value: MFLiteral('')),
            MFStateAction(target: 'error', value: MFLiteral('')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'habits-mirror-draft',
          on: 'habits-draft-input.change',
          actions: [MFStateAction(target: 'draftName', value: MFRef('prop.value'))],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'habits-create',
          on: 'habits-submit.press',
          actions: [
            MFAdapterAction(
              kind: 'adapter',
              call: 'adapter.habits.create',
              arguments: {'name': MFRef('state.draftName')},
              as: 'created',
            ),
            MFAdapterAction(kind: 'function', call: 'fn.habits.all', as: 'load'),
            MFStateAction(target: 'error', value: MFRef('prev.created.error')),
            MFStateAction(target: 'habitItems', value: MFRef('prev.load.items')),
            MFStateAction(target: 'emptyText', value: MFRef('prev.load.emptyText')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'habits-remove',
          on: 'habit-row-delete.press',
          actions: [
            MFAdapterAction(
              kind: 'adapter',
              call: 'adapter.habits.delete',
              arguments: {'habitId': MFRef('item.id'), 'name': MFRef('item.name')},
              as: 'deleted',
            ),
            MFAdapterAction(kind: 'function', call: 'fn.habits.all', as: 'load'),
            MFStateAction(target: 'habitItems', value: MFRef('prev.load.items')),
            MFStateAction(target: 'emptyText', value: MFRef('prev.load.emptyText')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'habits-open-today',
          on: 'habits-nav-today.press',
          actions: [MFNavigationAction(target: 'today-page')],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'habits-open-stats',
          on: 'habits-nav-stats.press',
          actions: [MFNavigationAction(target: 'stats-page')],
          policy: MFPolicy.rejectNew,
        ),
        // —— 统计页 ——
        MFBinding(
          id: 'stats-enter',
          on: 'stats-page.onEnter',
          actions: [
            MFAdapterAction(kind: 'function', call: 'fn.habits.stats', as: 'stats'),
            MFStateAction(target: 'statItems', value: MFRef('prev.stats.items')),
            MFStateAction(target: 'totalText', value: MFRef('prev.stats.totalText')),
            MFStateAction(target: 'activeDaysText', value: MFRef('prev.stats.activeDaysText')),
            MFStateAction(target: 'bestStreakText', value: MFRef('prev.stats.bestStreakText')),
            MFStateAction(target: 'emptyText', value: MFRef('prev.stats.emptyText')),
          ],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'stats-open-today',
          on: 'stats-nav-today.press',
          actions: [MFNavigationAction(target: 'today-page')],
          policy: MFPolicy.rejectNew,
        ),
        MFBinding(
          id: 'stats-open-habits',
          on: 'stats-nav-habits.press',
          actions: [MFNavigationAction(target: 'habits-page')],
          policy: MFPolicy.rejectNew,
        ),
      ],
    );
