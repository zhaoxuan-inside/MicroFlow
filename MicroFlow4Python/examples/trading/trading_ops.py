"""Trading platform demo operators — all pure/read computations, money in integer cents.

Demo data (catalog and stock) lives inside the operators; a real deployment
resolves external resources through host-injected providers instead. ZCode
builds and verifies this platform through the framework CLI:
`microflow check / operators / schema / impact / run` (see README).
"""


def _product(sku, title, unit_price):
    return {"sku": sku, "title": title, "unitPrice": unit_price}


CATALOG = [
    _product("MI-14", "手机 Pro 14", 499900),
    _product("MI-14E", "手机 14e", 199900),
    _product("PAD-11", "平板 11", 259900),
    _product("WATCH-S3", "手表 S3", 99900),
    _product("BUDGETS-2", "耳机 2", 49900),
]

STOCK = {"MI-14": 3, "MI-14E": 10, "PAD-11": 0, "WATCH-S3": 5, "BUDGETS-2": 1}


def search(input, output, context, metrix, debug, log):
    keyword = input["keyword"]
    hits = [p for p in CATALOG if keyword in p["title"] or keyword in p["sku"]]
    output.set("products", hits)
    return True


def cart_total(input, output, context, metrix, debug, log):
    output.set("total", sum(item["quantity"] * item["unitPrice"] for item in input["items"]))
    return True


def discount(input, output, context, metrix, debug, log):
    total = input["total"]
    payable = total * 95 // 100 if input["vip"] else total
    output.set("payable", payable)
    output.set("saved", total - payable)
    return True


def inventory_check(input, output, context, metrix, debug, log):
    shortages = []
    for item in input["items"]:
        stock = STOCK.get(item["sku"], 0)
        if stock < item["quantity"]:
            shortages.append({"sku": item["sku"], "requested": item["quantity"], "stock": stock})
    output.set("shortages", shortages)
    output.set("available", not shortages)
    return True


def compose_order(input, output, context, metrix, debug, log):
    import hashlib
    import json

    buyer = input["buyer"]
    items = input["items"]
    digest = hashlib.sha256(json.dumps(
        [buyer["id"], [(i["sku"], i["quantity"]) for i in items]], sort_keys=True,
    ).encode("utf-8")).hexdigest()[:12]
    available = input["available"]
    output.set("order", {
        "orderId": f"SO-{digest}",
        "buyerId": buyer["id"],
        "items": items,
        "payable": input["payable"],
        "status": "CREATED" if available else "BLOCKED",
    })
    return True


