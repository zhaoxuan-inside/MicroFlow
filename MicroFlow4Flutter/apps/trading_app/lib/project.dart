/// 交易平台的项目模型（§4）——**通过 authoring 命令面构造**。
///
/// 页面不直接拼装 MFProject，而是经 [MFAuthoringSession] 的结构化命令
/// （§14 `create_page` / `connect_navigation`）逐条提交：每条命令走与发布
/// 相同的静态校验门禁（§2.7），产生修改审计与可回滚修订——这正是
/// "ZCode 通过框架构建前端代码"的框架内路径。
library;

import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'registry.dart';

const _actor = 'zcode-builder';

MFNode _button(String id, String label) =>
    MFNode(id: id, type: 'Button', props: {'label': label, 'variant': 'secondary'});

/// 经 authoring 命令面构建交易平台项目；返回末轮会话与聚合审计链。
///
/// 门禁是活的（§2.7）：onEnter 引用的绑定必须与页面同批进入候选项目，而
/// 绑定的目标节点又必须随页面就位——因此按页面分三轮会话，每轮以
/// copyWith 把该页的数据加载/导航绑定同批带入，再提交 create_page。
/// 绑定图编辑的专用命令（§14 后续扩展）落地后可收敛为单会话。
({MFAuthoringSession session, List<MFRevision> audit}) buildTradingViaAuthoring({MFRegistry? registry}) {
  final reg = registry ?? buildTradingRegistry();
  var session = MFAuthoringSession(project: _baseProject(), registry: reg, actor: _actor);
  final audit = <MFRevision>[];

  _submit(session, session.createPage(
    pageId: 'home-page',
    route: '/home',
    tree: _homeTree(),
    stateMembers: const ['keyword', 'productItems', 'emptyText', 'cartHint'],
    onEnter: 'home-enter',
  ));
  audit.addAll(session.revisions);
  session = MFAuthoringSession(
    project: session.project.copyWith(bindingMaps: {'trading-map': _map([_homeBindings, _cartBindings])}),
    registry: reg,
    actor: _actor,
  );
  _submit(session, session.createPage(
    pageId: 'cart-page',
    route: '/cart',
    tree: _cartTree(),
    stateMembers: const ['cartItems', 'totalText', 'orderText', 'emptyText'],
    onEnter: 'cart-enter',
    navigationFrom: 'home-page',
  ));
  audit.addAll(session.revisions.take(1));
  session = MFAuthoringSession(
    project: session.project.copyWith(bindingMaps: {'trading-map': _map([_homeBindings, _cartBindings, _ordersBindings, _navBindings])}),
    registry: reg,
    actor: _actor,
  );
  _submit(session, session.createPage(
    pageId: 'orders-page',
    route: '/orders',
    tree: _ordersTree(),
    stateMembers: const ['orderItems', 'gmvText', 'emptyText'],
    onEnter: 'orders-enter',
    navigationFrom: 'home-page',
  ));
  audit.addAll(session.revisions);
  _submitNav(session, session.connectNavigation(from: 'cart-page', to: 'orders-page'));
  _submitNav(session, session.connectNavigation(from: 'orders-page', to: 'home-page'));
  audit.addAll(session.revisions.skip(1));
  return (session: session, audit: audit);
}

/// 构建完整可运行项目：authoring 命令面构造页面 + 全量绑定图。
MFProject buildTradingProject({MFRegistry? registry}) =>
    buildTradingViaAuthoring(registry: registry).session.project;

MFBindingMap _map(Iterable<List<MFBinding>> groups) => MFBindingMap(
      id: 'trading-map',
      schemaVersion: '1.0',
      syntaxVersion: '1.0',
      bindings: [for (final g in groups) ...g],
    );

void _submit(MFAuthoringSession session, MFCommandResult result) {
  if (!result.ok) {
    throw StateError(
        'authoring 命令 ${result.command} 被门禁拒绝：${[for (final d in result.diagnostics) d.message]}');
  }
}

void _submitNav(MFAuthoringSession session, MFCommandResult result) {
  if (!result.ok) {
    throw StateError(
        'authoring 命令 ${result.command} 被门禁拒绝：${[for (final d in result.diagnostics) d.message]}');
  }
}

MFProject _baseProject() {
  return MFProject(
    manifest: const MFManifest(
      projectId: 'trading-platform',
      syntaxVersion: '1.0',
      targets: ['web'],
      entryPage: 'home-page',
      defaultTheme: 'theme-light',
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN'],
    ),
    pages: const [],
    bindingMaps: {'trading-map': _map([_homeBindings])},
    i18n: const MFI18nCatalog(
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN'],
      messages: {
        'app.home.title': {'zh-CN': '交易平台首页'},
        'app.cart.title': {'zh-CN': '购物车'},
        'app.orders.title': {'zh-CN': '我的订单'},
      },
    ),
    tokens: const {
      'theme-light': MFTokenSet(id: 'theme-light', tokens: {
        'color.action': '#e94833',
        'color.bg.surface': '#ffffff',
        'color.text.primary': '#111827',
        'color.foreground': '#111827',
        'color.background': '#ffffff',
      }),
    },
    navigation: const MFNavigationSpec(edges: []),
  );
}

