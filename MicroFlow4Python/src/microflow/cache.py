"""Bounded process-local LRU/TTL result cache with generation-safe fills."""
import threading
import time
from collections import OrderedDict
from .values import canonical, thaw


class ResultCache:
    def __init__(self):
        self._entries = OrderedDict()
        self._bytes = 0
        self._generation = 0
        self._lock = threading.RLock()

    @property
    def generation(self):
        with self._lock:
            return self._generation

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry[0] <= time.monotonic():
                self._remove(key)
                return None
            self._entries.move_to_end(key)
            return thaw(entry[1])

    def _remove(self, key):
        _, _, size = self._entries.pop(key)
        self._bytes -= size

    def put(self, key, data, ttl, max_entries, max_bytes, generation):
        size = len(canonical(data))
        with self._lock:
            if generation != self._generation or size > max_bytes:
                return
            if key in self._entries:
                self._remove(key)
            self._entries[key] = (time.monotonic() + ttl, thaw(data), size)
            self._bytes += size
            while self._entries and (len(self._entries) > max_entries or self._bytes > max_bytes):
                self._remove(next(iter(self._entries)))

    def invalidate(self):
        with self._lock:
            self._generation += 1
            self._entries.clear()
            self._bytes = 0
