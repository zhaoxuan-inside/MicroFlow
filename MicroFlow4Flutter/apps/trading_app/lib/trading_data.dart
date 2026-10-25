/// 交易平台本地业务数据（§40 适配器的演示实现）。
///
/// 业务语义与后端 `MicroFlow4Python/examples/trading` 的编排流程对齐：
/// 金额用整数分，会员按 95/100 整数折算，订单状态 CREATED/BLOCKED。
/// 本地实现只为前端演示闭环；生产部署中适配器经 T14 控制面调用后端
/// 耐久执行接口，本文件不进入生产路径。
library;

class LocalTradingData {
  final List<Map<String, Object?>> _cart = [];
  final List<Map<String, Object?>> _orders = [];
  int _seq = 0;

  static const List<Map<String, Object?>> catalog = [
    {'sku': 'MI-14', 'title': '手机 Pro 14', 'unitPrice': 499900},
    {'sku': 'MI-14E', 'title': '手机 14e', 'unitPrice': 199900},
    {'sku': 'PAD-11', 'title': '平板 11', 'unitPrice': 259900},
    {'sku': 'WATCH-S3', 'title': '手表 S3', 'unitPrice': 99900},
    {'sku': 'BUDGETS-2', 'title': '耳机 2', 'unitPrice': 49900},
  ];

  static String _yuan(Object? cents) => '¥${((cents as int) / 100).toStringAsFixed(2)}';

  Map<String, Object?> search(Object? keyword) {
    final kw = '$keyword';
    final products = [
      for (final p in catalog)
        if (kw.isEmpty ||
            (p['title'] as String).contains(kw) ||
            (p['sku'] as String).contains(kw))
          {
            ...p,
            'priceText': _yuan(p['unitPrice']),
            'actionLabel': '加入购物车',
          },
    ];
    return {'products': products, 'emptyText': products.isEmpty ? '没有匹配的商品' : ''};
  }

  Map<String, Object?> addCart(Object? sku, Object? title, Object? unitPrice) {
    _cart.add({'sku': '$sku', 'title': '$title', 'unitPrice': unitPrice, 'quantity': 1});
    return {'cartCount': _cart.length, 'hint': '已加入购物车，共 ${_cart.length} 件'};
  }

  Map<String, Object?> cart() {
    final items = [
      for (final line in _cart)
        {
          ...line,
          'lineText': '${line['title']} ×${line['quantity']}  ${_yuan(line['unitPrice'])}',
        },
    ];
    final total = _cart.fold<int>(0, (sum, line) => sum + (line['unitPrice'] as int));
    return {
      'items': items,
      'totalText': '合计 ${_yuan(total)}',
      'emptyText': _cart.isEmpty ? '购物车是空的，回首页逛逛吧' : '',
    };
  }

  Map<String, Object?> placeOrder(Object? buyerId, Object? vip) {
    if (_cart.isEmpty) {
      return {'orderId': '', 'status': 'EMPTY', 'orderText': '购物车为空，无法下单'};
    }
    final total = _cart.fold<int>(0, (sum, line) => sum + (line['unitPrice'] as int));
    final payable = vip == true ? total * 95 ~/ 100 : total;
    final order = {
      'orderId': 'SO-W-${++_seq}',
      'buyerId': '$buyerId',
      'payable': payable,
      'status': 'CREATED',
    };
    _orders.add(order);
    _cart.clear();
    return {
      'orderId': order['orderId'],
      'status': order['status'],
      'orderText': '订单 ${order['orderId']} 已创建，应付 ${_yuan(payable)}',
    };
  }

  Map<String, Object?> orders() {
    final items = [
      for (final o in _orders)
        {'rowText': '${o['orderId']}  ${o['status']}  ${_yuan(o['payable'])}'},
    ];
    final gmv = _orders.fold<int>(0, (sum, o) => sum + (o['payable'] as int));
    return {
      'items': items,
      'gmvText': '成交金额 ${_yuan(gmv)}（${_orders.length} 单）',
      'emptyText': _orders.isEmpty ? '还没有订单' : '',
    };
  }
}
