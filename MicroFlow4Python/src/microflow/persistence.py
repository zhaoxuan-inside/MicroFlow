"""Host-injected persistence protocols. No production medium is bundled."""
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Literal
from .errors import PersistenceError
from .values import freeze, validate_value, digest
from .schema import check_schema, validate

PROTOCOL_VERSION = "microflow-persistence-v1"


def _identifier(value, label):
    if type(value) is not str or not value:
        raise PersistenceError("INVALID_PERSISTENCE_VALUE", f"{label} must be a nonempty string")


@dataclass(frozen=True)
class Capabilities:
    atomic_batch: bool = False
    conditional_write: bool = False
    request_deduplication: bool = False
    durable_ack: bool = False
    consistent_recovery: bool = False
    ownership_fencing: bool = False
    scope: str = "instance"

    def __post_init__(self):
        for name in ("atomic_batch", "conditional_write", "request_deduplication", "durable_ack",
                     "consistent_recovery", "ownership_fencing"):
            if type(getattr(self, name)) is not bool:
                raise PersistenceError("INVALID_CAPABILITIES", "Capability flags must be boolean", name)
        _identifier(self.scope, "scope")

    def require_durable(self):
        if not all((self.atomic_batch, self.conditional_write, self.request_deduplication,
                    self.durable_ack, self.consistent_recovery)):
            raise PersistenceError("CAPABILITY_REQUIRED", "Provider cannot guarantee durable execution")

    def require_ownership(self, scope: str):
        self.require_durable()
        if not self.ownership_fencing or self.scope != scope:
            raise PersistenceError("CAPABILITY_REQUIRED", "Provider ownership scope does not cover the deployment")


@dataclass(frozen=True)
class StorageBinding:
    provider_id: str
    binding_id: str
    namespace: str
    binding_revision: str
    config_digest: str = ""

    def __post_init__(self):
        for name in ("provider_id", "binding_id", "namespace", "binding_revision"):
            _identifier(getattr(self, name), name)
        if type(self.config_digest) is not str:
            raise PersistenceError("INVALID_BINDING", "Configuration digest must be a string")


@dataclass(frozen=True)
class OwnerToken:
    owner_id: str
    generation: int
    binding_revision: str = ""

    def __post_init__(self):
        _identifier(self.owner_id, "owner_id")
        if type(self.generation) is not int or self.generation < 1:
            raise PersistenceError("INVALID_OWNER", "Owner generation must be a positive integer")
        if type(self.binding_revision) is not str:
            raise PersistenceError("INVALID_OWNER", "Owner binding revision must be a string")


@dataclass(frozen=True)
class RecoveryView:
    revision: int
    records: Mapping
    cursor: str | None = None
    binding_revision: str = ""

    def __post_init__(self):
        if type(self.revision) is not int or self.revision < 0 or not isinstance(self.records, Mapping):
            raise PersistenceError("INVALID_RECOVERY_VIEW", "Expected a nonnegative revision and a Map")
        validate_value(self.records)
        if self.cursor is not None:
            _identifier(self.cursor, "cursor")
        if type(self.binding_revision) is not str:
            raise PersistenceError("INVALID_RECOVERY_VIEW", "Binding revision must be a string")
        object.__setattr__(self, "records", freeze(self.records))


@dataclass(frozen=True)
class StateBatch:
    puts: Mapping = field(default_factory=dict)
    deletes: tuple[str, ...] = ()
    result: object = None
    command_digest: str = ""

    def __post_init__(self):
        if not isinstance(self.puts, Mapping) or not isinstance(self.deletes, (list, tuple)):
            raise PersistenceError("INVALID_BATCH", "Batch requires a Map and a list of deletion keys")
        validate_value(self.puts)
        validate_value(self.result)
        for key in list(self.puts) + list(self.deletes):
            _identifier(key, "record key")
        if len(set(self.deletes)) != len(self.deletes) or set(self.puts) & set(self.deletes):
            raise PersistenceError("INVALID_BATCH", "Duplicate or overlapping deletion keys")
        if type(self.command_digest) is not str:
            raise PersistenceError("INVALID_BATCH", "Command digest must be a string")
        object.__setattr__(self, "puts", freeze(self.puts))
        object.__setattr__(self, "deletes", tuple(self.deletes))
        object.__setattr__(self, "result", freeze(self.result))

    @property
    def batch_digest(self):
        return digest({"puts": self.puts, "deletes": self.deletes, "result": self.result,
                       "command_digest": self.command_digest})


