"""Explicit registration and isolated collection of trusted project modules."""
import importlib.util
import inspect
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping
from .errors import ContractError
from .schema import check_schema
from .values import freeze, thaw


@dataclass(frozen=True)
class OperatorDefinition:
    name: str
    version: str
    method: Callable
    input_schema: str
    output_schema: str
    fallback: Callable | None
    metrix: Callable | None
    log: Callable | None
    capabilities: Mapping
    fallback_capabilities: Mapping
    default_policy: Mapping
    description: str
    source_file: str

    @property
    def ref(self):
        return f"{self.name}@{self.version}"


def _signature(method):
    if method is None:
        return
    try:
        parameters = list(inspect.signature(method).parameters.values())
    except (TypeError, ValueError) as exc:
        raise ContractError("INVALID_SIGNATURE", "Handler must be an inspectable callable") from exc
    if len(parameters) != 6 or [p.name for p in parameters] != ["input", "output", "context", "metrix", "debug", "log"] or any(
        p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) or p.default is not p.empty for p in parameters
    ):
        raise ContractError("INVALID_SIGNATURE", "Expected (input, output, context, metrix, debug, log)")


class Registry:
    def __init__(self):
        self._schemas = {}
        self._operators = {}
        self._sealed = False
        self.sources: dict[str, bytes] = {}

    @property
    def schemas(self):
        return MappingProxyType(self._schemas)

    @property
    def operators(self):
        return MappingProxyType(self._operators)

    def _writable(self):
        if self._sealed:
            raise ContractError("REGISTRY_SEALED", "Create a new registry for a new release")

    def register_schema(self, name: str, schema: Mapping):
        self._writable()
        if name in self._schemas:
            raise ContractError("DUPLICATE_SCHEMA", "Schema already registered", name)
        check_schema(schema)
        self._schemas[name] = freeze(thaw(schema))

    def register_operator(self, *, name: str, version: str, method: Callable,
                          input_schema: str, output_schema: str, fallback=None, metrix=None, log=None,
                          capabilities=None, fallback_capabilities=None, default_policy=None, description=""):
        self._writable()
        if type(name) is not str or type(version) is not str or not name or "@" in name or not version or "@" in version:
            raise ContractError("INVALID_OPERATOR_ID", "Invalid stable name or version")
        ref = f"{name}@{version}"
        if ref in self._operators:
            raise ContractError("DUPLICATE_OPERATOR", "Operator already registered", ref)
        if method is None:
            raise ContractError("INVALID_SIGNATURE", "Main method is required", ref)
        for handler in (method, fallback, metrix, log):
            _signature(handler)
        caps = {"effect": "pure", "idempotency_support": "natural", **(capabilities or {})}
        if caps["effect"] not in ("pure", "read", "write") or caps["idempotency_support"] not in ("natural", "external", "query", "none"):
            raise ContractError("INVALID_CAPABILITY", "Invalid operator capability", ref)
        # Fallback is an independent business action: callers must declare its effect.
        if fallback and fallback_capabilities is None:
            raise ContractError("FALLBACK_CAPABILITY_REQUIRED", "Declare fallback capabilities explicitly", ref)
        source = inspect.getsourcefile(method) or ""
        self._operators[ref] = OperatorDefinition(name, version, method, input_schema, output_schema,
            fallback, metrix, log, freeze(caps), freeze(fallback_capabilities or caps),
            freeze(default_policy or {}), description, source)
        for handler in (method, fallback, metrix, log):
            if handler is not None:
                handler_source = inspect.getsourcefile(handler)
                if handler_source:
                    resolved = str(Path(handler_source).resolve(strict=True))
                    content = Path(resolved).read_bytes()
                    if resolved in self.sources and self.sources[resolved] != content:
                        raise ContractError("SOURCE_CHANGED", "Source changed within a registration batch", resolved)
                    self.sources[resolved] = content

    def seal(self):
        for ref, op in self._operators.items():
            if op.input_schema not in self._schemas or op.output_schema not in self._schemas:
                raise ContractError("UNKNOWN_SCHEMA", "Operator references an unknown schema", ref)
        self._sealed = True
        self.sources = MappingProxyType(dict(self.sources))
        return self

    def describe(self):
        return [{"ref": op.ref, "description": op.description, "source_file": op.source_file,
                 "input_schema": op.input_schema, "output_schema": op.output_schema,
                 "capabilities": thaw(op.capabilities), "fallback_capabilities": thaw(op.fallback_capabilities),
                 "handlers": {role: getattr(getattr(op, role), "__qualname__", None)
                              for role in ("method", "fallback", "metrix", "log")}}
                for op in sorted(self._operators.values(), key=lambda op: op.ref)]


def discover(files: list[str | Path]) -> Registry:
    """Only explicitly listed trusted files are imported; failures discard the whole batch."""
    registry = Registry()
    paths = [Path(p).resolve(strict=True) for p in files]
    if len(set(paths)) != len(paths):
        raise ContractError("DUPLICATE_MODULE", "Duplicate manifest entry")
    for path in paths:
        name = f"_microflow_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ContractError("MODULE_IMPORT_FAILED", "Not a Python module", str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            before = path.read_bytes()
            spec.loader.exec_module(module)
            entry = getattr(module, "register", None)
            if not callable(entry):
                raise ContractError("MISSING_REGISTER", "Project module must expose register(registry)", str(path))
            entry(registry)
            if path.read_bytes() != before:
                raise ContractError("SOURCE_CHANGED", "Module changed during registration", str(path))
            registry.sources[str(path)] = before
        except ContractError:
            sys.modules.pop(name, None)
            raise
        except Exception as exc:
            sys.modules.pop(name, None)
            raise ContractError("MODULE_REGISTRATION_FAILED", "Import or registration failed", str(path),
                                exception_type=type(exc).__name__) from exc
    return registry.seal()
