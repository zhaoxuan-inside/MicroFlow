"""Durable SQLite provider for one instance (scope="instance").

Durability claim: commits run in WAL mode with synchronous=FULL and the
commit receipt is written in the same transaction, so an acknowledged
COMMITTED receipt survives process exit and power loss on the same host.
This is not a cross-host high-availability medium (SCALABILITY.md): a second
owner takes over only after the lease expires, with a strictly higher
fencing generation; every commit fences the current lease.
"""
import hashlib
import json
import math
import sqlite3
import threading
import time as _time
import uuid

from ..errors import PersistenceError
from ..values import digest, thaw
from .protocol import (Capabilities, CommitReceipt, OwnerToken, ProviderDescriptor,
                       RecoveryView, StateBatch)

PROVIDER_ID = "microflow-sqlite"
SQLITE_STATE_SCHEMA = "microflow-sqlite-state-v1"
CONFIG_SCHEMA_VERSION = "microflow-sqlite-config-v1"
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "namespace": {"type": "string", "minLength": 1},
        "binding_id": {"type": "string", "minLength": 1},
        "lease_ttl_seconds": {"type": "number", "minimum": 1},
        "busy_timeout_ms": {"type": "integer", "minimum": 0},
        "max_records": {"type": "integer", "minimum": 1},
        "max_requests": {"type": "integer", "minimum": 1},
        "max_snapshots": {"type": "integer", "minimum": 1},
        "max_checkpoints": {"type": "integer", "minimum": 1},
    },
    "required": ["path"],
}
CONFIG_DEFAULTS = {"namespace": "main", "binding_id": "runtime-state",
                          "lease_ttl_seconds": 30, "busy_timeout_ms": 5000,
                          "max_records": 1_000_000, "max_requests": 1_000_000,
                          "max_snapshots": 8, "max_checkpoints": 64}
PROVIDER_CAPABILITIES = Capabilities(atomic_batch=True, conditional_write=True,
                                     request_deduplication=True, durable_ack=True,
                                     consistent_recovery=True, ownership_fencing=True,
                                     scope="instance")

_REQUEST_COLUMNS = "status, request_id, revision, commit_id, result, batch_digest, command_digest, durable"


def _unavailable(error):
    return PersistenceError("STORE_UNAVAILABLE", f"SQLite store unavailable: {error}")


