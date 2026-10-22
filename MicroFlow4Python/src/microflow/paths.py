"""Field/index paths. No eval, Python attributes, wildcards or negative indices."""
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ContractError
from .values import MISSING, thaw


@dataclass(frozen=True)
class Field:
    name: str


@dataclass(frozen=True)
class Index:
    value: int


def parse(path: str) -> tuple[Field | Index, ...]:
    if not isinstance(path, str) or not path or len(path) > 4096:
        raise ContractError("INVALID_PATH", "Expected a nonempty bounded path")
    result = []
    pos = 0
    need_field = True
    decoder = json.JSONDecoder()
    while pos < len(path):
        if path[pos] == "[":
            if result and need_field:
                raise ContractError("INVALID_PATH", "Bracket cannot follow a dot", path)
            pos += 1
            if pos < len(path) and path[pos] == '"':
                try:
                    key, size = decoder.raw_decode(path[pos:])
                except ValueError as exc:
                    raise ContractError("INVALID_PATH", "Invalid quoted field", path) from exc
                token = Field(key)
                pos += size
            else:
                match = re.match(r"0|[1-9][0-9]*", path[pos:])
                if not match or not result or need_field:
                    raise ContractError("INVALID_PATH", "Invalid list index", path)
                token = Index(int(match[0]))
                pos += len(match[0])
            if pos >= len(path) or path[pos] != "]":
                raise ContractError("INVALID_PATH", "Unclosed bracket", path)
            result.append(token)
            pos += 1
        elif need_field:
            match = re.match(r"[A-Za-z_][A-Za-z_0-9-]*", path[pos:])
            if not match:
                raise ContractError("INVALID_PATH", "Invalid field", path)
            result.append(Field(match[0]))
            pos += len(match[0])
        else:
            raise ContractError("INVALID_PATH", "Expected dot or bracket", path)
        need_field = False
        if pos < len(path) and path[pos] == ".":
            pos += 1
            need_field = True
            if pos == len(path):
                raise ContractError("INVALID_PATH", "Trailing dot", path)
    return tuple(result)


def get(value: Any, path: str | tuple, default: Any = MISSING) -> Any:
    for token in parse(path) if isinstance(path, str) else path:
        if isinstance(token, Field):
            if not isinstance(value, Mapping) or token.name not in value:
                return default
            value = value[token.name]
        else:
            if not isinstance(value, (tuple, list)) or token.value >= len(value):
                return default
            value = value[token.value]
    return value


def set_value(target: dict, path: str | tuple, value: Any) -> None:
    tokens = parse(path) if isinstance(path, str) else path
    current = target
    for i, token in enumerate(tokens):
        last = i == len(tokens) - 1
        if isinstance(token, Field) and isinstance(current, dict):
            key = token.name
            if last:
                if key in current:
                    raise ContractError("MAPPING_CONFLICT", "Target already assigned", str(path))
                current[key] = thaw(value)
            else:
                if key not in current:
                    if isinstance(tokens[i + 1], Index):
                        raise ContractError("SPARSE_ARRAY", "Array must already exist", str(path))
                    current[key] = {}
                current = current[key]
        elif isinstance(token, Index) and isinstance(current, list) and token.value < len(current):
            if last:
                current[token.value] = thaw(value)
            else:
                current = current[token.value]
        else:
            raise ContractError("PATH_TYPE_MISMATCH", "Path does not match target", str(path))


def map_values(rules: Mapping, sources: Mapping) -> dict:
    check_rules(rules)
    candidate: dict = {}
    for target, rule in rules.items():
        value = get(sources, rule["from"])
        if value is MISSING and rule.get("required", False):
            raise ContractError("MISSING_DEPENDENCY_RESULT", "Required source is missing", rule["from"])
        if value is MISSING or (value is None and rule.get("default_on_null", False)):
            if "default" in rule:
                value = rule["default"]
            elif rule.get("required", False):
                raise ContractError("MISSING_DEPENDENCY_RESULT", "Required source is missing", rule["from"])
        if value is not MISSING:
            set_value(candidate, target, value)
    return candidate


def check_rules(rules: Mapping) -> None:
    """Check all destinations before reading any source or publishing a value."""
    if not isinstance(rules, Mapping):
        raise ContractError("INVALID_MAPPING", "Expected mapping object")
    destinations = []
    for target, rule in rules.items():
        tokens = parse(target)
        if any(tokens[:len(other)] == other or other[:len(tokens)] == tokens for other in destinations):
            raise ContractError("MAPPING_CONFLICT", "Overlapping target paths", target)
        destinations.append(tokens)
        if not isinstance(rule, Mapping) or "from" not in rule or set(rule) - {"from", "required", "default", "default_on_null"}:
            raise ContractError("INVALID_MAPPING", "Unknown or missing mapping fields", target)
        parse(rule["from"])
        for key in ("required", "default_on_null"):
            if key in rule and type(rule[key]) is not bool:
                raise ContractError("INVALID_MAPPING", "Mapping switches must be boolean", target)
