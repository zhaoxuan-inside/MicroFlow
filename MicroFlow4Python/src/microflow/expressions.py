"""Restricted JSON condition AST; business computation belongs in operators."""
from collections.abc import Mapping
from .errors import ContractError
from .paths import get, parse
from .values import MISSING, canonical, validate_value


def check(expression):
    validate_value(expression)
    if not isinstance(expression, Mapping) or len(expression) != 1:
        raise ContractError("INVALID_CONDITION", "Condition must contain one operation")
    op, args = next(iter(expression.items()))
    if op in ("and", "or"):
        if not isinstance(args, (list, tuple)) or not args:
            raise ContractError("INVALID_CONDITION", "Boolean operation needs nonempty operands")
        for arg in args:
            check(arg)
    elif op == "not":
        check(args)
    elif op == "exists":
        parse(args)
    elif op in ("eq", "ne", "lt", "lte", "gt", "gte", "in"):
        if not isinstance(args, (tuple, list)) or len(args) != 2:
            raise ContractError("INVALID_CONDITION", "Comparison needs two operands")
        for arg in args:
            if isinstance(arg, Mapping):
                if set(arg) != {"path"}:
                    raise ContractError("INVALID_CONDITION", "Use path operands or JSON scalar/list literals")
                parse(arg["path"])
    else:
        raise ContractError("INVALID_CONDITION", "Unknown condition operation", op)


def evaluate(expression, sources):
    op, args = next(iter(expression.items()))
    if op == "and":
        return all(evaluate(a, sources) for a in args)
    if op == "or":
        return any(evaluate(a, sources) for a in args)
    if op == "not":
        return not evaluate(args, sources)
    if op == "exists":
        return get(sources, args) is not MISSING
    left, right = [get(sources, a["path"]) if isinstance(a, Mapping) else a for a in args]
    if left is MISSING or right is MISSING:
        raise ContractError("MISSING_CONDITION_VALUE", "Comparison operand is missing")
    if op == "eq":
        return canonical(left) == canonical(right)
    if op == "ne":
        return canonical(left) != canonical(right)
    if op == "in":
        if not isinstance(right, (tuple, list)):
            raise ContractError("CONDITION_TYPE_MISMATCH", "in requires an array")
        return canonical(left) in [canonical(v) for v in right]
    if type(left) is not type(right) or type(left) not in (str, int, float):
        raise ContractError("CONDITION_TYPE_MISMATCH", "Ordered operands must have the same numeric/string type")
    return {"lt": lambda: left < right, "lte": lambda: left <= right,
            "gt": lambda: left > right, "gte": lambda: left >= right}[op]()


def paths(expression):
    if isinstance(expression, Mapping):
        for k, v in expression.items():
            if k in ("path", "exists"):
                yield v
            else:
                yield from paths(v)
    elif isinstance(expression, (list, tuple)):
        for item in expression:
            yield from paths(item)
