"""Non-blocking sink adapter: framework records in, durable batches out.

The framework calls ``record_sink`` **synchronously inside its own event loop**
(``worker.py`` rejects coroutines), so this adapter may never do IO on that
thread: ``accept`` only assigns an ordinal and appends to a bounded deque.
A background flusher drains it, writes the batch to the local outbox *before*
any network call, and acknowledges only after the host answers.

Failure is counted, never raised into business code. Overflow is counted
(``dropped``), never silently absorbed — an evicted record is lost on purpose
and the counter is the only honest evidence of it.
"""
import threading
from collections import deque

from .errors import RegistryError
from .push import DEFAULT_TIMEOUT_SECONDS, send_batch
from .stream import MAX_FRAMES, KIND_RECORD, build_batch, build_frame, check_aggregate
from .store import Store

UNATTRIBUTED = "unattributed"
_AGGREGATE_FIELDS = ("executionId", "execution_id", "traceId", "trace_id")


class RecordStream:
    def __init__(self, *, namespace: str, group: str, config, store=None, capacity: int = 1000,
                 flush_size: int = 100, flush_interval: float = 5.0, kind: str = KIND_RECORD,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS, retries: int = 0):
        if capacity < 1 or flush_size < 1 or flush_size > capacity:
            raise RegistryError("STREAM_INVALID",
                                "capacity and flush_size must satisfy 0 < flush_size <= capacity")
        if flush_size > MAX_FRAMES:
            raise RegistryError("BATCH_TOO_LARGE",
                                f"flush_size {flush_size} exceeds the frame budget {MAX_FRAMES}")
        check_aggregate(namespace)
        check_aggregate(group)
        self.namespace, self.group = namespace, group
        self._config = config
        self._store = store or Store()
        self._capacity, self._flush_size = capacity, flush_size
        self._flush_interval, self._kind = flush_interval, kind
        self._timeout, self._retries = timeout, retries
        self._queue = deque()
        self._sequence = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.accepted = self.dropped = self.renamed = self.invalid = 0
        self.pushed = self.failed_flushes = self.batches = 0

    # ---- producer side: called on the business thread -------------------

    @staticmethod
    def aggregate_of(record) -> str:
        for field in _AGGREGATE_FIELDS:
            value = record.get(field) if isinstance(record, dict) else None
            if isinstance(value, str) and value:
                try:
                    return check_aggregate(value)
                except RegistryError:
                    return UNATTRIBUTED
        return UNATTRIBUTED

    def accept(self, record) -> bool:
        """Never raises, never blocks on IO. Returns False when the frame was dropped."""
        try:
            aggregate = self.aggregate_of(record)
            if aggregate == UNATTRIBUTED and isinstance(record, dict):
                named = any(record.get(field) for field in _AGGREGATE_FIELDS)
                if named:
                    self.renamed += 1
            with self._lock:
                if len(self._queue) >= self._capacity:
                    self.dropped += 1
                    return False
                sequence = self._sequence.get(aggregate, 0) + 1
                self._sequence[aggregate] = sequence
                self._queue.append((aggregate, sequence, record))
            self.accepted += 1
            return True
        except Exception:  # noqa: BLE001 - a sink must never break the caller
            self.invalid += 1
            return False

    # ---- consumer side: drain, persist, push ----------------------------

    def flush(self, *, force: bool = True) -> int:
        """Replay the outbox first, then drain newly queued frames in flush_size chunks."""
        sent = self._drain_outbox()
        while True:
            with self._lock:
                queued = len(self._queue)
                if not queued or (not force and queued < self._flush_size):
                    return sent
                take = min(queued, self._flush_size)
                chunk = [self._queue.popleft() for _ in range(take)]
            frames, rejected = self._project(chunk)
            self.invalid += rejected
            if not frames:
                continue
            batch = build_batch(self.namespace, self.group, frames)
            self._store.enqueue(batch)
            delivered = self._deliver(batch)
            if delivered == 0:
                return sent                      # host unavailable: the batch is durable
            sent += delivered

    def _project(self, chunk) -> tuple[list, int]:
        frames, rejected = [], 0
        for aggregate, sequence, record in chunk:
            try:
                frames.append(build_frame(record, aggregate_key=aggregate, sequence=sequence,
                                          kind=self._kind))
            except (TypeError, ValueError):
                rejected += 1                    # NaN or non-JSON payloads never poison a batch
        return frames, rejected

    def _drain_outbox(self) -> int:
        """Oldest-first replay: pending batches are pushed before anything newer."""
        sent = 0
        for batch in self._store.pending(self.namespace, self.group):
            delivered = self._deliver(batch)
            if delivered == 0:
                break
            sent += delivered
        return sent

    def _deliver(self, batch: dict) -> int:
        try:
            outcome = send_batch(self._config, batch, timeout=self._timeout, retries=self._retries)
        except RegistryError:
            self.failed_flushes += 1
            return 0
        self._store.ack(batch)
        self._store.record_stream(batch, status=outcome["status"],
                                  trace_id=outcome.get("traceId", ""))
        self.batches += 1
        self.pushed += batch["count"]
        return batch["count"]

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> "RecordStream":
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="microflow-registry-sink",
                                            daemon=True)
            self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.flush(force=False)
            except Exception:  # noqa: BLE001 - the flusher must survive its own bugs
                self.failed_flushes += 1
            self._stop.wait(self._flush_interval)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._flush_interval + 1)
        self.flush(force=True)

    def stats(self) -> dict:
        return {"accepted": self.accepted, "dropped": self.dropped, "invalid": self.invalid,
                "renamed": self.renamed, "queued": len(self._queue),
                "pushed": self.pushed, "batches": self.batches,
                "failed_flushes": self.failed_flushes,
                "outbox": self._store.pending_count(self.namespace, self.group),
                "capacity": self._capacity, "flush_size": self._flush_size}

    def pending(self) -> list:
        return self._store.pending(self.namespace, self.group)

    def replay(self) -> int:
        """Explicit outbox drain (used by the CLI and by operators)."""
        return self._drain_outbox()
