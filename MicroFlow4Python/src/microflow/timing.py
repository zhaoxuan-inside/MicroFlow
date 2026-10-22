"""Wall-compatible budget time without extending budgets on local clock rollback."""
import time
import threading


class BudgetClock:
    def __init__(self):
        self._wall = time.time()
        self._monotonic = time.monotonic()
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            monotonic = time.monotonic()
            now = max(time.time(), self._wall + monotonic - self._monotonic)
            self._wall, self._monotonic = now, monotonic
            return now
