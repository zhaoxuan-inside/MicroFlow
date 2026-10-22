import concurrent.futures
import unittest
from types import SimpleNamespace
from dataclasses import replace
from microflow.coordinator import Coordinator
from microflow.errors import PersistenceError, ContractError
from microflow.persistence import (CommitReceipt, StateBatch, RecoveryView, OwnerToken, Capabilities,
                                   ProviderDescriptor, StorageBinding, validate_provider)
from microflow.testing import MemoryStateStore
from microflow.values import digest


def increment(view):
    value = view.records.get("count", 0) + 1
    return StateBatch({"count": value}), {"count": value}


class FaultStore(MemoryStateStore):
    mode = "normal"
    calls = 0

    def commit(self, *args):
        self.calls += 1
        if self.mode == "before":
            raise OSError("lost connection")
        if self.mode == "unknown":
            return CommitReceipt("UNKNOWN", args[2])
        receipt = super().commit(*args)
        if self.mode == "after":
            raise OSError("lost acknowledgment")
        if self.mode == "corrupt":
            return replace(receipt, batch_digest="wrong")
        return receipt

    def get_commit(self, request_id):
        if self.mode == "unknown":
            return CommitReceipt("UNKNOWN", request_id)
        return super().get_commit(request_id)


class CoordinatorTests(unittest.TestCase):
    def test_replay_returns_original_result_without_deciding(self):
        store = MemoryStateStore()
        coordinator = Coordinator(store)
        result = coordinator.transact(increment, "one", request_digest=digest({"op": "increment"}))
        result["count"] = 99
        coordinator.transact(increment)
        coordinator.close()
        coordinator = Coordinator(store)
        replay = coordinator.transact(lambda _: self.fail("replayed decision"), "one",
                                      request_digest=digest({"op": "increment"}))
        self.assertEqual(replay, {"count": 1})
        self.assertEqual(store.read("count"), 2)
        with self.assertRaisesRegex(PersistenceError, "REQUEST_CONFLICT"):
            coordinator.transact(increment, "one", request_digest="different")

    def test_lost_acknowledgment_queries_original_receipt(self):
        store = FaultStore()
        store.mode = "after"
        coordinator = Coordinator(store)
        self.assertEqual(coordinator.transact(increment), {"count": 1})
        self.assertEqual(store.calls, 1)

    def test_unknown_blocks_writes_until_authoritatively_resolved(self):
        store = FaultStore()
        coordinator = Coordinator(store)
        store.mode = "unknown"
        with self.assertRaisesRegex(PersistenceError, "COMMIT_IN_DOUBT"):
            coordinator.transact(increment)
        with self.assertRaisesRegex(PersistenceError, "COMMIT_IN_DOUBT"):
            coordinator.transact(lambda _: self.fail("decision while uncertain"))
        self.assertEqual(store.calls, 1)
        store.mode = "normal"
        self.assertEqual(coordinator.transact(increment), {"count": 1})

    def test_exception_before_commit_does_not_retry_automatically(self):
        store = FaultStore()
        coordinator = Coordinator(store)
        store.mode = "before"
        with self.assertRaisesRegex(PersistenceError, "COMMIT_FAILED"):
            coordinator.transact(increment)
        self.assertEqual(store.calls, 1)
        self.assertEqual(store.load_recovery_view().revision, 0)

    def test_corrupt_confirmation_requires_lookup_before_next_write(self):
        store = FaultStore()
        coordinator = Coordinator(store)
        store.mode = "corrupt"
        with self.assertRaisesRegex(PersistenceError, "PROVIDER_PROTOCOL"):
            coordinator.transact(increment)
        store.mode = "normal"
        self.assertEqual(coordinator.transact(increment), {"count": 2})

    def test_stable_readonly_result_is_recorded(self):
        store = MemoryStateStore()
        coordinator = Coordinator(store)
        self.assertEqual(coordinator.transact(lambda _: (None, [1]), "read", request_digest="read"), [1])
        self.assertEqual(coordinator.transact(lambda _: self.fail(), "read", request_digest="read"), [1])

    def test_query_outage_keeps_gate_closed(self):
        class Outage(FaultStore):
            unavailable = True
            def get_commit(self, request_id):
                if self.unavailable:
                    raise OSError("offline")
                return super().get_commit(request_id)
        store = Outage()
        coordinator = Coordinator(store)
        store.mode = "after"
        for _ in range(2):
            with self.assertRaisesRegex(PersistenceError, "COMMIT_IN_DOUBT"):
                coordinator.transact(increment)
        self.assertEqual(store.calls, 1)
        store.unavailable = False
        store.mode = "normal"
        self.assertEqual(coordinator.transact(increment), {"count": 2})

    def test_unknown_ack_after_commit_is_resolved_without_reexecution(self):
        class UnknownAck(MemoryStateStore):
            def commit(self, *args):
                super().commit(*args)
                return CommitReceipt("UNKNOWN", args[2])
        store = UnknownAck()
        coordinator = Coordinator(store)
        self.assertEqual(coordinator.transact(increment), {"count": 1})
        self.assertEqual(store.load_recovery_view().revision, 1)

    def test_result_corruption_cannot_pass_batch_hash_check(self):
        class WrongResult(MemoryStateStore):
            def commit(self, *args):
                return replace(super().commit(*args), result={"count": 999})
        coordinator = Coordinator(WrongResult())
        with self.assertRaisesRegex(PersistenceError, "PROVIDER_PROTOCOL"):
            coordinator.transact(increment)

    def test_durable_receipt_required_even_when_capabilities_claimed(self):
        class FalseDurable(MemoryStateStore):
            capabilities = Capabilities(atomic_batch=True, conditional_write=True,
                request_deduplication=True, durable_ack=True, consistent_recovery=True)
        coordinator = Coordinator(FalseDurable(), durable=True)
        with self.assertRaisesRegex(PersistenceError, "PROVIDER_PROTOCOL"):
            coordinator.transact(increment)

    def test_revision_and_request_validation_before_decision(self):
        coordinator = Coordinator(MemoryStateStore())
        for options in ({"request_id": "id"}, {"expected_revision": True}, {"expected_revision": 1}):
            with self.assertRaises(PersistenceError):
                coordinator.transact(lambda _: self.fail(), **options)
        coordinator.close()
        with self.assertRaisesRegex(PersistenceError, "COORDINATOR_CLOSED"):
            coordinator.transact(increment)

    def test_ephemeral_provider_cannot_claim_durable(self):
        with self.assertRaisesRegex(PersistenceError, "CAPABILITY_REQUIRED"):
            Coordinator(MemoryStateStore(), durable=True)

    def test_concurrent_decisions_serialize(self):
        store = MemoryStateStore()
        coordinator = Coordinator(store)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda _: coordinator.transact(increment)["count"], range(100)))
        self.assertEqual(sorted(values), list(range(1, 101)))

    def test_definite_conflict_retries_pure_decision(self):
        class Contended(MemoryStateStore):
            conflict = True
            def commit(self, *args):
                if self.conflict:
                    self.conflict = False
                    return CommitReceipt("CONFLICT", args[2])
                return super().commit(*args)
        coordinator = Coordinator(Contended())
        self.assertEqual(coordinator.transact(increment), {"count": 1})
        coordinator.store.conflict = True
        with self.assertRaisesRegex(PersistenceError, "REVISION_CONFLICT"):
            coordinator.transact(increment, "control", request_digest="control")


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStateStore()
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
        self.assertFalse(receipt.durable)
        with self.assertRaises(TypeError):
            receipt.result["ok"] = False
        self.assertEqual(self.store.load_recovery_view().revision, 1)

    def test_owner_fencing_and_exclusivity(self):
        foreign = MemoryStateStore().acquire_owner("test")
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
            MemoryStateStore().query("a", first.cursor)
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
        store = MemoryStateStore(max_records=1, max_requests=1)
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
        store = MemoryStateStore(max_snapshots=1, max_checkpoints=1)
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


