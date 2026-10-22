"""Serialize pure state decisions; uncertain commits fence subsequent writes."""
import threading
import uuid
from dataclasses import replace
from .errors import PersistenceError
from .persistence import CommitReceipt, StateBatch
from .values import digest, thaw


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
