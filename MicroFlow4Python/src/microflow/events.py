"""Reliable event intent and deduplication protocol.

The framework records an intent before a host delivers it. Delivery itself is
owned by the injected provider and may be repeated safely by event_id.
"""
from dataclasses import dataclass
import math
import threading
from typing import Protocol
from .errors import ContractError, PersistenceError
from .values import digest, freeze, thaw, validate_value

PROTOCOL_VERSION = 'microflow-event-v1'


def _text(value, label):
    if type(value) is not str or not value or len(value) > 256:
        raise ContractError('INVALID_EVENT', f'{label} must be a bounded nonempty string')


def _time(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ContractError('INVALID_EVENT', f'{label} must be finite and nonnegative')


@dataclass(frozen=True)
class EventIntent:
    event_id: str
    event_type: str
    schema_version: str
    aggregate_key: str
    sequence: int
    payload: object
    execution_id: str
    release_id: str
    occurred_at: float
    recorded_at: float
    protocol: str = PROTOCOL_VERSION

    def __post_init__(self):
        for value, label in ((self.event_id, 'event_id'), (self.event_type, 'event_type'),
                             (self.schema_version, 'schema_version'), (self.aggregate_key, 'aggregate_key'),
                             (self.execution_id, 'execution_id'), (self.release_id, 'release_id')):
            _text(value, label)
        if type(self.sequence) is not int or self.sequence < 1:
            raise ContractError('INVALID_EVENT', 'sequence must be a positive integer')
        validate_value(self.payload)
        _time(self.occurred_at, 'occurred_at'); _time(self.recorded_at, 'recorded_at')
        if self.recorded_at < self.occurred_at:
            raise ContractError('INVALID_EVENT', 'recorded_at cannot precede occurred_at')
        if self.protocol != PROTOCOL_VERSION:
            raise ContractError('UNSUPPORTED_EVENT_PROTOCOL', 'Unsupported event protocol')
        object.__setattr__(self, 'payload', freeze(self.payload))

    @property
    def content_digest(self):
        return digest({'event_type': self.event_type, 'schema_version': self.schema_version,
                       'aggregate_key': self.aggregate_key, 'sequence': self.sequence,
                       'payload': self.payload, 'execution_id': self.execution_id,
                       'release_id': self.release_id, 'occurred_at': self.occurred_at})

    def value(self):
        return {'protocol': self.protocol, 'event_id': self.event_id, 'event_type': self.event_type,
                'schema_version': self.schema_version, 'aggregate_key': self.aggregate_key,
                'sequence': self.sequence, 'payload': thaw(self.payload), 'execution_id': self.execution_id,
                'release_id': self.release_id, 'occurred_at': self.occurred_at,
                'recorded_at': self.recorded_at}


class EventStore(Protocol):
    def append(self, event: EventIntent) -> EventIntent: ...
    def acknowledge(self, event_id: str, content_digest: str) -> EventIntent: ...
    def pending(self, limit: int = 100) -> tuple[EventIntent, ...]: ...


class MemoryEventStore:
    """Bounded protocol substitute with atomic event-id and sequence checks."""
    def __init__(self, *, max_events=1000):
        if type(max_events) is not int or max_events < 1:
            raise ContractError('INVALID_EVENT', 'max_events must be positive')
        self.max_events = max_events
        self._lock = threading.RLock(); self._events = {}; self._status = {}; self._last = {}

    def append(self, event):
        if not isinstance(event, EventIntent):
            raise ContractError('INVALID_EVENT', 'Expected EventIntent')
        with self._lock:
            existing = self._events.get(event.event_id)
            if existing is not None:
                if existing.content_digest != event.content_digest:
                    raise PersistenceError('EVENT_ID_CONFLICT', 'event_id belongs to another event')
                return existing
            expected = self._last.get(event.aggregate_key, 0) + 1
            if event.sequence != expected:
                raise PersistenceError('EVENT_SEQUENCE_CONFLICT', 'Aggregate sequence is not contiguous')
            if len(self._events) >= self.max_events:
                raise PersistenceError('EVENT_CAPACITY', 'Event intent capacity exhausted')
            self._events[event.event_id] = event; self._status[event.event_id] = 'PENDING'
            self._last[event.aggregate_key] = event.sequence
            return event

    def acknowledge(self, event_id, content_digest):
        _text(event_id, 'event_id'); _text(content_digest, 'content_digest')
        with self._lock:
            event = self._events.get(event_id)
            if event is None:
                raise PersistenceError('UNKNOWN_EVENT', 'Event intent does not exist')
            if event.content_digest != content_digest:
                raise PersistenceError('EVENT_ID_CONFLICT', 'Acknowledgement digest does not match event')
            self._status[event_id] = 'DELIVERED'
            return event

    def pending(self, limit=100):
        if type(limit) is not int or limit < 1:
            raise ContractError('INVALID_EVENT', 'limit must be positive')
        with self._lock:
            return tuple(event for event in self._events.values()
                         if self._status[event.event_id] == 'PENDING')[:limit]

    def status(self, event_id):
        _text(event_id, 'event_id')
        with self._lock:
            if event_id not in self._events:
                raise PersistenceError('UNKNOWN_EVENT', 'Event intent does not exist')
            return self._status[event_id]