class ProviderValidationTests(unittest.TestCase):
    def setUp(self):
        self.config = {"path": "isolated-test"}
        self.binding = StorageBinding("test", "runtime", "tenant", "rev-1", digest(self.config))
        self.descriptor = ProviderDescriptor("test", {"type": "object", "required": ["path"],
            "properties": {"path": {"type": "string"}}}, MemoryStateStore.capabilities)
        # Structural stub only; no artifact medium is exercised here.
        artifacts = SimpleNamespace(**{name: lambda *args: None for name in
            ("put_immutable", "get", "verify", "delete_unreferenced")})
        self.provider = SimpleNamespace(binding=self.binding, state=MemoryStateStore(),
                                        artifacts=artifacts, describe=lambda: self.descriptor)

    def validate(self, **options):
        return validate_provider(self.provider, self.config, expected_binding=self.binding, **options)

    def test_descriptor_and_bound_configuration(self):
        self.assertEqual(self.validate(), self.descriptor)
        with self.assertRaisesRegex(PersistenceError, "CAPABILITY_REQUIRED"):
            self.validate(durable=True)
        with self.assertRaisesRegex(PersistenceError, "CAPABILITY_REQUIRED"):
            self.validate(ownership_scope="cluster")

    def test_binding_and_digest_mismatch(self):
        self.provider.binding = replace(self.binding, binding_revision="rev-2")
        with self.assertRaisesRegex(PersistenceError, "BINDING_MISMATCH"):
            self.validate()
        self.provider.binding = self.binding
        self.config["path"] = "different"
        with self.assertRaisesRegex(PersistenceError, "BINDING_MISMATCH"):
            self.validate()

    def test_config_shape_and_required_operations(self):
        self.config["path"] = 42
        with self.assertRaises(ContractError):
            self.validate()
        self.config["path"] = "isolated-test"
        self.provider.artifacts.verify = None
        with self.assertRaisesRegex(PersistenceError, "PROVIDER_PROTOCOL"):
            self.validate()

    def test_capabilities_and_protocol_version_mismatch(self):
        self.provider.state.capabilities = replace(MemoryStateStore.capabilities, durable_ack=True)
        with self.assertRaisesRegex(PersistenceError, "PROVIDER_PROTOCOL"):
            self.validate()
        with self.assertRaisesRegex(PersistenceError, "UNSUPPORTED_PROVIDER_PROTOCOL"):
            replace(self.descriptor, protocol_version="unknown")
