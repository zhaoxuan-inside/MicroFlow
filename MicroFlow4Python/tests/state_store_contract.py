"""Shared StateStore contract suite (T07): one protocol, every provider.

The implementation plan requires real providers to pass the same contract
tests as the memory stand-in. Concrete suites implement ``make_store`` and
``make_foreign_token`` (and set ``DURABLE_RECEIPT``); every scenario below
runs unchanged on each store.
"""
import unittest
from dataclasses import replace

from microflow.errors import PersistenceError
from microflow.persistence import (Capabilities, CommitReceipt, OwnerToken, ProviderDescriptor,
                                   RecoveryView, StateBatch)


class StateStoreContract:
    """Protocol scenarios every StateStore implementation must satisfy.

    Plain mixin: concrete suites combine it with unittest.TestCase so this
    base class itself is never collected as tests.
    """

    DURABLE_RECEIPT: bool

    def make_store(self, **budgets):
        raise NotImplementedError

    def make_foreign_token(self, store):
        raise NotImplementedError

    def setUp(self):
        self.store = self.make_store()
        self.owner = self.store.acquire_owner("test")

    def commit(self, batch, request="request"):
        return self.store.commit(batch, self.store.load_recovery_view().revision, request, self.owner)

    def test_atomic_batch_replay_and_digest_conflict(self):
        batch = StateBatch({"a": [1]}, result={"ok": True}, command_digest="command")
        receipt = self.commit(batch)
        self.assertEqual(receipt, self.store.commit(batch, 0, "request", self.owner))
        for changed in (replace(batch, result=False), replace(batch, command_digest="other")):
            with self.assertRaisesRegex(PersistenceError, "REQUEST_CONFLICT"):
                self.commit(changed)
        self.assertEqual(receipt.durable, self.DURABLE_RECEIPT)
        with self.assertRaises(TypeError):
            receipt.result["ok"] = False
        self.assertEqual(self.store.load_recovery_view().revision, 1)

    def test_owner_fencing_and_exclusivity(self):
        foreign = self.make_foreign_token(self.store)
        with self.assertRaisesRegex(PersistenceError, "OWNER_FENCED"):
            self.store.renew_owner(foreign)
        with self.assertRaisesRegex(PersistenceError, "OWNER_BUSY"):
            self.store.acquire_owner("another")
        self.store.release_owner(self.owner)
        for token in (None, self.owner):
            with self.assertRaisesRegex(PersistenceError, "OWNER_FENCED"):
                self.store.renew_owner(token)
        current = self.store.acquire_owner("test")
        self.assertGreater(current.generation, self.owner.generation)
        with self.assertRaisesRegex(PersistenceError, "OWNER_FENCED"):
            self.commit(StateBatch({"a": 1}))

    def test_snapshot_pages_survive_concurrent_changes_and_are_replayable(self):
        self.commit(StateBatch({"a1": 1, "a2": 2, "a3": 3}))
        first = self.store.query("a", limit=1)
        self.commit(StateBatch({"a2": 20, "a0": 0}, ("a3",)), "change")
        second = self.store.query("a", first.cursor, 1)
        last = self.store.query("a", second.cursor, 1)
        self.assertEqual([first.revision, second.revision, last.revision], [1, 1, 1])
        self.assertEqual(dict(second.records), {"a2": 2})
        self.assertEqual(dict(last.records), {"a3": 3})
        self.assertIsNone(last.cursor)
        self.assertEqual(second, self.store.query("a", first.cursor, 1))
        with self.assertRaisesRegex(PersistenceError, "INVALID_CURSOR"):
            self.store.query("other", first.cursor)
        with self.assertRaisesRegex(PersistenceError, "INVALID_CURSOR"):
            self.make_store().query("a", first.cursor)
        self.store.close_cursor(first.cursor)
        with self.assertRaisesRegex(PersistenceError, "INVALID_CURSOR"):
            self.store.query("a", second.cursor)

    def test_checkpoint_is_immutable_and_request_idempotent(self):
        self.commit(StateBatch({"a": [1]}))
        checkpoint = self.store.checkpoint(1, "checkpoint", self.owner)
        self.commit(StateBatch({"a": [2]}), "change")
        self.assertEqual(checkpoint, self.store.checkpoint(1, "checkpoint", self.owner))
        snapshot = self.store.load_checkpoint(checkpoint)
        self.assertEqual(snapshot.revision, 1)
        self.assertEqual(snapshot.records["a"], (1,))
        with self.assertRaisesRegex(PersistenceError, "REQUEST_CONFLICT"):
            self.store.checkpoint(3, "checkpoint", self.owner)

    def test_budgets_fail_before_mutating(self):
        store = self.make_store(max_records=1, max_requests=1)
        owner = store.acquire_owner("test")
        with self.assertRaisesRegex(PersistenceError, "STATE_BUDGET"):
            store.commit(StateBatch({"a": 1, "b": 2}), 0, "too-big", owner)
        self.assertEqual(store.load_recovery_view().revision, 0)
        store.commit(StateBatch({"a": 1}), 0, "one", owner)
        with self.assertRaisesRegex(PersistenceError, "STATE_BUDGET"):
            store.commit(StateBatch({"a": 2}), 1, "two", owner)
        self.assertEqual(store.read("a"), 1)
        self.assertEqual(store.get_commit("one").status, "COMMITTED")

    def test_snapshot_and_checkpoint_budgets(self):
        store = self.make_store(max_snapshots=1, max_checkpoints=1)
        owner = store.acquire_owner("test")
        store.commit(StateBatch({"a": 1, "b": 2}), 0, "data", owner)
        page = store.query("", limit=1)
        with self.assertRaisesRegex(PersistenceError, "SNAPSHOT_BUDGET"):
            store.query("", limit=1)
        store.close_cursor(page.cursor)
        self.assertIsNotNone(store.query("", limit=1).cursor)
        store.checkpoint(1, "cp", owner)
        with self.assertRaisesRegex(PersistenceError, "CHECKPOINT_BUDGET"):
            store.checkpoint(2, "cp2", owner)
        self.assertEqual(store.load_recovery_view().revision, 2)

    def test_revision_conflict_is_atomic(self):
        self.commit(StateBatch({"a": 1}))
        receipt = self.store.commit(StateBatch({"b": 2}, ("a",)), 0, "stale", self.owner)
        self.assertEqual(receipt.status, "CONFLICT")
        self.assertEqual(dict(self.store.load_recovery_view().records), {"a": 1})
        self.assertEqual(self.store.get_commit("stale").status, "NOT_COMMITTED")

    def test_protocol_objects_reject_invalid_values(self):
        cases = (lambda: StateBatch({"a": 1}, ("a",)), lambda: StateBatch(deletes=("a", "a")),
                 lambda: RecoveryView(True, {}), lambda: CommitReceipt("COMMITTED", "x", durable=1),
                 lambda: OwnerToken("owner", 0), lambda: Capabilities(durable_ack=1))
        for create in cases:
            with self.assertRaises(PersistenceError):
                create()
        descriptor = ProviderDescriptor("test", {"type": "object"}, Capabilities())
        with self.assertRaises(TypeError):
            descriptor.config_schema["type"] = "string"