class SQLiteStateStore:
    """Single-writer durable StateStore on one SQLite file (microflow-persistence-v1).

    All operations serialize on one connection guarded by a reentrant lock,
    mirroring the memory double's threading model. get_commit briefly probes
    the write lock: absence during an in-flight write returns UNKNOWN instead
    of an authoritative NOT_COMMITTED.
    """
    capabilities = PROVIDER_CAPABILITIES

    def __init__(self, path, *, binding_revision, namespace="main", binding_id="runtime-state",
                 lease_ttl_seconds=30, busy_timeout_ms=5000, max_records=1_000_000,
                 max_requests=1_000_000, max_snapshots=8, max_checkpoints=64, time_fn=None):
        for name, value in (("path", path), ("binding_revision", binding_revision),
                            ("namespace", namespace), ("binding_id", binding_id)):
            if type(value) is not str or not value:
                raise PersistenceError("INVALID_BINDING", f"{name} must be a nonempty string", name)
        for name, value in (("lease_ttl_seconds", lease_ttl_seconds),):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise PersistenceError("INVALID_BINDING", "Lease TTL must be positive and finite", name)
        for name, value in (("busy_timeout_ms", busy_timeout_ms), ("max_records", max_records),
                            ("max_requests", max_requests), ("max_snapshots", max_snapshots),
                            ("max_checkpoints", max_checkpoints)):
            if type(value) is not int or value < 0:
                raise PersistenceError("INVALID_BINDING", f"{name} must be a nonnegative integer", name)
        self._lock = threading.RLock()
        self._binding_revision = binding_revision
        self._namespace = namespace
        self._binding_id = binding_id
        self._ttl = float(lease_ttl_seconds)
        self._busy = int(busy_timeout_ms)
        self._budgets = max_records, max_requests, max_snapshots, max_checkpoints
        self._time = time_fn or _time.time
        self._snapshots = {}
        self._cursors = set()
        self._connection = None
        try:
            self._connection = sqlite3.connect(path, timeout=self._busy / 1000,
                                               check_same_thread=False, isolation_level=None)
        except sqlite3.Error as error:
            raise PersistenceError("STORE_OPEN_FAILED",
                                   f"State store medium cannot be opened: {error}") from error
        try:
            self._configure()
        except sqlite3.Error as error:
            self._connection.close()
            self._connection = None
            raise PersistenceError("STORE_OPEN_FAILED",
                                   f"State store medium cannot be initialized: {error}") from error
        except BaseException:
            self._connection.close()
            self._connection = None
            raise

    def _configure(self):
        con = self._connection
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute(f"PRAGMA busy_timeout={self._busy}")
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute("CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK (id = 1),"
                        " protocol TEXT NOT NULL, provider_id TEXT NOT NULL, namespace TEXT NOT NULL,"
                        " binding_id TEXT NOT NULL, binding_revision TEXT NOT NULL, schema_version TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK (id = 1),"
                        " revision INTEGER NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID")
            con.execute("CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, status TEXT NOT NULL,"
                        " revision INTEGER NOT NULL, commit_id TEXT NOT NULL, result TEXT, batch_digest TEXT NOT NULL,"
                        " command_digest TEXT NOT NULL, durable INTEGER NOT NULL) WITHOUT ROWID")
            con.execute("CREATE TABLE IF NOT EXISTS owners (id INTEGER PRIMARY KEY CHECK (id = 1),"
                        " owner_id TEXT NOT NULL, generation INTEGER NOT NULL, expires_at REAL NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS checkpoints (checkpoint_id TEXT PRIMARY KEY,"
                        " revision INTEGER NOT NULL, payload TEXT NOT NULL) WITHOUT ROWID")
            con.execute("CREATE TABLE IF NOT EXISTS artifacts (digest TEXT PRIMARY KEY, content BLOB NOT NULL,"
                        " size INTEGER NOT NULL) WITHOUT ROWID")
            identity = ("microflow-persistence-v1", PROVIDER_ID, self._namespace,
                        self._binding_id, self._binding_revision, SQLITE_STATE_SCHEMA)
            row = con.execute("SELECT protocol, provider_id, namespace, binding_id, binding_revision,"
                              " schema_version FROM meta WHERE id = 1").fetchone()
            if row is None:
                con.execute("INSERT INTO meta VALUES (1, ?, ?, ?, ?, ?, ?)", identity)
            elif tuple(row) != identity:
                raise PersistenceError("BINDING_MISMATCH",
                                       "Store file is already bound to another provider identity")
            con.execute("INSERT OR IGNORE INTO state (id, revision) VALUES (1, 0)")
            con.execute("COMMIT")
        except BaseException:
            self._safe_rollback(con)
            raise

    @staticmethod
    def _safe_rollback(con):
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def _require_open(self):
        if self._connection is None:
            raise PersistenceError("STORE_UNAVAILABLE", "State store is closed")

    def _now(self):
        value = self._time()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise PersistenceError("INVALID_CLOCK", "Lease clock must return nonnegative finite seconds")
        return float(value)

    def _fence(self, token, now, con):
        if not isinstance(token, OwnerToken):
            raise PersistenceError("OWNER_FENCED", "Stale owner")
        row = con.execute("SELECT owner_id, generation, expires_at FROM owners WHERE id = 1").fetchone()
        if (row is None or row[0] != token.owner_id or row[1] != token.generation
                or token.binding_revision != self._binding_revision or row[2] <= now):
            raise PersistenceError("OWNER_FENCED", "Stale owner")

    @staticmethod
    def _row_receipt(row):
        status, request_id, revision, commit_id, result, batch_digest, command_digest, durable = row
        return CommitReceipt(status, request_id, revision, commit_id,
                             json.loads(result) if result is not None else None,
                             batch_digest, command_digest, bool(durable))

    def _dump(self, value):
        return json.dumps(thaw(value), ensure_ascii=True, separators=(",", ":"))

    def _read_revision_and_records(self, where="", parameters=()):
        con = self._connection
        con.execute("BEGIN DEFERRED")
        try:
            revision = con.execute("SELECT revision FROM state WHERE id = 1").fetchone()[0]
            rows = con.execute(f"SELECT key, value FROM records{where} ORDER BY key", parameters).fetchall()
            con.execute("COMMIT")
        except BaseException:
            self._safe_rollback(con)
            raise
        return revision, rows

    def load_recovery_view(self):
        with self._lock:
            self._require_open()
            try:
                revision, rows = self._read_revision_and_records()
            except sqlite3.Error as error:
                raise _unavailable(error) from error
            return RecoveryView(revision, {key: json.loads(value) for key, value in rows},
                                binding_revision=self._binding_revision)

    def load_record_view(self, key):
        if type(key) is not str or not key:
            raise PersistenceError("INVALID_PERSISTENCE_VALUE", "record key must be a nonempty string")
        with self._lock:
            self._require_open()
            try:
                revision, rows = self._read_revision_and_records(" WHERE key = ?", (key,))
            except sqlite3.Error as error:
                raise _unavailable(error) from error
            records = {row[0]: json.loads(row[1]) for row in rows}
            return RecoveryView(revision, records, binding_revision=self._binding_revision)

    def acquire_owner(self, owner_id):
        if type(owner_id) is not str or not owner_id:
            raise PersistenceError("INVALID_OWNER", "Owner id must be a nonempty string")
        with self._lock:
            self._require_open()
            now = self._now()
            try:
                con = self._connection
                con.execute("BEGIN IMMEDIATE")
                try:
                    row = con.execute("SELECT owner_id, generation, expires_at FROM owners WHERE id = 1").fetchone()
                    if row is not None and row[2] > now:
                        raise PersistenceError("OWNER_BUSY", "Partition already owned")
                    generation = (row[1] if row is not None else 0) + 1
                    con.execute("INSERT OR REPLACE INTO owners VALUES (1, ?, ?, ?)",
                                (owner_id, generation, now + self._ttl))
                    con.execute("COMMIT")
                except BaseException:
                    self._safe_rollback(con)
                    raise
            except sqlite3.Error as error:
                raise _unavailable(error) from error
            return OwnerToken(owner_id, generation, self._binding_revision)

    def renew_owner(self, token):
        with self._lock:
            self._require_open()
            now = self._now()
            try:
                con = self._connection
                con.execute("BEGIN IMMEDIATE")
                try:
                    self._fence(token, now, con)
                    con.execute("UPDATE owners SET expires_at = ? WHERE id = 1", (now + self._ttl,))
                    con.execute("COMMIT")
                except BaseException:
                    self._safe_rollback(con)
                    raise
            except sqlite3.Error as error:
                raise _unavailable(error) from error

    def release_owner(self, token):
        with self._lock:
            self._require_open()
            now = self._now()
            try:
                con = self._connection
                con.execute("BEGIN IMMEDIATE")
                try:
                    self._fence(token, now, con)
                    # Keep the row so the fencing generation stays monotonic
                    # across release/re-acquire cycles; expiry marks it free.
                    con.execute("UPDATE owners SET expires_at = 0 WHERE id = 1")
                    con.execute("COMMIT")
                except BaseException:
                    self._safe_rollback(con)
                    raise
            except sqlite3.Error as error:
                raise _unavailable(error) from error

    def get_commit(self, request_id):
        with self._lock:
            self._require_open()
            con = self._connection
            # Probe the write lock with zero timeout: if another writer holds
            # it, absence of the receipt is not authoritative (UNKNOWN).
            con.execute("PRAGMA busy_timeout=0")
            try:
                try:
                    con.execute("BEGIN IMMEDIATE")
                except sqlite3.Error:
                    return CommitReceipt("UNKNOWN", request_id)
                try:
                    row = con.execute(f"SELECT {_REQUEST_COLUMNS} FROM requests WHERE request_id = ?",
                                      (request_id,)).fetchone()
                    con.execute("COMMIT")
                except BaseException:
                    self._safe_rollback(con)
                    raise
            except sqlite3.Error:
                return CommitReceipt("UNKNOWN", request_id)
            finally:
                con.execute(f"PRAGMA busy_timeout={self._busy}")
            return self._row_receipt(row) if row is not None else CommitReceipt("NOT_COMMITTED", request_id)

    def commit(self, batch, expected_revision, request_id, owner_token):
        with self._lock:
            self._require_open()
            if not isinstance(batch, StateBatch) or type(expected_revision) is not int or expected_revision < 0:
                raise PersistenceError("INVALID_BATCH", "Invalid batch or expected revision")
            # Validate request identity even on a conflict, before touching any state.
            CommitReceipt("NOT_COMMITTED", request_id)
            now = self._now()
            try:
                con = self._connection
                con.execute("BEGIN IMMEDIATE")
                try:
                    self._fence(owner_token, now, con)
                    row = con.execute(f"SELECT {_REQUEST_COLUMNS} FROM requests WHERE request_id = ?",
                                      (request_id,)).fetchone()
                    if row is not None:
                        receipt = self._row_receipt(row)
                        con.execute("ROLLBACK")
                        if receipt.batch_digest != batch.batch_digest:
                            raise PersistenceError("REQUEST_CONFLICT", "Request id reused with a different batch")
                        return receipt
                    revision = con.execute("SELECT revision FROM state WHERE id = 1").fetchone()[0]
                    if expected_revision != revision:
                        con.execute("ROLLBACK")
                        return CommitReceipt("CONFLICT", request_id, revision)
                    for key in batch.deletes:
                        con.execute("DELETE FROM records WHERE key = ?", (key,))
                    for key, value in batch.puts.items():
                        con.execute("INSERT OR REPLACE INTO records (key, value) VALUES (?, ?)",
                                    (key, self._dump(value)))
                    record_count = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
                    request_count = con.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
                    if record_count > self._budgets[0] or request_count >= self._budgets[1]:
                        raise PersistenceError("STATE_BUDGET", "State or request retention budget exhausted")
                    receipt = CommitReceipt("COMMITTED", request_id, revision + 1, uuid.uuid4().hex,
                                            thaw(batch.result), batch.batch_digest, batch.command_digest, True)
                    con.execute(f"INSERT INTO requests ({_REQUEST_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (receipt.status, receipt.request_id, receipt.revision, receipt.commit_id,
                                 self._dump(receipt.result) if receipt.result is not None else None,
                                 receipt.batch_digest, receipt.command_digest, 1))
                    con.execute("UPDATE state SET revision = ? WHERE id = 1", (revision + 1,))
                    con.execute("COMMIT")
                    return receipt
                except BaseException:
                    self._safe_rollback(con)
                    raise
            except sqlite3.Error as error:
                raise _unavailable(error) from error

    def read(self, key):
        if type(key) is not str or not key:
            raise PersistenceError("INVALID_PERSISTENCE_VALUE", "record key must be a nonempty string")
        with self._lock:
            self._require_open()
            try:
                row = self._connection.execute("SELECT value FROM records WHERE key = ?", (key,)).fetchone()
            except sqlite3.Error as error:
                raise _unavailable(error) from error
            if row is None:
                raise KeyError(key)
            return json.loads(row[0])

    def query(self, prefix, cursor=None, limit=100):
        if type(prefix) is not str or type(limit) is not int or not 1 <= limit <= 1000:
            raise PersistenceError("INVALID_QUERY", "Expected a prefix and a limit between 1 and 1000")
        with self._lock:
            self._require_open()
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
                                next_cursor, self._binding_revision)

    def close_cursor(self, cursor):
        with self._lock:
            if type(cursor) is not str or cursor not in self._cursors:
                raise PersistenceError("INVALID_CURSOR", "Cursor is invalid or closed")
            snapshot_id = cursor.split(":")[0]
            del self._snapshots[snapshot_id]
            self._cursors = {c for c in self._cursors if not c.startswith(snapshot_id + ":")}

    def checkpoint(self, expected_revision, request_id, owner_token):
        with self._lock:
            self._require_open()
            self.renew_owner(owner_token)
            command = digest({"operation": "checkpoint", "expected_revision": expected_revision})
            old = self.get_commit(request_id)
            if old.status == "COMMITTED":
                if old.command_digest != command:
                    raise PersistenceError("REQUEST_CONFLICT", "Request id belongs to another command")
                return old.result
            view = self.load_recovery_view()
            if expected_revision != view.revision:
                raise PersistenceError("REVISION_CONFLICT", "Checkpoint revision no longer matches")
            try:
                if self._connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] >= self._budgets[3]:
                    raise PersistenceError("CHECKPOINT_BUDGET", "Checkpoint budget exhausted")
            except sqlite3.Error as error:
                raise _unavailable(error) from error
            checkpoint_id = uuid.uuid4().hex
            self.commit(StateBatch(result=checkpoint_id, command_digest=command), expected_revision,
                        request_id, owner_token)
            payload = json.dumps({"revision": view.revision, "records": thaw(view.records)},
                                 ensure_ascii=True, separators=(",", ":"))
            try:
                con = self._connection
                con.execute("BEGIN IMMEDIATE")
                try:
                    con.execute("INSERT INTO checkpoints VALUES (?, ?, ?)", (checkpoint_id, view.revision, payload))
                    con.execute("COMMIT")
                except BaseException:
                    self._safe_rollback(con)
                    raise
            except sqlite3.Error as error:
                raise _unavailable(error) from error
            return checkpoint_id

    def load_checkpoint(self, checkpoint_id):
        with self._lock:
            self._require_open()
            try:
                row = self._connection.execute("SELECT revision, payload FROM checkpoints WHERE checkpoint_id = ?",
                                               (checkpoint_id,)).fetchone()
            except sqlite3.Error as error:
                raise _unavailable(error) from error
            if row is None:
                raise PersistenceError("CHECKPOINT_NOT_FOUND", "Checkpoint does not exist")
            data = json.loads(row[1])
            return RecoveryView(data["revision"], data["records"], binding_revision=self._binding_revision)

    def close(self):
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                finally:
                    self._connection = None


