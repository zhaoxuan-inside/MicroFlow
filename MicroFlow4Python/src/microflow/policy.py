"""Deterministic policy inheritance. Capability declarations cannot be overridden."""
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from .errors import ContractError
from .values import digest, freeze, thaw, validate_value
from .paths import parse

DEFAULTS = freeze({
    "execution_mode": "sync", "durability": "durable", "persistence_binding": "runtime-state",
    "recovery": {"enabled": True},
    "checkpoint_policy": "operator",
    "cache": {"enabled": False, "ttl": "60s", "max_entries": 1024, "max_bytes": 8_388_608,
              "key_paths": [], "scope": "runtime", "single_flight": True},
    "idempotency": {"enabled": False, "key_paths": [], "scope": "business",
                    "result_retention": "30d", "replay_policy": "confirmed"},
    "timeout": {"attempt": "30s", "queue": "30s", "deadline": "300s"},
    "retry": {"max_attempts": 1, "base": "100ms", "cap": "10s", "retry_after_fallback": False},
    "concurrency": 16,
    "resource_policy": {"keys": []},
    "observability": {"max_events": 1000},
})


def _descriptor(value, path=""):
    if isinstance(value, Mapping):
        return {"type": "object", "additionalProperties": False,
                "properties": {k: _descriptor(v, f"{path}.{k}" if path else k) for k, v in value.items()}}
    if path in {"cache.ttl", "idempotency.result_retention", "timeout.attempt", "timeout.queue",
                "timeout.deadline", "retry.base", "retry.cap"}:
        return {"type": "duration", "units": ["ms", "s", "m", "h", "d"], "exclusiveMinimum": 0}
    if type(value) is bool:
        return {"type": "boolean"}
    if type(value) is int:
        return {"type": "integer", "minimum": 1}
    if isinstance(value, (list, tuple)):
        return {"type": "array", "items": {"type": "path"}}
    enums = {"execution_mode": ["sync", "async"], "durability": ["durable", "ephemeral"],
             "checkpoint_policy": ["operator", "explicit"], "cache.scope": ["runtime"],
             "idempotency.scope": ["business"], "idempotency.replay_policy": ["confirmed"]}
    return {"type": "string", "enum": enums[path]} if path in enums else {"type": "string", "minLength": 1}


POLICY_SCHEMA = freeze(_descriptor(DEFAULTS))


def describe_policy():
    """Framework descriptor vocabulary, distinct from business MicroFlow Schema v1."""
    return {"protocol": "microflow-policy-schema-v1", "schema": thaw(POLICY_SCHEMA),
            "defaults": thaw(DEFAULTS), "merge": {"objects": "recursive", "arrays": "replace",
            "null": "reject", "missing": "inherit", "overrides": "explicit-leaf-whitelist"}}


def validate_policy(config, schema=POLICY_SCHEMA, path="policy"):
    """Validate a partial policy layer, including values later overridden."""
    validate_value(config)
    kind = schema["type"]
    if kind == "object":
        if not isinstance(config, Mapping):
            raise ContractError("INVALID_POLICY", "Expected configuration object", path)
        for key, value in config.items():
            if key not in schema["properties"]:
                raise ContractError("UNKNOWN_POLICY_FIELD", "Unknown policy field", f"{path}.{key}")
            validate_policy(value, schema["properties"][key], f"{path}.{key}")
    elif kind == "duration":
        try:
            seconds(config)
        except ContractError as error:
            raise ContractError("INVALID_POLICY", "Expected positive finite duration", path) from error
    elif kind == "array":
        if not isinstance(config, (list, tuple)):
            raise ContractError("INVALID_POLICY", "Expected an array of paths", path)
        for index, item in enumerate(config):
            validate_policy(item, schema["items"], f"{path}[{index}]")
    elif kind == "path":
        try:
            parse(config)
        except ContractError as error:
            raise ContractError("INVALID_POLICY", "Expected a valid field path", path) from error
    elif (kind == "boolean" and type(config) is not bool
          or kind == "integer" and (type(config) is not int or config < schema["minimum"])
          or kind == "string" and (type(config) is not str or not config)):
        raise ContractError("INVALID_POLICY", f"Expected {kind}", path)
    elif "enum" in schema and config not in schema["enum"]:
        raise ContractError("INVALID_POLICY", "Unsupported policy value", path)


