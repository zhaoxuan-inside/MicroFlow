"""The six-argument operator surface. Runtime objects never enter persisted Maps."""
import threading
import math
from dataclasses import dataclass
from collections import Counter
from types import MappingProxyType
from typing import Any, Mapping
from .errors import Cancelled, ContractError
from .paths import get, set_value
from .values import freeze, thaw, validate_value


class Input(Mapping):
    def __init__(self, data):
        validate_value(data)
        if not isinstance(data, Mapping):
            raise ContractError("INVALID_INPUT", "Input must be a Map")
        self._data = freeze(data)

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def get_path(self, path, default=None):
        return get(self._data, path, default)


class Output:
    __slots__ = ("_data", "_rejection")

    def __init__(self):
        self._data = {}
        self._rejection = None

    @property
    def data(self):
        return self._data

    def set(self, path: str, value: Any):
        validate_value(value)
        candidate = thaw(self._data)
        set_value(candidate, path, value)
        self._data = candidate

    def reject(self, code="OPERATOR_REJECTED", message="Operator reported failure"):
        self._rejection = {"code": code, "message": message}


@dataclass(frozen=True)
class Context:
    options: Mapping
    resources: Mapping

    def __post_init__(self):
        validate_value(self.options)
        object.__setattr__(self, "options", freeze(self.options))
        object.__setattr__(self, "resources", MappingProxyType(dict(self.resources)))

    def resource(self, name):
        return self.resources[name]


class Metrics:
    def __init__(self, limit=1000):
        self.counts = Counter()
        self.samples = {}
        self.limit = limit

    def increment(self, name, value=1):
        self._check(name, value)
        if len(self.counts) >= self.limit and name not in self.counts:
            raise ContractError("METRIC_LIMIT", "Metric cardinality exceeded")
        self.counts[name] += value

    def observe(self, name, value):
        self._check(name, value)
        if name not in self.samples and len(self.samples) >= self.limit:
            raise ContractError("METRIC_LIMIT", "Metric cardinality exceeded")
        entry = self.samples.setdefault(name, {"count": 0, "sum": 0, "buckets": [0] * 8})
        entry["count"] += 1
        entry["sum"] += value
        for i, bound in enumerate((.001, .01, .1, 1, 10, 60, 300, float("inf"))):
            if value <= bound:
                entry["buckets"][i] += 1
                break

    def _check(self, name, value):
        if type(name) is not str or not name or type(value) not in (int, float) or not math.isfinite(value):
            raise ContractError("INVALID_METRIC", "Expected a named finite numeric measurement")


class Debug:
    def __init__(self, cancel: threading.Event, checkpoint=None, *, can_pause=True):
        self.cancel = cancel
        self._checkpoint = checkpoint
        self._can_pause = can_pause
        self._gate = threading.Event()
        self._gate.set()
        self.snapshots = []
        self.progress = None

    def check_cancelled(self):
        if self.cancel.is_set():
            raise Cancelled()

    def snapshot(self, value):
        validate_value(value)
        if len(self.snapshots) >= 16:
            raise ContractError("SNAPSHOT_LIMIT", "Snapshot budget exceeded")
        self.snapshots.append(thaw(value))

    def checkpoint(self, value):
        validate_value(value)
        if self._checkpoint:
            self._checkpoint(thaw(value))
        else:
            raise ContractError("CHECKPOINT_UNAVAILABLE", "No checkpoint channel")

    def pause(self):
        if not self._can_pause:
            raise ContractError("UNSAFE_PAUSE", "Cannot pause while holding critical resources")
        self._gate.clear()

    def resume(self):
        self._gate.set()

    def wait(self):
        while not self._gate.wait(.05):
            self.check_cancelled()
        self.check_cancelled()


class Log:
    def __init__(self, limit=1000):
        self.records = []
        self.events = []
        self.limit = limit
        self.dropped = 0

    def write(self, message: str, **fields):
        validate_value(fields)
        if len(self.records) >= self.limit:
            self.dropped += 1
        else:
            self.records.append({"message": message, "fields": thaw(fields)})

    def event(self, event_id: str, event_type: str, data: Mapping, *, schema_version="1"):
        validate_value(data)
        if len(self.events) >= self.limit:
            raise ContractError("EVENT_LIMIT", "Reliable event budget exceeded")
        if not event_id or not event_type:
            raise ContractError("INVALID_EVENT", "Event identity and type are required")
        self.events.append({"event_id": event_id, "event_type": event_type,
                            "schema_version": schema_version, "data": thaw(data)})
