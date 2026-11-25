"""Serialize pure state decisions; uncertain commits fence subsequent writes."""
import threading
import uuid
from collections.abc import Mapping
from dataclasses import replace
from .errors import PersistenceError
from .persistence import CommitReceipt, RecoveryView, StateBatch
from .values import digest, thaw

# Intents are committed as ``event-intent/<event_id>`` records by the
# scheduling layer, atomically with the business change they describe.
# The prefix is part of the state-store layout contract (scheduling.py).
EVENT_INTENT_PREFIX = "event-intent/"


class Coordinator:
    def __init__(self, store, owner_id=None, *, durable=False):
        if not all((store.capabilities.atomic_batch, store.capabilities.conditional_write,
                    store.capabilities.request_deduplication)):
            raise PersistenceError("CAPABILITY_REQUIRED", "Coordinator requires atomic conditional deduplicated commits")
        if durable:
            store.capabilities.require_durable()
        self.store = store
        self.durable = durable
        self._lock = threading.RLock()
        self.owner = store.acquire_owner(owner_id or uuid.uuid4().hex)
        self._closed = False
        self._uncertain = None

    def view(self):
        return self.store.load_recovery_view()

    @property
    def capabilities(self):
        """Capabilities of the injected store; upper layers read this, not the store."""
        return self.store.capabilities

    def view_record(self, key):
        """Use an optional atomic targeted read; retain old-provider behavior."""
        reader = getattr(self.store, "load_record_view", None)
        if not callable(reader):
            return self.view()
        view = reader(key)
        if not isinstance(view, RecoveryView) or view.cursor is not None or set(view.records) - {key}:
            raise PersistenceError("PROVIDER_PROTOCOL", "Invalid targeted recovery view")
        return view

    def pending_events(self, limit=100):
        """Pending delivery intents, oldest first (read face for the host pump).

        The state store is the only delivery ledger: intents committed with the
        business change stay ``delivery: PENDING`` until acknowledged. This is
        a lock-free targeted read (``store.query`` over the intent prefix);
        deterministic order is (recorded_at, event_id) so replays drain the
        same way. Hosts inject the pump; the kernel never loops on delivery.
        """
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise PersistenceError("INVALID_REQUEST", "limit must be between 1 and 1000")
        view = self.store.query(EVENT_INTENT_PREFIX, limit=limit)
        pending = [record for record in view.records.values()
                   if isinstance(record, Mapping) and record.get("delivery") == "PENDING"]
        pending.sort(key=lambda record: (record.get("recorded_at") or 0,
                                         record.get("event_id") or ""))
        return tuple(pending)

    def acknowledge_event(self, event_id, content_digest, *, request_id,
                          expected_revision=None):
        """Mark one intent DELIVERED after the host confirmed actual delivery.

        Single-book flip: the intent record in the state store is authoritative;
        the transport settles its own bookkeeping before calling this. The
        command is idempotent by ``request_id`` (replays return the stored
        result) and re-acknowledging a delivered intent with a fresh request
        id is a recorded no-op, so at-least-once pumps can retry freely.
        """
        for value, label in ((event_id, "event_id"), (content_digest, "content_digest"),
                             (request_id, "request_id")):
            if type(value) is not str or not value:
                raise PersistenceError("INVALID_REQUEST", f"{label} must be a nonempty string")
        command = {"operation": "acknowledge_event", "event_id": event_id,
                   "content_digest": content_digest, "expected_revision": expected_revision}

        def decide(view):
            record = view.records.get(EVENT_INTENT_PREFIX + event_id)
            if not isinstance(record, Mapping):
                raise PersistenceError("UNKNOWN_EVENT", "Event intent does not exist",
                                        request_id=request_id)
            if record.get("content_digest") != content_digest:
                raise PersistenceError("EVENT_ID_CONFLICT",
                                       "Acknowledgement digest does not match event",
                                       request_id=request_id)
            if record.get("delivery") == "DELIVERED":
                return None, {"status": "already-delivered", "event_id": event_id}
            delivered = dict(record)
            delivered["delivery"] = "DELIVERED"
            batch = StateBatch({EVENT_INTENT_PREFIX + event_id: delivered})
            return batch, {"status": "delivered", "event_id": event_id}

        return self.transact(decide, request_id, request_digest=digest(command),
                             expected_revision=expected_revision)

    def _receipt(self, receipt, request_id):
        if not isinstance(receipt, CommitReceipt) or receipt.request_id != request_id:
            raise PersistenceError("PROVIDER_PROTOCOL", "Invalid commit receipt")
        return receipt

    def _query(self, request_id):
        try:
            return self._receipt(self.store.get_commit(request_id), request_id)
        except Exception as error:
            raise PersistenceError("COMMIT_IN_DOUBT", "Cannot query original request", request_id=request_id) from error

    def _confirmed(self, receipt, batch=None, command_digest=None):
        if (not receipt.commit_id or not receipt.batch_digest
                or (batch is not None and receipt.batch_digest != batch.batch_digest)
                or (batch is not None and (receipt.command_digest != batch.command_digest
                                           or digest(receipt.result) != digest(batch.result)))
                or (command_digest is not None and receipt.command_digest != command_digest)
                or (self.durable and not receipt.durable)):
            raise PersistenceError("PROVIDER_PROTOCOL", "Commit confirmation does not match the request")
        return thaw(receipt.result)

    def _settle(self):
        if self._uncertain is None:
            return
        request_id, batch = self._uncertain
        receipt = self._query(request_id)
        if receipt.status == "COMMITTED":
            self._confirmed(receipt, batch)
        elif receipt.status != "NOT_COMMITTED":
            raise PersistenceError("COMMIT_IN_DOUBT", "Original request remains unresolved", request_id=request_id)
        self._uncertain = None

    def transact(self, decide, request_id=None, *, request_digest=None, expected_revision=None):
        """decide(view) -> (StateBatch | None, JSON result), without external effects.

        Stable request IDs require the digest of the complete control command,
        including its expected revision. Confirmed replays return the stored result.
        Only a definite revision conflict may rerun the pure decision.
        """
        if request_id is not None and (type(request_id) is not str or not request_id
                                      or type(request_digest) is not str or not request_digest):
            raise PersistenceError("INVALID_REQUEST", "Stable requests require an id and command digest")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise PersistenceError("INVALID_REQUEST", "Expected revision must be a nonnegative integer")
        with self._lock:
            if self._closed:
                raise PersistenceError("COORDINATOR_CLOSED", "Coordinator is closed")
            self.store.renew_owner(self.owner)
            self._settle()
            if request_id is not None:
                old = self._query(request_id)
                if old.status == "COMMITTED":
                    if old.command_digest != request_digest:
                        raise PersistenceError("REQUEST_CONFLICT", "Request id belongs to a different command")
                    return self._confirmed(old, command_digest=request_digest)
                if old.status != "NOT_COMMITTED":
                    self._uncertain = (request_id, None)
                    raise PersistenceError("COMMIT_IN_DOUBT", "Original request remains unresolved", request_id=request_id)
            for _ in range(16):
                view = self.view()
                if expected_revision is not None and view.revision != expected_revision:
                    raise PersistenceError("REVISION_CONFLICT", "Expected revision no longer matches")
                batch, result = decide(view)
                if batch is None and request_id is None:
                    return result
                if batch is None:
                    batch = StateBatch()
                if not isinstance(batch, StateBatch):
                    raise PersistenceError("INVALID_BATCH", "Decision must return a StateBatch")
                batch = replace(batch, result=result, command_digest=request_digest or "")
                command = request_id or uuid.uuid4().hex
                self._uncertain = (command, batch)
                try:
                    receipt = self._receipt(self.store.commit(batch, view.revision, command, self.owner), command)
                except Exception:
                    receipt = self._query(command)
                if receipt.status == "UNKNOWN":
                    receipt = self._query(command)
                if receipt.status == "COMMITTED":
                    result = self._confirmed(receipt, batch)
                    self._uncertain = None
                    return result
                if receipt.status in ("CONFLICT", "FAILED", "NOT_COMMITTED"):
                    self._uncertain = None
                    if receipt.status == "CONFLICT":
                        if request_id is not None or expected_revision is not None:
                            raise PersistenceError("REVISION_CONFLICT", "Control command must be re-evaluated")
                        continue
                    raise PersistenceError("COMMIT_FAILED", "Provider rejected atomic state change", request_id=command)
                raise PersistenceError("COMMIT_IN_DOUBT", "Cannot confirm original request", request_id=command)
            raise PersistenceError("REVISION_CONFLICT", "State remained contended")

    def close(self):
        with self._lock:
            if not self._closed:
                self.store.release_owner(self.owner)
                self._closed = True
