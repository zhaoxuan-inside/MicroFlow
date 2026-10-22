"""Bounded in-memory protocol double. Never evidence of production durability."""
import threading
import uuid
from .errors import PersistenceError
from .persistence import Capabilities, CommitReceipt, OwnerToken, RecoveryView, StateBatch
from .values import digest, thaw


class MemoryStateStore:
    capabilities = Capabilities(atomic_batch=True, conditional_write=True, request_deduplication=True)

    def __init__(self, *, max_records=10000, max_requests=10000, max_snapshots=32, max_checkpoints=32):
        for value in (max_records, max_requests, max_snapshots, max_checkpoints):
            if type(value) is not int or value < 1:
                raise ValueError("Budgets must be positive integers")
        self._lock = threading.RLock()
        self._records = {}
        self._requests = {}
        self._snapshots = {}
        self._cursors = set()
        self._checkpoints = {}
        self._revision = 0
        self._generation = 0
        self._owner = None
        self._binding = uuid.uuid4().hex
        self._budgets = max_records, max_requests, max_snapshots, max_checkpoints

    def load_recovery_view(self):
        with self._lock:
            return RecoveryView(self._revision, self._records, binding_revision=self._binding)

    def acquire_owner(self, owner_id):
        if type(owner_id) is not str or not owner_id:
            raise PersistenceError("INVALID_OWNER", "Owner id must be a nonempty string")
        with self._lock:
            if self._owner is not None:
                raise PersistenceError("OWNER_BUSY", "Partition already owned")
            self._generation += 1
            self._owner = OwnerToken(owner_id, self._generation, self._binding)
            return self._owner

    def renew_owner(self, token):
        with self._lock:
            if not isinstance(token, OwnerToken) or self._owner is None or token != self._owner:
                raise PersistenceError("OWNER_FENCED", "Stale owner")

    def release_owner(self, token):
        with self._lock:
            self.renew_owner(token)
            self._owner = None

    def get_commit(self, request_id):
        with self._lock:
            return self._requests.get(request_id, CommitReceipt("NOT_COMMITTED", request_id))

    def commit(self, batch, expected_revision, request_id, owner_token):
        with self._lock:
            self.renew_owner(owner_token)
            if not isinstance(batch, StateBatch) or type(expected_revision) is not int or expected_revision < 0:
                raise PersistenceError("INVALID_BATCH", "Invalid batch or expected revision")
            # Validate request identity even on a conflict, before touching any state.
            CommitReceipt("NOT_COMMITTED", request_id)
            old = self._requests.get(request_id)
            if old is not None:
                if old.batch_digest != batch.batch_digest:
                    raise PersistenceError("REQUEST_CONFLICT", "Request id reused with a different batch")
                return old
            if expected_revision != self._revision:
                return CommitReceipt("CONFLICT", request_id, self._revision)
            records = thaw(self._records)
            records.update(thaw(batch.puts))
            for key in batch.deletes:
                records.pop(key, None)
            if len(records) > self._budgets[0] or len(self._requests) >= self._budgets[1]:
                raise PersistenceError("STATE_BUDGET", "State or request retention budget exhausted")
            receipt = CommitReceipt("COMMITTED", request_id, self._revision + 1, uuid.uuid4().hex,
                                    batch.result, batch.batch_digest, batch.command_digest, False)
            self._records = records
            self._revision += 1
            self._requests[request_id] = receipt
            return receipt

    def read(self, key):
        with self._lock:
            return thaw(self._records[key])

    def query(self, prefix, cursor=None, limit=100):
        if type(prefix) is not str or type(limit) is not int or not 1 <= limit <= 1000:
            raise PersistenceError("INVALID_QUERY", "Expected a prefix and a limit between 1 and 1000")
        with self._lock:
            if cursor is None:
                view = self.load_recovery_view()
                keys = sorted(k for k in view.records if k.startswith(prefix))
                position = 0
                snapshot_id = uuid.uuid4().hex
            else:
                try:
                    if cursor not in self._cursors:
                        raise ValueError()
                    snapshot_id, offset = cursor.split(":")
                    saved_prefix, view, keys = self._snapshots[snapshot_id]
                    position = int(offset)
                    if saved_prefix != prefix or position < 1 or position >= len(keys) or str(position) != offset:
                        raise ValueError()
                except (KeyError, ValueError, AttributeError):
                    raise PersistenceError("INVALID_CURSOR", "Cursor is invalid or closed") from None
            end = min(position + limit, len(keys))
            next_cursor = None
            if end < len(keys):
                if snapshot_id not in self._snapshots and len(self._snapshots) >= self._budgets[2]:
                    raise PersistenceError("SNAPSHOT_BUDGET", "Close a query snapshot before opening another")
                self._snapshots[snapshot_id] = prefix, view, keys
                next_cursor = f"{snapshot_id}:{end}"
                self._cursors.add(next_cursor)
            return RecoveryView(view.revision, {k: view.records[k] for k in keys[position:end]},
                                next_cursor, self._binding)

    def close_cursor(self, cursor):
        with self._lock:
            if type(cursor) is not str or cursor not in self._cursors:
                raise PersistenceError("INVALID_CURSOR", "Cursor is invalid or closed")
            snapshot_id = cursor.split(":")[0]
            del self._snapshots[snapshot_id]
            self._cursors = {c for c in self._cursors if not c.startswith(snapshot_id + ":")}

    def checkpoint(self, expected_revision, request_id, owner_token):
        with self._lock:
            self.renew_owner(owner_token)
            command = digest({"operation": "checkpoint", "expected_revision": expected_revision})
            old = self.get_commit(request_id)
            if old.status == "COMMITTED":
                if old.command_digest != command:
                    raise PersistenceError("REQUEST_CONFLICT", "Request id belongs to another command")
                return old.result
            if expected_revision != self._revision:
                raise PersistenceError("REVISION_CONFLICT", "Checkpoint revision no longer matches")
            if len(self._checkpoints) >= self._budgets[3]:
                raise PersistenceError("CHECKPOINT_BUDGET", "Checkpoint budget exhausted")
            checkpoint_id = uuid.uuid4().hex
            view = self.load_recovery_view()
            self.commit(StateBatch(result=checkpoint_id, command_digest=command), expected_revision,
                        request_id, owner_token)
            self._checkpoints[checkpoint_id] = view
            return checkpoint_id

    def load_checkpoint(self, checkpoint_id):
        with self._lock:
            try:
                return self._checkpoints[checkpoint_id]
            except KeyError:
                raise PersistenceError("CHECKPOINT_NOT_FOUND", "Checkpoint does not exist") from None
