"""A pure calculation example. It performs no external operations."""


def calculate(input, output, context, metrix, debug, log):
    output.set("total", sum(item["price"] * item["quantity"] for item in input["items"]))
    return True


def register(registry):
    registry.register_schema("quote.input@1", {
        "type": "object", "properties": {"items": {"type": "array", "items": {
            "type": "object", "properties": {"price": {"type": "integer", "minimum": 0},
                                             "quantity": {"type": "integer", "minimum": 1}},
            "required": ["price", "quantity"]}}}, "required": ["items"]})
    registry.register_schema("quote.output@1", {"type": "object", "properties": {
        "total": {"type": "integer", "minimum": 0}}, "required": ["total"]})
    registry.register_operator(name="quote.calculate", version="1", method=calculate,
                               input_schema="quote.input@1", output_schema="quote.output@1")
