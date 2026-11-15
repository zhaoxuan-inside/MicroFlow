"""MicroFlow4Python persistence subpackage: port protocol + providers + config factory.

All of this lives inside the ``microflow`` package (one project, one wheel):
  protocol.py  — microflow-persistence-v1 port (StateStore/ArtifactStore/...).
  memory.py    — ephemeral in-process provider, the default choice.
  sqlite.py    — durable provider for one instance, an explicit opt-in.
The factory imports concrete provider modules lazily, so importing this
package alone loads only the protocol. Larger media (PostgreSQL/MySQL) are
later providers behind the same port; Redis is not a StateStore candidate —
it cannot honestly declare durable_ack or consistent_recovery.
"""
from collections.abc import Mapping
from dataclasses import asdict

from ..errors import MicroFlowError, PersistenceError
from ..schema import validate as _validate_config
from ..values import digest, freeze, thaw
from .protocol import (PROTOCOL_VERSION, ArtifactStore, Capabilities, CommitReceipt,
                       OwnerToken, PersistenceProvider, ProviderDescriptor, RecoveryView,
                       StateBatch, StateStore, StorageBinding, validate_provider)

PROVIDER_KINDS = ("memory", "sqlite")
CONFIG_PROTOCOL = "microflow-provider-config-v1"


def _load(kind):
    if kind == "memory":
        from . import memory as module
    else:
        from . import sqlite as module
    return module


def create_provider(kind="memory", config=None):
    """Build a provider from the closed kind set and a validated configuration.

    kind "memory" (default) is ephemeral: durable configurations are rejected
    before execution. kind "sqlite" is durable on a single instance. The
    resolved configuration and the StorageBinding are deterministic, so a
    restart with the same configuration reopens the same binding.
    """
    if type(kind) is not str or kind not in PROVIDER_KINDS:
        raise PersistenceError("UNKNOWN_PROVIDER_KIND", f"Provider kind is not in the closed set: {kind!r}")
    module = _load(kind)
    if config is None:
        config = {}
    if not isinstance(config, Mapping):
        raise PersistenceError("PROVIDER_CONFIG_INVALID", "Provider configuration must be an object")
    resolved = {**module.CONFIG_DEFAULTS, **config}
    try:
        _validate_config(resolved, module.CONFIG_SCHEMA, "provider.config")
    except MicroFlowError as error:
        raise PersistenceError("PROVIDER_CONFIG_INVALID", "Provider configuration is invalid") from error
    binding_revision = digest({"kind": kind, "config_protocol": CONFIG_PROTOCOL,
                               "config_schema": module.CONFIG_SCHEMA_VERSION,
                               "namespace": resolved["namespace"],
                               "binding_id": resolved["binding_id"]})
    binding = StorageBinding(module.PROVIDER_ID, resolved["binding_id"], resolved["namespace"],
                             binding_revision, digest(resolved))
    return module.build(freeze(resolved), binding)


def describe_provider_config(kind):
    """Versioned configuration schema, defaults and honest capabilities per kind."""
    if type(kind) is not str or kind not in PROVIDER_KINDS:
        raise PersistenceError("UNKNOWN_PROVIDER_KIND", f"Provider kind is not in the closed set: {kind!r}")
    module = _load(kind)
    return {"protocol": CONFIG_PROTOCOL, "kind": kind,
            "schema_version": module.CONFIG_SCHEMA_VERSION,
            "schema": thaw(module.CONFIG_SCHEMA), "defaults": thaw(module.CONFIG_DEFAULTS),
            "capabilities": asdict(module.PROVIDER_CAPABILITIES)}