def register(registry):
    item_schema = {"type": "object",
                   "properties": {"sku": {"type": "string"},
                                  "quantity": {"type": "integer", "minimum": 1},
                                  "unitPrice": {"type": "integer", "minimum": 0}},
                   "required": ["sku", "quantity", "unitPrice"]}
    product_schema = {"type": "object",
                      "properties": {"sku": {"type": "string"}, "title": {"type": "string"},
                                     "unitPrice": {"type": "integer", "minimum": 0}},
                      "required": ["sku", "title", "unitPrice"]}
    buyer_schema = {"type": "object",
                    "properties": {"id": {"type": "string"}, "vip": {"type": "boolean"}},
                    "required": ["id", "vip"]}
    registry.register_schema("trading.product@1", product_schema)
    registry.register_schema("trading.item@1", item_schema)
    registry.register_schema("trading.buyer@1", buyer_schema)
    registry.register_schema("trading.browse.input@1", {
        "type": "object", "properties": {"keyword": {"type": "string", "minLength": 1}},
        "required": ["keyword"],
    })
    registry.register_schema("trading.browse.output@1", {
        "type": "object",
        "properties": {"products": {"type": "array", "items": product_schema}},
        "required": ["products"],
    })
    registry.register_schema("trading.pricing.pass@1", {
        "type": "object",
        "properties": {"items": {"type": "array", "items": item_schema}, "vip": {"type": "boolean"}},
        "required": ["items", "vip"],
    })
    registry.register_schema("trading.cart.total@1", {
        "type": "object", "properties": {"total": {"type": "integer", "minimum": 0}},
        "required": ["total"],
    })
    registry.register_schema("trading.discount.pass@1", {
        "type": "object",
        "properties": {"total": {"type": "integer", "minimum": 0}, "vip": {"type": "boolean"}},
        "required": ["total", "vip"],
    })
    registry.register_schema("trading.discount.result@1", {
        "type": "object",
        "properties": {"payable": {"type": "integer", "minimum": 0},
                       "saved": {"type": "integer", "minimum": 0}},
        "required": ["payable", "saved"],
    })
    registry.register_schema("trading.pricing.result@1", {
        "type": "object",
        "properties": {"total": {"type": "integer", "minimum": 0},
                       "payable": {"type": "integer", "minimum": 0},
                       "saved": {"type": "integer", "minimum": 0}},
        "required": ["total", "payable", "saved"],
    })
    registry.register_schema("trading.order.request@1", {
        "type": "object",
        "properties": {"buyer": buyer_schema, "items": {"type": "array", "items": item_schema}},
        "required": ["buyer", "items"],
    })
    registry.register_schema("trading.inventory.result@1", {
        "type": "object",
        "properties": {"available": {"type": "boolean"},
                       "shortages": {"type": "array", "items": {
                           "type": "object",
                           "properties": {"sku": {"type": "string"},
                                          "requested": {"type": "integer", "minimum": 1},
                                          "stock": {"type": "integer", "minimum": 0}},
                           "required": ["sku", "requested", "stock"]}}},
        "required": ["available", "shortages"],
    })
    registry.register_schema("trading.compose.pass@1", {
        "type": "object",
        "properties": {"buyer": buyer_schema, "items": {"type": "array", "items": item_schema},
                       "payable": {"type": "integer", "minimum": 0},
                       "available": {"type": "boolean"}},
        "required": ["buyer", "items", "payable", "available"],
    })
    order_schema = {
        "type": "object",
        "properties": {"orderId": {"type": "string"}, "buyerId": {"type": "string"},
                       "items": {"type": "array", "items": item_schema},
                       "payable": {"type": "integer", "minimum": 0},
                       "status": {"type": "string", "enum": ["CREATED", "BLOCKED"]}},
        "required": ["orderId", "buyerId", "items", "payable", "status"],
    }
    registry.register_schema("trading.order@1", order_schema)
    registry.register_schema("trading.order.output@1", {
        "type": "object", "properties": {"order": order_schema},
        "required": ["order"],
    })
    registry.register_operator(
        name="trading.catalog_search", version="1", method=search,
        input_schema="trading.browse.input@1", output_schema="trading.browse.output@1",
        capabilities={"effect": "read", "idempotency_support": "natural"},
        description="按关键字检索在售商品目录（演示数据内置于算子）",
    )
    registry.register_operator(
        name="trading.cart_total", version="1", method=cart_total,
        input_schema="trading.pricing.pass@1", output_schema="trading.cart.total@1",
        capabilities={"effect": "pure", "idempotency_support": "natural"},
        description="按明细行小计购物车总额",
    )
    registry.register_operator(
        name="trading.pricing_discount", version="1", method=discount,
        input_schema="trading.discount.pass@1", output_schema="trading.discount.result@1",
        capabilities={"effect": "pure", "idempotency_support": "natural"},
        description="会员折扣：vip 按 95/100 整数折算，输出应付与已省金额",
    )
    registry.register_operator(
        name="trading.inventory_check", version="1", method=inventory_check,
        input_schema="trading.order.request@1", output_schema="trading.inventory.result@1",
        capabilities={"effect": "read", "idempotency_support": "natural"},
        description="按库存演示数据校验每个明细行的可满足性，输出短缺清单",
    )
    registry.register_operator(
        name="trading.order_compose", version="1", method=compose_order,
        input_schema="trading.compose.pass@1", output_schema="trading.order.output@1",
        capabilities={"effect": "pure", "idempotency_support": "natural"},
        description="合成订单：确定性 orderId（输入摘要派生），缺货置 BLOCKED",
    )