def seconds(value: str | int | float) -> float:
    if type(value) in (int, float) and 0 < value < float("inf"):
        return float(value)
    if isinstance(value, str):
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", value)
        if match:
            result = float(match[1]) * {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400}[match[2]]
            if 0 < result < float("inf"):
                return result
    raise ContractError("INVALID_POLICY", "Expected positive finite duration")


@dataclass(frozen=True)
class EffectiveOperatorPolicy:
    values: Mapping
    policy_digest: str

    def __getitem__(self, name):
        return self.values[name]


def resolve(*layers: Mapping, capabilities: Mapping | None = None,
            provider_capabilities=None, allowed_overrides: set[str] | None = None,
            overrides: Mapping | None = None) -> EffectiveOperatorPolicy:
    result = thaw(DEFAULTS)

    def merge(target, source, template, path="policy"):
        if not isinstance(source, Mapping):
            raise ContractError("INVALID_POLICY", "Expected configuration object", path)
        for k, v in source.items():
            if k not in template:
                raise ContractError("UNKNOWN_POLICY_FIELD", "Unknown policy field", f"{path}.{k}")
            if isinstance(template[k], Mapping):
                merge(target[k], v, template[k], f"{path}.{k}")
            else:
                target[k] = thaw(v)

    for layer in layers:
        validate_policy(layer)
        merge(result, layer, DEFAULTS)
    if overrides is not None:
        validate_policy(overrides)
        def leaf_paths(value, prefix=""):
            if not isinstance(value, Mapping):
                raise ContractError("INVALID_POLICY", "Overrides must be objects")
            for key, child in value.items():
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(child, Mapping):
                    yield from leaf_paths(child, path)
                else:
                    yield path

        if not set(leaf_paths(overrides)) <= (allowed_overrides or set()):
            raise ContractError("FORBIDDEN_OVERRIDE", "Invocation override not allowed")
        merge(result, overrides, DEFAULTS)
    caps = capabilities or {"effect": "pure", "idempotency_support": "natural"}
    if result["durability"] == "ephemeral" and (result["execution_mode"] == "async" or result["recovery"]["enabled"] or result["idempotency"]["enabled"]):
        raise ContractError("CAPABILITY_REQUIRED", "Ephemeral mode only supports synchronous nonrecoverable execution")
    if result["cache"]["enabled"] and (caps.get("effect") not in ("pure", "read") or
                                        (caps.get("effect") == "read" and not caps.get("data_version"))):
        raise ContractError("UNSAFE_CACHE", "Cache needs pure computation or versioned reads")
    if result["cache"]["key_paths"]:
        raise ContractError("UNSUPPORTED_POLICY", "Input pruning requires a dependency proof; use full-input keys")
    safe = caps.get("idempotency_support") in ("natural", "external", "query")
    if caps.get("effect") == "write" and not safe and (result["retry"]["max_attempts"] > 1 or result["recovery"]["enabled"] or result["idempotency"]["enabled"]):
        raise ContractError("UNSAFE_REEXECUTION", "Write operation has no result confirmation or idempotency capability")
    if result["idempotency"]["enabled"] and not result["idempotency"]["key_paths"]:
        raise ContractError("INVALID_POLICY", "Business idempotency requires stable key_paths")
    if result["durability"] == "durable":
        if provider_capabilities is None:
            raise ContractError("CAPABILITY_REQUIRED", "Durable execution requires a bound persistence provider")
        provider_capabilities.require_durable()
    return EffectiveOperatorPolicy(freeze(result), digest(result))
