"""MicroFlow Schema v1, intentionally not a general JSON Schema implementation."""
from collections.abc import Mapping
from .errors import ContractError
from .values import canonical, validate_value

KEYWORDS = {"type", "properties", "required", "additionalProperties", "items", "enum",
            "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems",
            "description", "sensitive", "examples", "version"}
TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


def check_schema(schema: Mapping, path: str = "schema") -> None:
    validate_value(schema)
    if not isinstance(schema, Mapping):
        raise ContractError("INVALID_SCHEMA", "Schema must be an object", path)
    unknown = set(schema) - KEYWORDS
    if unknown:
        raise ContractError("UNKNOWN_SCHEMA_RULE", f"Unknown keywords: {sorted(unknown)}", path)
    if type(schema.get("type")) is not str or schema["type"] not in TYPES:
        raise ContractError("INVALID_SCHEMA", "Exactly one supported type is required", path)
    groups = {"object": {"properties", "required", "additionalProperties"},
              "array": {"items", "minItems", "maxItems"},
              "string": {"minLength", "maxLength"},
              "integer": {"minimum", "maximum"}, "number": {"minimum", "maximum"}}
    typed = set().union(*groups.values())
    if (set(schema) & typed) - groups.get(schema["type"], set()):
        raise ContractError("INVALID_SCHEMA", "Keyword is not applicable to this type", path)
    props = schema.get("properties", {})
    if not isinstance(props, Mapping):
        raise ContractError("INVALID_SCHEMA", "properties must be an object", path)
    for name, child in props.items():
        check_schema(child, f"{path}.properties.{name}")
    required = schema.get("required", [])
    if not isinstance(required, (list, tuple)) or any(type(x) is not str or x not in props for x in required):
        raise ContractError("INVALID_SCHEMA", "required must name declared properties", path)
    if len(set(required)) != len(required):
        raise ContractError("INVALID_SCHEMA", "required fields must be unique", path)
    if type(schema.get("additionalProperties", False)) is not bool:
        raise ContractError("INVALID_SCHEMA", "additionalProperties must be boolean", path)
    if schema["type"] == "array":
        if "items" not in schema:
            raise ContractError("INVALID_SCHEMA", "Array items schema is required", path)
        check_schema(schema["items"], f"{path}.items")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            raise ContractError("INVALID_SCHEMA", f"{key} must be a nonnegative integer", path)
    for key in ("minimum", "maximum"):
        if key in schema and type(schema[key]) not in (int, float):
            raise ContractError("INVALID_SCHEMA", f"{key} must be numeric", path)
    for lower, upper in (("minimum", "maximum"), ("minLength", "maxLength"), ("minItems", "maxItems")):
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            raise ContractError("INVALID_SCHEMA", "Contradictory bounds", path)
    if "enum" in schema and (not isinstance(schema["enum"], (tuple, list)) or not schema["enum"]):
        raise ContractError("INVALID_SCHEMA", "enum must be a nonempty array", path)
    validate_value(schema)


def validate(value, schema: Mapping, path: str = "data") -> None:
    check_schema(schema)
    validate_value(value)

    def visit(v, s, p):
        kind = s["type"]
        valid = {"object": isinstance(v, Mapping), "array": isinstance(v, (list, tuple)),
                 "string": type(v) is str, "integer": type(v) is int,
                 "number": type(v) in (int, float), "boolean": type(v) is bool,
                 "null": v is None}[kind]
        if not valid:
            raise ContractError("SCHEMA_VIOLATION", f"Expected {kind}; got {type(v).__name__}", p)
        if "enum" in s and canonical(v) not in [canonical(x) for x in s["enum"]]:
            raise ContractError("SCHEMA_VIOLATION", "Value outside enum", p)
        if kind == "object":
            props = s.get("properties", {})
            for name in s.get("required", []):
                if name not in v:
                    raise ContractError("SCHEMA_VIOLATION", "Required field missing", f"{p}.{name}")
            for name, child in v.items():
                if name not in props:
                    if not s.get("additionalProperties", False):
                        raise ContractError("SCHEMA_VIOLATION", "Undeclared field", f"{p}.{name}")
                else:
                    visit(child, props[name], f"{p}.{name}")
        if kind == "array":
            for i, child in enumerate(v):
                visit(child, s["items"], f"{p}[{i}]")
        bounds = {"string": ("minLength", "maxLength"), "array": ("minItems", "maxItems")}
        if kind in bounds:
            lower, upper = bounds[kind]
            if len(v) < s.get(lower, 0) or len(v) > s.get(upper, float("inf")):
                raise ContractError("SCHEMA_VIOLATION", "Length outside bounds", p)
        if kind in ("integer", "number") and (v < s.get("minimum", float("-inf")) or v > s.get("maximum", float("inf"))):
            raise ContractError("SCHEMA_VIOLATION", "Number outside bounds", p)

    visit(value, schema, path)
