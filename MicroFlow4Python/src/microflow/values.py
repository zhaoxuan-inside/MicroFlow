"""Strict JSON values, immutable views and versioned canonical digests."""
import hashlib
import json
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .errors import ContractError


class _Missing:
    def __repr__(self):
        return "MISSING"


MISSING = _Missing()


def thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def validate_value(value: Any, *, max_depth: int = 64, max_items: int = 100_000) -> None:
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > max_items or depth > max_depth:
            raise ContractError("VALUE_LIMIT", "Value exceeds depth or item budget")
        if isinstance(item, Mapping):
            if any(type(k) is not str for k in item):
                raise ContractError("INVALID_VALUE", "Map keys must be strings")
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend((v, depth + 1) for v in item)
        elif type(item) is float:
            if not math.isfinite(item):
                raise ContractError("INVALID_VALUE", "Non-finite numbers are forbidden")
        elif item is not None and type(item) not in (str, bool, int):
            raise ContractError("INVALID_VALUE", f"Unsupported type: {type(item).__name__}")


def canonical(value: Any) -> bytes:
    validate_value(value)

    def tree(v):
        if v is None:
            return ["null"]
        if type(v) is bool:
            return ["bool", v]
        if type(v) is int:
            return ["int", str(v)]
        if type(v) is float:
            return ["float", v.hex()]
        if type(v) is str:
            return ["str", v]
        if isinstance(v, Mapping):
            return ["map", [[k, tree(v[k])] for k in sorted(v)]]
        return ["list", [tree(x) for x in v]]

    return json.dumps(["microflow-canonical-v1", tree(value)], ensure_ascii=True,
                      separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def load_json(text: str, *, max_bytes: int = 4_194_304) -> Any:
    if len(text.encode("utf-8")) > max_bytes:
        raise ContractError("CONFIG_LIMIT", "Configuration exceeds byte budget")

    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ContractError("DUPLICATE_KEY", "Duplicate JSON key", k)
            result[k] = v
        return result

    def constant(v):
        raise ContractError("INVALID_VALUE", f"Non-finite JSON constant: {v}")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise ContractError("INVALID_JSON", "Invalid JSON syntax", line=exc.lineno, column=exc.colno) from exc
    except (ValueError, RecursionError) as exc:
        raise ContractError("INVALID_JSON", "Invalid or excessively nested JSON") from exc
    validate_value(value)
    return value