MFNode _homeTree() {
  return MFNode(
    id: 'home-page',
    type: 'Stack',
    children: [
      MFNode(
        id: 'home-header',
        type: 'Stack',
        props: const {'direction': 'horizontal', 'align': 'space-between', 'crossAlign': 'center'},
        children: [
          MFNode(id: 'home-title', type: 'Text', t: 'app.home.title'),
          MFNode(
            id: 'home-nav',
            type: 'Stack',
            props: const {'direction': 'horizontal'},
            children: [_button('home-open-cart', '购物车'), _button('home-open-orders', '我的订单')],
          ),
        ],
      ),
      MFNode(
        id: 'home-search',
        type: 'Stack',
        props: const {'direction': 'horizontal', 'crossAlign': 'center'},
        children: [
          MFNode(
            id: 'home-search-input',
            type: 'Input',
            props: const {'placeholder': '搜索商品', 'value': ''},
            constraints: const MFSelfConstraint(width: 'fill'),
          ),
          const MFNode(id: 'home-search-go', type: 'Button', props: {'label': '搜索', 'variant': 'primary'}),
        ],
      ),
      MFNode(id: 'home-hint', type: 'Text', props: {'text': {'ref': 'state.cartHint'}}),
      MFNode(id: 'home-empty', type: 'Text', props: {'text': {'ref': 'state.emptyText'}}),
      MFNode(
        id: 'home-list',
        type: 'List',
        props: {'items': {'ref': 'state.productItems'}},
        children: [
          MFNode(
            id: 'home-row',
            type: 'Stack',
            props: const {'direction': 'horizontal', 'crossAlign': 'center'},
            children: [
              MFNode(
                id: 'home-row-title',
                type: 'Text',
                props: {'text': {'ref': 'item.title'}},
                constraints: const MFSelfConstraint(width: 'fill'),
              ),
              MFNode(id: 'home-row-price', type: 'Text', props: {'text': {'ref': 'item.priceText'}}),
              MFNode(
                id: 'home-row-add',
                type: 'Button',
                props: {'label': {'ref': 'item.actionLabel'}, 'variant': 'primary'},
              ),
            ],
          ),
        ],
      ),
    ],
  );
}

MFNode _cartTree() {
  return MFNode(
    id: 'cart-page',
    type: 'Stack',
    children: [
      MFNode(
        id: 'cart-header',
        type: 'Stack',
        props: const {'direction': 'horizontal', 'align': 'space-between', 'crossAlign': 'center'},
        children: [
          MFNode(id: 'cart-title', type: 'Text', t: 'app.cart.title'),
          _button('cart-open-orders', '我的订单'),
        ],
      ),
      MFNode(id: 'cart-empty', type: 'Text', props: {'text': {'ref': 'state.emptyText'}}),
      MFNode(
        id: 'cart-list',
        type: 'List',
        props: {'items': {'ref': 'state.cartItems'}},
        children: [
          MFNode(id: 'cart-row', type: 'Text', props: {'text': {'ref': 'item.lineText'}}),
        ],
      ),
      MFNode(id: 'cart-total', type: 'Text', props: {'text': {'ref': 'state.totalText'}}),
      MFNode(
        id: 'cart-actions',
        type: 'Stack',
        props: const {'direction': 'horizontal'},
        children: [
          const MFNode(id: 'cart-submit', type: 'Button', props: {'label': '提交订单', 'variant': 'primary'}),
        ],
      ),
      MFNode(id: 'cart-order', type: 'Text', props: {'text': {'ref': 'state.orderText'}}),
    ],
  );
}

MFNode _ordersTree() {
  return MFNode(
    id: 'orders-page',
    type: 'Stack',
    children: [
      MFNode(
        id: 'orders-header',
        type: 'Stack',
        props: const {'direction': 'horizontal', 'align': 'space-between', 'crossAlign': 'center'},
        children: [
          MFNode(id: 'orders-title', type: 'Text', t: 'app.orders.title'),
          _button('orders-open-home', '回首页'),
        ],
      ),
      MFNode(id: 'orders-gmv', type: 'Text', props: {'text': {'ref': 'state.gmvText'}}),
      MFNode(id: 'orders-empty', type: 'Text', props: {'text': {'ref': 'state.emptyText'}}),
      MFNode(
        id: 'orders-list',
        type: 'List',
        props: {'items': {'ref': 'state.orderItems'}},
        children: [
          MFNode(id: 'orders-row', type: 'Text', props: {'text': {'ref': 'item.rowText'}}),
        ],
      ),
    ],
  );
}

