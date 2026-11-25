import concurrent.futures
import unittest
from types import SimpleNamespace
from dataclasses import replace
from microflow.coordinator import Coordinator
from microflow.errors import PersistenceError, ContractError
from microflow.persistence import (CommitReceipt, StateBatch, Capabilities,
                                   ProviderDescriptor, StorageBinding, validate_provider)
from microflow.testing import MemoryStateStore
from microflow.values import digest

from tests.state_store_contract import StateStoreContract


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


class EventDeliveryFacesTests(unittest.TestCase):
    """pending_events / acknowledge_event：状态库是唯一投递账本（D2）。"""

    def _intent(self, event_id, sequence=1, aggregate="exec-1", delivery="PENDING"):
        content = digest({"event": event_id, "sequence": sequence})
        return {"protocol": "microflow-event-v1", "event_id": event_id,
                "event_type": "microflow.execution", "schema_version": "1",
                "aggregate_key": aggregate, "sequence": sequence, "payload": {},
                "execution_id": aggregate, "release_id": "r", "occurred_at": 1.0,
                "recorded_at": float(sequence), "content_digest": content,
                "delivery": delivery}

    def _write(self, coordinator, intent):
        def decide(view):
            return StateBatch({"event-intent/" + intent["event_id"]: intent}), {"ok": True}
        return coordinator.transact(decide, request_id="write-" + intent["event_id"],
                                    request_digest=digest({"write": intent["event_id"]}))

    def _coordinator(self):
        return Coordinator(MemoryStateStore())

    def test_pending_returns_only_pending_in_recorded_order(self):
        coordinator = self._coordinator()
        self._write(coordinator, self._intent("a", sequence=3))
        self._write(coordinator, self._intent("b", sequence=1, delivery="DELIVERED"))
        self._write(coordinator, self._intent("c", sequence=2))
        pending = coordinator.pending_events()
        self.assertEqual([record["event_id"] for record in pending], ["c", "a"])  # recorded_at 最旧优先
        self.assertEqual(pending[0]["delivery"], "PENDING")

    def test_acknowledge_flips_and_replays_return_the_stored_result(self):
        coordinator = self._coordinator()
        intent = self._intent("evt-1")
        self._write(coordinator, intent)
        request = digest({"ack": "evt-1", "attempt": 1})
        first = coordinator.acknowledge_event("evt-1", intent["content_digest"], request_id=request)
        self.assertEqual(first, {"status": "delivered", "event_id": "evt-1"})
        self.assertEqual(coordinator.pending_events(), ())
        replay = coordinator.acknowledge_event("evt-1", intent["content_digest"], request_id=request)
        self.assertEqual(replay, first)

    def test_reacknowledge_with_a_fresh_request_is_a_recorded_noop(self):
        coordinator = self._coordinator()
        intent = self._intent("evt-2")
        self._write(coordinator, intent)
        coordinator.acknowledge_event("evt-2", intent["content_digest"],
                                      request_id=digest({"ack": "evt-2", "attempt": 1}))
        second = coordinator.acknowledge_event("evt-2", intent["content_digest"],
                                                request_id=digest({"ack": "evt-2", "attempt": 2}))
        self.assertEqual(second, {"status": "already-delivered", "event_id": "evt-2"})

    def test_digest_mismatch_and_unknown_events_are_rejected(self):
        coordinator = self._coordinator()
        intent = self._intent("evt-3")
        self._write(coordinator, intent)
        with self.assertRaisesRegex(PersistenceError, "EVENT_ID_CONFLICT"):
            coordinator.acknowledge_event("evt-3", "0" * 64, request_id=digest({"ack": "bad"}))
        with self.assertRaisesRegex(PersistenceError, "UNKNOWN_EVENT"):
            coordinator.acknowledge_event("missing", intent["content_digest"],
                                          request_id=digest({"ack": "missing"}))

    def test_argument_validation_is_explicit(self):
        coordinator = self._coordinator()
        with self.assertRaisesRegex(PersistenceError, "INVALID_REQUEST"):
            coordinator.pending_events(limit=0)
        with self.assertRaisesRegex(PersistenceError, "INVALID_REQUEST"):
            coordinator.acknowledge_event("", "d", request_id="r")


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


class MemoryStateStoreContract(StateStoreContract, unittest.TestCase):
    """The memory double passes the same contract scenarios as real providers."""

    DURABLE_RECEIPT = False

    def make_store(self, **budgets):
        return MemoryStateStore(**budgets)

    def make_foreign_token(self, store):
        return type(store)().acquire_owner("test")


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
