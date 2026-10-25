/// 资源注册面（§23 统一资源注册）：Tier A 元组件契约 + 交易平台业务资源。
///
/// 渲染发生在解释器 primitive table（§38.1）；注册供静态校验、事件锚点
/// （§39）与载荷契约检查（§5）使用。业务函数/适配器（§10/§40）的语义与
/// 后端 examples/trading 编排流程对齐；下单/加购触点以采集注记（§24.7）
/// 声明运营事件，运行时零埋点发射，业务代码不做手工上报。
library;

import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'trading_data.dart';

MFRegistry buildTradingRegistry({LocalTradingData? data}) {
  final trading = data ?? LocalTradingData();
  final registry = MFRegistry();
  for (final id in MFTierA.required) {
    registry.register(
      'primitive',
      id,
      ComponentContract(
        props: switch (id) {
          'Text' => {'text': const TString()},
          'Button' => {
              'label': const TString(),
              'variant': const TEnum(['primary', 'secondary', 'danger']),
            },
          'Input' => {
              'placeholder': const TString(),
              'value': const TString(),
              'readOnly': const TBool(),
            },
          'Icon' => {'name': const TString(), 'size': const TNumber(), 'color': const TString()},
          'Image' => {'src': const TString()},
          'Checkbox' => {'value': const TBool()},
          'Select' => {'label': const TString(), 'options': const TList(), 'value': const TString()},
          'Modal' => {'background': const TString()},
          _ => const {},
        },
        events: switch (id) {
          'Button' => {'press': const TString()},
          'Input' => {'change': const TString()},
          'Checkbox' => {'change': const TBool()},
          'Select' => {'change': const TString()},
          'Stack' => const {'press': TString(), 'onEnter': TBool()},
          _ => const {},
        },
        states: switch (id) {
          'Button' => const ['enabled', 'disabled', 'busy'],
          _ => const [],
        },
        slots: const ['content'],
        layout: const LayoutCapability(
          display: ['block', 'inline'],
          sizing: ['hug', 'fill', 'fixed'],
        ),
      ),
      MFHostComponentImpl((children, props) => Object()),
      description: 'Tier A 元组件（§38.1）：渲染由解释器 primitive table 承载',
    );
  }

  registry.register(
    'function',
    'fn.trading.search',
    const ComponentContract(props: {
      'output': TObject(requiredKeys: ['products', 'emptyText']),
    }),
    MFFunctionImpl((args) async => trading.search(args['keyword']), timeoutMs: 3000),
    description: '按关键字检索商品目录（演示数据；生产经 T14 控制面调用后端 browse 流程）',
  );
  registry.register(
    'function',
    'fn.trading.cart',
    const ComponentContract(props: {
      'output': TObject(requiredKeys: ['items', 'totalText', 'emptyText']),
    }),
    MFFunctionImpl((args) async => trading.cart(), timeoutMs: 3000),
    description: '读取购物车明细与合计',
  );
  registry.register(
    'function',
    'fn.trading.orders',
    const ComponentContract(props: {
      'output': TObject(requiredKeys: ['items', 'gmvText', 'emptyText']),
    }),
    MFFunctionImpl((args) async => trading.orders(), timeoutMs: 3000),
    description: '读取订单列表与成交金额汇总（运营数据面）',
  );
  registry.register(
    'adapter',
    'adapter.trading.add_cart',
    const ComponentContract(props: {
      'output': TObject(requiredKeys: ['cartCount', 'hint']),
    }, telemetry: MFTelemetryAnnotation(
      events: {'success': 'ops.trade.added-to-cart'},
      args: ['sku'],
    )),
    MFAdapterImpl((args) async => trading.addCart(
          args['sku'],
          args['title'],
          args['unitPrice'],
        ), timeoutMs: 3000),
    description: '加入购物车；触点采集注记 ops.trade.added-to-cart',
  );
  registry.register(
    'adapter',
    'adapter.trading.place_order',
    const ComponentContract(props: {
      'output': TObject(requiredKeys: ['orderId', 'status', 'orderText']),
    }, telemetry: MFTelemetryAnnotation(
      events: {'success': 'ops.trade.order-placed'},
      args: ['orderId', 'status'],
    )),
    MFAdapterImpl((args) async => trading.placeOrder(
          args['buyerId'] ?? 'buyer-web-001',
          args['vip'] ?? true,
        ), timeoutMs: 3000),
    description: '下单合成订单（业务语义对齐后端 place_order 流程）；触点注记 ops.trade.order-placed',
  );
  return registry;
}