List<MFBinding> get _homeBindings => [
      MFBinding(
        id: 'home-enter',
        on: 'home-page.onEnter',
        actions: [
          // 首动作为异步调用：同步状态写入安排在其后，避免页面打开
          // （构建期）同步触发状态代际通知（§39 锚点执行时序）。
          MFAdapterAction(kind: 'function', call: 'fn.trading.search',
              arguments: {'keyword': MFLiteral('')}, as: 'load'),
          MFStateAction(target: 'keyword', value: MFLiteral('')),
          MFStateAction(target: 'cartHint', value: MFLiteral('')),
          MFStateAction(target: 'productItems', value: MFRef('prev.load.products')),
          MFStateAction(target: 'emptyText', value: MFRef('prev.load.emptyText')),
        ],
        policy: MFPolicy.rejectNew,
      ),
      MFBinding(
        id: 'home-search-input',
        on: 'home-search-input.change',
        actions: [MFStateAction(target: 'keyword', value: MFRef('prop.value'))],
        policy: MFPolicy.rejectNew,
      ),
      MFBinding(
        id: 'home-search',
        on: 'home-search-go.press',
        actions: [
          MFAdapterAction(kind: 'function', call: 'fn.trading.search',
              arguments: {'keyword': MFRef('state.keyword')}, as: 'load'),
          MFStateAction(target: 'productItems', value: MFRef('prev.load.products')),
          MFStateAction(target: 'emptyText', value: MFRef('prev.load.emptyText')),
        ],
        policy: MFPolicy.rejectNew,
      ),
      MFBinding(
        id: 'home-row-add',
        on: 'home-row-add.press',
        actions: [
          MFAdapterAction(
            kind: 'adapter',
            call: 'adapter.trading.add_cart',
            arguments: {'sku': MFRef('item.sku'), 'title': MFRef('item.title'),
                'unitPrice': MFRef('item.unitPrice')},
            as: 'added',
          ),
          MFStateAction(target: 'cartHint', value: MFRef('prev.added.hint')),
        ],
        policy: MFPolicy.rejectNew,
      ),
    ];

List<MFBinding> get _cartBindings => [
      MFBinding(
        id: 'cart-enter',
        on: 'cart-page.onEnter',
        actions: [
          MFAdapterAction(kind: 'function', call: 'fn.trading.cart', as: 'cart'),
          MFStateAction(target: 'orderText', value: MFLiteral('')),
          MFStateAction(target: 'cartItems', value: MFRef('prev.cart.items')),
          MFStateAction(target: 'totalText', value: MFRef('prev.cart.totalText')),
          MFStateAction(target: 'emptyText', value: MFRef('prev.cart.emptyText')),
        ],
        policy: MFPolicy.rejectNew,
      ),
      MFBinding(
        id: 'cart-submit',
        on: 'cart-submit.press',
        actions: [
          MFAdapterAction(kind: 'adapter', call: 'adapter.trading.place_order',
              arguments: {'buyerId': MFLiteral('buyer-web-001'), 'vip': MFLiteral(true)},
              as: 'order'),
          MFStateAction(target: 'orderText', value: MFRef('prev.order.orderText')),
        ],
        policy: MFPolicy.rejectNew,
      ),
    ];

List<MFBinding> get _navBindings => [
      MFBinding(
        id: 'home-open-cart',
        on: 'home-open-cart.press',
        actions: [MFNavigationAction(target: 'cart-page')],
        policy: MFPolicy.rejectNew,
      ),
      MFBinding(
        id: 'home-open-orders',
        on: 'home-open-orders.press',
        actions: [MFNavigationAction(target: 'orders-page')],
        policy: MFPolicy.rejectNew,
      ),
      MFBinding(
        id: 'cart-open-orders',
        on: 'cart-open-orders.press',
        actions: [MFNavigationAction(target: 'orders-page')],
        policy: MFPolicy.rejectNew,
      ),
    ];

List<MFBinding> get _ordersBindings => [
      MFBinding(
        id: 'orders-enter',
        on: 'orders-page.onEnter',
        actions: [
          MFAdapterAction(kind: 'function', call: 'fn.trading.orders', as: 'orders'),
          MFStateAction(target: 'orderItems', value: MFRef('prev.orders.items')),
          MFStateAction(target: 'gmvText', value: MFRef('prev.orders.gmvText')),
          MFStateAction(target: 'emptyText', value: MFRef('prev.orders.emptyText')),
        ],
        policy: MFPolicy.rejectNew,
      ),
      MFBinding(
        id: 'orders-open-home',
        on: 'orders-open-home.press',
        actions: [MFNavigationAction(target: 'home-page')],
        policy: MFPolicy.rejectNew,
      ),
    ];
