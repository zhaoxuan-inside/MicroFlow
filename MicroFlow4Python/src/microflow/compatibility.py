"""Conservative Schema v1 path and compatibility proofs for the compiler."""
from .errors import ContractError
from .paths import Field, Index
from .values import canonical

PROVED_COMPATIBLE = "PROVED_COMPATIBLE"
PROVED_INCOMPATIBLE = "PROVED_INCOMPATIBLE"
UNKNOWN = "UNKNOWN"


def schema_at(schema, tokens, location):
    for token in tokens:
        if isinstance(token, Field) and schema["type"] == "object":
            child = schema.get("properties", {}).get(token.name)
            if child is None:
                if schema.get("additionalProperties", False):
                    return None
                raise ContractError("UNKNOWN_SCHEMA_PATH", "Path refers to an undeclared field", location)
            schema = child
        elif isinstance(token, Index) and schema["type"] == "array":
            schema = schema["items"]
        else:
            raise ContractError("SCHEMA_PATH_TYPE_MISMATCH", "Path crosses an incompatible container", location)
    return schema


def compatible(source, target):
    if source is None or target is None:
        return UNKNOWN
    if source["type"] != target["type"] and (source["type"], target["type"]) != ("integer", "number"):
        return PROVED_INCOMPATIBLE
    states = []
    for lower, upper in (("minimum", "maximum"), ("minLength", "maxLength"), ("minItems", "maxItems")):
        if lower in target and source.get(lower, float("-inf")) < target[lower]:
            states.append(UNKNOWN)
        if upper in target and source.get(upper, float("inf")) > target[upper]:
            states.append(UNKNOWN)
    if "enum" in target:
        if "enum" not in source:
            states.append(UNKNOWN)
        elif not {canonical(x) for x in source["enum"]} <= {canonical(x) for x in target["enum"]}:
            states.append(UNKNOWN)
    if target["type"] == "array":
        states.append(compatible(source["items"], target["items"]))
    if target["type"] == "object":
        sp, tp = source.get("properties", {}), target.get("properties", {})
        if not set(target.get("required", ())) <= set(source.get("required", ())):
            states.append(UNKNOWN)
        if not target.get("additionalProperties", False) and (source.get("additionalProperties", False) or set(sp) - set(tp)):
            states.append(UNKNOWN)
        states.extend(compatible(sp[name], tp[name]) for name in sp.keys() & tp.keys())
    if PROVED_INCOMPATIBLE in states:
        # Optional fields may not be present; only a runtime check can resolve this.
        return UNKNOWN
    return UNKNOWN if UNKNOWN in states else PROVED_COMPATIBLE