class SQLiteArtifactStore:
    """Content-addressed artifact store sharing the state store's connection.

    The caller owns reference-reachability decisions; delete_unreferenced
    removes the blob it is told to remove (platform standard §15). The full
    release publication protocol is a later slice (T12).
    """
    def __init__(self, store):
        self._store = store

    def put_immutable(self, artifact_digest, content):
        if (type(artifact_digest) is not str or not artifact_digest
                or not isinstance(content, (bytes, bytearray, memoryview))):
            raise PersistenceError("INVALID_PERSISTENCE_VALUE", "Artifact digest and bytes are required")
        content = bytes(content)
        if hashlib.sha256(content).hexdigest() != artifact_digest:
            raise PersistenceError("ARTIFACT_DIGEST_MISMATCH", "Artifact bytes do not match their digest")
        store = self._store
        with store._lock:
            store._require_open()
            try:
                con = store._connection
                con.execute("BEGIN IMMEDIATE")
                try:
                    con.execute("INSERT OR IGNORE INTO artifacts (digest, content, size) VALUES (?, ?, ?)",
                                (artifact_digest, content, len(content)))
                    con.execute("COMMIT")
                except BaseException:
                    store._safe_rollback(con)
                    raise
            except sqlite3.Error as error:
                raise _unavailable(error) from error

    def get(self, artifact_digest):
        store = self._store
        with store._lock:
            store._require_open()
            try:
                row = store._connection.execute("SELECT content FROM artifacts WHERE digest = ?",
                                                (artifact_digest,)).fetchone()
            except sqlite3.Error as error:
                raise _unavailable(error) from error
            if row is None:
                raise PersistenceError("MISSING_ARTIFACT", "Referenced artifact is missing")
            return bytes(row[0])

    def verify(self, artifact_digest):
        store = self._store
        with store._lock:
            store._require_open()
            try:
                row = store._connection.execute("SELECT 1 FROM artifacts WHERE digest = ?",
                                                (artifact_digest,)).fetchone()
            except sqlite3.Error as error:
                raise _unavailable(error) from error
            return row is not None

    def delete_unreferenced(self, artifact_digest, reference_revision):
        if type(reference_revision) is not int or reference_revision < 0:
            raise PersistenceError("INVALID_PERSISTENCE_VALUE", "Reference revision must be a nonnegative integer")
        store = self._store
        with store._lock:
            store._require_open()
            try:
                con = store._connection
                con.execute("BEGIN IMMEDIATE")
                try:
                    con.execute("DELETE FROM artifacts WHERE digest = ?", (artifact_digest,))
                    con.execute("COMMIT")
                except BaseException:
                    store._safe_rollback(con)
                    raise
            except sqlite3.Error as error:
                raise _unavailable(error) from error


class SQLiteProvider:
    """Durable single-instance provider; capabilities honestly declare the fault scope."""
    def __init__(self, resolved_config, binding, *, time_fn=None):
        self.config = resolved_config
        self.binding = binding
        self.state = SQLiteStateStore(resolved_config["path"], binding_revision=binding.binding_revision,
                                      namespace=binding.namespace, binding_id=binding.binding_id,
                                      lease_ttl_seconds=resolved_config["lease_ttl_seconds"],
                                      busy_timeout_ms=resolved_config["busy_timeout_ms"],
                                      max_records=resolved_config["max_records"],
                                      max_requests=resolved_config["max_requests"],
                                      max_snapshots=resolved_config["max_snapshots"],
                                      max_checkpoints=resolved_config["max_checkpoints"],
                                      time_fn=time_fn)
        self.artifacts = SQLiteArtifactStore(self.state)

    def describe(self):
        return ProviderDescriptor(PROVIDER_ID, CONFIG_SCHEMA, self.state.capabilities)

    def close(self):
        self.state.close()


def build(resolved_config, binding, *, time_fn=None):
    return SQLiteProvider(resolved_config, binding, time_fn=time_fn)
