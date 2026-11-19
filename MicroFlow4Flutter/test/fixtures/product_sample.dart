import 'package:microflow_model/microflow_model.dart';

/// 0.11.0 产品级表达力参考样例（测试资产，非业务应用）：
/// 一个仪表盘形态的页面模型，覆盖视觉面全部新能力——
/// AppBar 品牌标题 / Scaffold 背景 token / 表面卡片（背景+圆角+边框+阴影）/
/// 容器留白与限宽 / 标题排版层次 / 指标行卡片网格 / 列表表面行。
/// 用法：测试直接以本模型驱动 MicroFlowApp 渲染并断言结构；宿主可参考
/// 此声明方式表达产品级 UI。
MFProject productSampleProject() => MFProject(
      manifest: const MFManifest(projectId: 'surface-sample', entryPage: 'dashboard',
          defaultTheme: 'theme-light'),
      pages: [
        MFPage(
          id: 'dashboard',
          route: '/dashboard',
          stateMembers: const ['rows'],
          tree: MFNode(
            id: 'root',
            type: 'Stack',
            props: const {
              'expand': true,
              'padding': 24,
              'gap': 16,
              'maxWidth': 960,
            },
            children: [
              MFNode(id: 'title', type: 'Text',
                  props: const {'text': '运营总览', 'size': 22, 'weight': 700},
                  style: 'style-title'),
              // 指标行：三张表面卡片（Grid 均分 + Card 化 Stack）。
              MFNode(
                id: 'metric-row',
                type: 'Grid',
                props: {'columns': 3, 'gap': 12},
                children: [
                  _metricCard('m1', '事件总数', '10'),
                  _metricCard('m2', '活跃会话', '5'),
                  _metricCard('m3', '丢失率', '0.0%'),
                ],
              ),
              // 表面面板：有边框 + 弱阴影 + 内边距的内容分组。
              MFNode(
                id: 'panel',
                type: 'Stack',
                props: const {
                  'background': 'color.surface',
                  'radius': 10,
                  'borderWidth': 1,
                  'borderColor': 'color.border',
                  'shadow': 'soft',
                  'padding': 16,
                  'gap': 10,
                },
                children: [
                  MFNode(id: 'panel-title', type: 'Text',
                      props: const {'text': '最近事件', 'size': 15, 'weight': 600},
                      style: 'style-title'),
                  MFNode(
                    id: 'event-list',
                    type: 'List',
                    props: {'items': MFRef('state.rows')},
                    children: [
                      MFNode(
                        id: 'event-row',
                        type: 'Stack',
                        props: const {
                          'direction': 'horizontal',
                          'align': 'space-between',
                          'background': 'color.surface',
                          'radius': 8,
                          'padding': 10,
                        },
                        children: [
                          MFNode(id: 'event-name', type: 'Text',
                              props: {'text': MFRef('item.name')}),
                          MFNode(id: 'event-count', type: 'Text',
                              props: {'text': MFRef('item.count'), 'foreground': 'color.text.muted'}),
                        ],
                      ),
                    ],
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
      tokens: const {
        'theme-light': MFTokenSet(
          id: 'theme-light',
          tokens: {
            'color.action': '#0070F3',
            'color.brand': '#0070F3',
            'color.background': '#F7F8FA',
            'color.surface': '#FFFFFF',
            'color.border': '#E5E7EB',
            'color.foreground': '#171717',
            'color.text.muted': '#666666',
          },
        ),
      },
      styleSheets: const {
        'style-title': MFStyleSheet(id: 'style-title', base: {'foreground': 'color.foreground'}),
      },
    );

MFNode _metricCard(String id, String label, String value) => MFNode(
      id: id,
      type: 'Stack',
      props: const {
        'background': 'color.surface',
        'radius': 10,
        'borderWidth': 1,
        'borderColor': 'color.border',
        'shadow': 'raised',
        'padding': 14,
        'gap': 6,
      },
      children: [
        MFNode(id: '\$id-label', type: 'Text',
            props: {'text': label, 'foreground': 'color.text.muted', 'size': 12, 'weight': 500}),
        MFNode(id: '\$id-value', type: 'Text',
            props: {'text': value, 'size': 26, 'weight': 700}),
      ],
    );
