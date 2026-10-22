"""Bounded resource lease protocol for host-injected execution adapters."""
from dataclasses import dataclass
import math
import threading
from typing import Protocol
from .errors import ContractError
from .values import freeze


def _id(value, label):
    if type(value) is not str or not value or len(value) > 256:
        raise ContractError('INVALID_RESOURCE_LEASE', f'{label} must be a bounded identifier')


@dataclass(frozen=True)
class LeaseRequest:
    resource_keys: tuple[str, ...]
    owner_id: str
    generation: int
    ttl: float

    def __post_init__(self):
        if not isinstance(self.resource_keys, (tuple, list)) or not self.resource_keys:
            raise ContractError('INVALID_RESOURCE_LEASE', 'At least one resource key is required')
        keys = tuple(self.resource_keys)
        for key in keys:
            _id(key, 'resource key')
        if len(set(keys)) != len(keys) or keys != tuple(sorted(keys)):
            raise ContractError('INVALID_RESOURCE_LEASE', 'Resource keys must be unique and sorted')
        _id(self.owner_id, 'owner_id')
        if type(self.generation) is not int or self.generation < 1:
            raise ContractError('INVALID_RESOURCE_LEASE', 'Generation must be positive')
        if type(self.ttl) not in (int, float) or not math.isfinite(self.ttl) or self.ttl <= 0:
            raise ContractError('INVALID_RESOURCE_LEASE', 'TTL must be finite and positive')
        object.__setattr__(self, 'resource_keys', keys)


@dataclass(frozen=True)
class ResourceLease:
    lease_id: str
    resource_keys: tuple[str, ...]
    owner_id: str
    generation: int
    expires_at: float

    def __post_init__(self):
        _id(self.lease_id, 'lease_id'); _id(self.owner_id, 'owner_id')
        LeaseRequest(self.resource_keys, self.owner_id, self.generation, 1)
        if type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at):
            raise ContractError('INVALID_RESOURCE_LEASE', 'Expiry must be finite')


class ResourceLeaseProvider(Protocol):
    def acquire(self, request: LeaseRequest, now: float) -> ResourceLease: ...
    def renew(self, lease: ResourceLease, ttl: float, now: float) -> ResourceLease: ...
    def release(self, lease: ResourceLease, now: float) -> None: ...


class MemoryLeaseProvider:
    """Protocol test double; expiry is observed on the next operation."""
    def __init__(self):
        self._lock = threading.RLock(); self._leases = {}; self._counter = 0

    def _check_now(self, now):
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ContractError('INVALID_RESOURCE_LEASE', 'now must be finite')

    def acquire(self, request, now):
        if not isinstance(request, LeaseRequest):
            raise ContractError('INVALID_RESOURCE_LEASE', 'Expected LeaseRequest')
        self._check_now(now)
        with self._lock:
            self._purge(now)
            if any(set(request.resource_keys) & set(item.resource_keys) for item in self._leases.values()):
                raise ContractError('RESOURCE_BUSY', 'Requested resource is leased')
            self._counter += 1
            lease = ResourceLease(f'lease-{self._counter}', request.resource_keys, request.owner_id,
                                  request.generation, now + request.ttl)
            self._leases[lease.lease_id] = lease
            return lease

    def renew(self, lease, ttl, now):
        if not isinstance(lease, ResourceLease) or type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
            raise ContractError('INVALID_RESOURCE_LEASE', 'Invalid lease renewal')
        self._check_now(now)
        with self._lock:
            current = self._leases.get(lease.lease_id)
            if current != lease or now >= lease.expires_at:
                raise ContractError('LEASE_FENCED', 'Lease is expired or no longer current')
            updated = ResourceLease(lease.lease_id, lease.resource_keys, lease.owner_id, lease.generation, now + ttl)
            self._leases[lease.lease_id] = updated
            return updated

    def release(self, lease, now):
        if not isinstance(lease, ResourceLease):
            raise ContractError('INVALID_RESOURCE_LEASE', 'Expected ResourceLease')
        self._check_now(now)
        with self._lock:
            current = self._leases.get(lease.lease_id)
            if current != lease or now >= lease.expires_at:
                raise ContractError('LEASE_FENCED', 'Lease is no longer current')
            del self._leases[lease.lease_id]

    def _purge(self, now):
        for key, lease in tuple(self._leases.items()):
            if now >= lease.expires_at:
                del self._leases[key]

    def snapshot(self):
        with self._lock:
            return freeze({key: lease.__dict__.copy() for key, lease in self._leases.items()})