@dataclass(frozen=True)
class CommitReceipt:
    status: Literal["COMMITTED", "CONFLICT", "UNKNOWN", "FAILED", "NOT_COMMITTED"]
    request_id: str
    revision: int = 0
    commit_id: str = ""
    result: object = None
    batch_digest: str = ""
    command_digest: str = ""
    durable: bool = False

    def __post_init__(self):
        if self.status not in ("COMMITTED", "CONFLICT", "UNKNOWN", "FAILED", "NOT_COMMITTED"):
            raise PersistenceError("INVALID_RECEIPT", "Unknown commit status")
        _identifier(self.request_id, "request_id")
        if type(self.revision) is not int or self.revision < 0 or type(self.durable) is not bool:
            raise PersistenceError("INVALID_RECEIPT", "Invalid revision or durability flag")
        for name in ("commit_id", "batch_digest", "command_digest"):
            if type(getattr(self, name)) is not str:
                raise PersistenceError("INVALID_RECEIPT", "Receipt identifiers must be strings", name)
        validate_value(self.result)
        object.__setattr__(self, "result", freeze(self.result))


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    config_schema: Mapping
    capabilities: Capabilities
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self):
        _identifier(self.provider_id, "provider_id")
        if self.protocol_version != PROTOCOL_VERSION:
            raise PersistenceError("UNSUPPORTED_PROVIDER_PROTOCOL", "Unsupported persistence protocol")
        if not isinstance(self.capabilities, Capabilities):
            raise PersistenceError("INVALID_CAPABILITIES", "Expected Capabilities")
        check_schema(self.config_schema)
        if self.config_schema["type"] != "object":
            raise PersistenceError("INVALID_PROVIDER_SCHEMA", "Provider configuration must be a Map")
        object.__setattr__(self, "config_schema", freeze(self.config_schema))


class StateStore(Protocol):
    """All methods operate within the injected binding's namespace.

    commit must fence the owner, atomically compare revision, apply the whole batch,
    and remember request_id + batch digest before giving durable confirmation.
    NOT_COMMITTED from get_commit is authoritative: that request cannot later
    become committed without another submission. Mere absence during an in-flight
    write must return UNKNOWN. Confirmed receipts retain the original JSON result.
    RecoveryView is a consistent partition snapshot, not mixed per-key reads.
    Implementations must also offer bounded query/export for operational histories.
    """
    capabilities: Capabilities

    def load_recovery_view(self) -> RecoveryView: ...
    def commit(self, batch: StateBatch, expected_revision: int, request_id: str,
               owner_token: OwnerToken) -> CommitReceipt: ...
    def get_commit(self, request_id: str) -> CommitReceipt: ...
    def acquire_owner(self, owner_id: str) -> OwnerToken: ...
    def renew_owner(self, token: OwnerToken) -> None: ...
    def release_owner(self, token: OwnerToken) -> None: ...
    # Continuation pages keep the first page's revision. Invalid/expired cursors
    # must fail explicitly rather than restart against current state.
    def query(self, prefix: str, cursor: str | None = None, limit: int = 100) -> RecoveryView: ...
    def close_cursor(self, cursor: str) -> None: ...
    def read(self, key: str): ...
    def checkpoint(self, expected_revision: int, request_id: str, owner_token: OwnerToken) -> str: ...
    def load_checkpoint(self, checkpoint_id: str) -> RecoveryView: ...


class ArtifactStore(Protocol):
    def put_immutable(self, digest: str, content: bytes) -> None: ...
    def get(self, digest: str) -> bytes: ...
    def verify(self, digest: str) -> bool: ...
    def delete_unreferenced(self, digest: str, reference_revision: int) -> None: ...


class PersistenceProvider(Protocol):
    binding: StorageBinding
    state: StateStore
    artifacts: ArtifactStore

    def describe(self) -> ProviderDescriptor: ...


def validate_provider(provider, config, *, expected_binding: StorageBinding,
                      durable=False, ownership_scope=None) -> ProviderDescriptor:
    """Validate an already injected trusted object; never load a provider by name.

    The host supplies the expected binding and the exact resolved configuration.
    Structural checks cannot prove the medium's operational guarantees.
    """
    if not isinstance(expected_binding, StorageBinding):
        raise PersistenceError("INVALID_BINDING", "Expected a StorageBinding")
    descriptor = provider.describe()
    if not isinstance(descriptor, ProviderDescriptor):
        raise PersistenceError("PROVIDER_PROTOCOL", "Expected a versioned ProviderDescriptor")
    binding = getattr(provider, "binding", None)
    if binding != expected_binding or descriptor.provider_id != expected_binding.provider_id:
        raise PersistenceError("BINDING_MISMATCH", "Provider does not match the requested binding revision")
    validate(config, descriptor.config_schema, "provider.config")
    if not expected_binding.config_digest or expected_binding.config_digest != digest(config):
        raise PersistenceError("BINDING_MISMATCH", "Resolved configuration does not match the binding digest")
    state = getattr(provider, "state", None)
    artifacts = getattr(provider, "artifacts", None)
    if getattr(state, "capabilities", None) != descriptor.capabilities:
        raise PersistenceError("PROVIDER_PROTOCOL", "State capabilities differ from the descriptor")
    for service, methods in ((state, ("load_recovery_view", "commit", "get_commit", "acquire_owner",
                                     "renew_owner", "release_owner", "query", "close_cursor", "read",
                                     "checkpoint", "load_checkpoint")),
                             (artifacts, ("put_immutable", "get", "verify", "delete_unreferenced"))):
        if any(not callable(getattr(service, method, None)) for method in methods):
            raise PersistenceError("PROVIDER_PROTOCOL", "Injected provider is missing required operations")
    if durable:
        descriptor.capabilities.require_durable()
    if ownership_scope is not None:
        descriptor.capabilities.require_ownership(ownership_scope)
    return descriptor
