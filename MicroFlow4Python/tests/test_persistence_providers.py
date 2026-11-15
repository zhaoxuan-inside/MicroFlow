"""Persistence subpackage: factory, memory/sqlite providers, durable end-to-end, decoupling guard."""
import hashlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from microflow.compiler import compile_release
from microflow.coordinator import Coordinator
from microflow.errors import PersistenceError
from microflow.persistence import (OwnerToken, StateBatch, create_provider,
                                   describe_provider_config, validate_provider)
from microflow.persistence.memory import MemoryProvider
from microflow.persistence.sqlite import SQLiteStateStore
from microflow.registry import Registry
from microflow.scheduling import ExecutionCommands
from microflow.values import digest, thaw
from microflow.worker import ScheduledRuntime

from tests.state_store_contract import StateStoreContract
from tests.test_compiler import EPHEMERAL, INTEGER_MAP, flow, method


class ProviderFactoryTests(unittest.TestCase):
    def test_default_kind_is_memory(self):
        provider = create_provider()
        self.assertIsInstance(provider, MemoryProvider)
        self.assertEqual(provider.describe().provider_id, "microflow-memory")
        owner = provider.state.acquire_owner("test")
        receipt = provider.state.commit(StateBatch({"k": 1}), 0, "r", owner)
        self.assertFalse(receipt.durable)
        self.assertEqual(dict(provider.state.load_recovery_view().records), {"k": 1})

    def test_closed_kind_set_rejects_unknown_kinds(self):
        for kind in ("redis", "postgres", "", 42, None):
            with self.subTest(kind=kind), self.assertRaisesRegex(PersistenceError, "UNKNOWN_PROVIDER_KIND"):
                create_provider(kind)
            with self.subTest(kind=kind), self.assertRaisesRegex(PersistenceError, "UNKNOWN_PROVIDER_KIND"):
                describe_provider_config(kind)

    def test_config_validation_rejects_bad_shapes(self):
        cases = (("sqlite", {}), ("sqlite", {"path": "x.db", "max_records": 0}),
                 ("memory", {"bogus": 1}), ("memory", ["not", "a", "map"]),
                 ("sqlite", {"path": "x.db", "lease_ttl_seconds": 0.5}))
        for kind, config in cases:
            with self.subTest(kind=kind), self.assertRaisesRegex(PersistenceError, "PROVIDER_CONFIG_INVALID"):
                create_provider(kind, config)

    def test_describe_provider_config_is_versioned_and_honest(self):
        description = describe_provider_config("sqlite")
        self.assertEqual(description["protocol"], "microflow-provider-config-v1")
        self.assertEqual(description["schema_version"], "microflow-sqlite-config-v1")
        self.assertTrue(description["capabilities"]["durable_ack"])
        self.assertEqual(description["capabilities"]["scope"], "instance")
        memory = describe_provider_config("memory")
        self.assertFalse(memory["capabilities"]["durable_ack"])
        description["schema"]["properties"].clear()
        self.assertEqual(describe_provider_config("sqlite")["schema"]["properties"]["path"]["type"], "string")

    def test_binding_is_deterministic_and_namespace_sensitive(self):
        first = create_provider("memory", {"namespace": "one"})
        second = create_provider("memory", {"namespace": "one"})
        self.assertEqual(first.binding, second.binding)
        other = create_provider("memory", {"namespace": "two"})
        self.assertNotEqual(first.binding.binding_revision, other.binding.binding_revision)


class MemoryProviderTests(unittest.TestCase):
    def test_memory_provider_is_rejected_for_durable_execution(self):
        provider = create_provider("memory")
        validate_provider(provider, thaw(provider.config), expected_binding=provider.binding)
        with self.assertRaisesRegex(PersistenceError, "CAPABILITY_REQUIRED"):
            validate_provider(provider, thaw(provider.config), expected_binding=provider.binding, durable=True)
        with self.assertRaisesRegex(PersistenceError, "CAPABILITY_REQUIRED"):
            Coordinator(provider.state, durable=True)


class SQLiteStateStoreContract(StateStoreContract, unittest.TestCase):
    """The SQLite store passes the same contract scenarios as the memory double."""

    DURABLE_RECEIPT = True

    def setUp(self):
        self._stores = []
        self._dirs = []
        super().setUp()

    def make_store(self, **budgets):
        tmp = tempfile.TemporaryDirectory()
        self._dirs.append(tmp)
        store = SQLiteStateStore(str(Path(tmp.name) / "state.db"), binding_revision="sqlite-contract", **budgets)
        self._stores.append(store)
        return store

    def make_foreign_token(self, store):
        return OwnerToken("intruder", 10_000)

    def tearDown(self):
        for store in self._stores:
            store.close()
        for tmp in self._dirs:
            tmp.cleanup()


class SQLiteStoreTests(unittest.TestCase):
    def test_reopen_same_file_preserves_state_and_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.db")
            first = SQLiteStateStore(path, binding_revision="reopen")
            owner = first.acquire_owner("test")
            first.commit(StateBatch({"k": [1, 2]}, result={"ok": True}, command_digest="c"), 0, "r", owner)
            first.close()
            second = SQLiteStateStore(path, binding_revision="reopen")
            view = second.load_recovery_view()
            self.assertEqual(view.revision, 1)
            self.assertEqual(view.records["k"], (1, 2))
            receipt = second.get_commit("r")
            self.assertEqual((receipt.status, receipt.durable), ("COMMITTED", True))
            self.assertEqual(dict(receipt.result), {"ok": True})
            second.close()

    def test_checkpoint_survives_reopen_and_stays_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.db")
            first = SQLiteStateStore(path, binding_revision="cp")
            owner = first.acquire_owner("test")
            first.commit(StateBatch({"k": 1}), 0, "data", owner)
            checkpoint = first.checkpoint(1, "cp", owner)
            first.commit(StateBatch({"k": 2}), 1, "data-2", owner)
            self.assertEqual(first.load_recovery_view().revision, 2)
            first.release_owner(owner)
            first.close()
            second = SQLiteStateStore(path, binding_revision="cp")
            snapshot = second.load_checkpoint(checkpoint)
            self.assertEqual(snapshot.revision, 1)
            self.assertEqual(snapshot.records["k"], 1)
            # Same request id and same command digest replay across reopen.
            replay = second.checkpoint(1, "cp", second.acquire_owner("test"))
            self.assertEqual(replay, checkpoint)
            second.close()

    def test_reopen_rejects_foreign_binding_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.db")
            SQLiteStateStore(path, binding_revision="one", namespace="main").close()
            with self.assertRaisesRegex(PersistenceError, "BINDING_MISMATCH"):
                SQLiteStateStore(path, binding_revision="two")
            with self.assertRaisesRegex(PersistenceError, "BINDING_MISMATCH"):
                SQLiteStateStore(path, binding_revision="one", namespace="other")

    def test_get_commit_returns_unknown_while_a_writer_holds_the_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.db")
            store = SQLiteStateStore(path, binding_revision="probe")
            blocker = sqlite3.connect(path, isolation_level=None)
            blocker.execute("BEGIN IMMEDIATE")
            try:
                self.assertEqual(store.get_commit("missing").status, "UNKNOWN")
            finally:
                blocker.execute("ROLLBACK")
                blocker.close()
            self.assertEqual(store.get_commit("missing").status, "NOT_COMMITTED")
            store.close()

    def test_expired_lease_takeover_advances_generation_and_fences_old_owner(self):
        clock = {"now": 1000.0}
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "lease.db")
            store = SQLiteStateStore(path, binding_revision="lease", lease_ttl_seconds=30,
                                     time_fn=lambda: clock["now"])
            first = store.acquire_owner("first")
            clock["now"] += 31
            second = store.acquire_owner("second")
            self.assertEqual(second.generation, first.generation + 1)
            with self.assertRaisesRegex(PersistenceError, "OWNER_FENCED"):
                store.commit(StateBatch({"k": 1}), 0, "r", first)
            receipt = store.commit(StateBatch({"k": 1}), 0, "r", second)
            self.assertEqual(receipt.status, "COMMITTED")
            store.close()

    def test_artifacts_are_content_addressed_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = create_provider("sqlite", {"path": str(Path(tmp) / "artifacts.db")})
            content = b"release-bytes"
            with self.assertRaisesRegex(PersistenceError, "ARTIFACT_DIGEST_MISMATCH"):
                provider.artifacts.put_immutable("0" * 64, content)
            name = hashlib.sha256(content).hexdigest()
            provider.artifacts.put_immutable(name, content)
            provider.artifacts.put_immutable(name, content)
            self.assertEqual(provider.artifacts.get(name), content)
            self.assertTrue(provider.artifacts.verify(name))
            self.assertFalse(provider.artifacts.verify("f" * 64))
            provider.artifacts.delete_unreferenced(name, 0)
            with self.assertRaisesRegex(PersistenceError, "MISSING_ARTIFACT"):
                provider.artifacts.get(name)
            provider.close()


class CrossProcessFencingTests(unittest.TestCase):
    def test_exited_process_lease_blocks_takeover_until_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "fencing.db")
            revision = digest({"drill": "cross-process-fencing"})
            source_root = str(Path(__file__).resolve().parent.parent / "src")
            child = ("import sys;"
                     f"sys.path.insert(0, {source_root!r});"
                     "from microflow.persistence.sqlite import SQLiteStateStore;"
                     f"store = SQLiteStateStore({path!r}, binding_revision={revision!r}, lease_ttl_seconds=1);"
                     "token = store.acquire_owner('child');"
                     "print(token.generation)")
            completed = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            child_generation = int(completed.stdout.strip())
            store = SQLiteStateStore(path, binding_revision=revision, lease_ttl_seconds=1)
            with self.assertRaisesRegex(PersistenceError, "OWNER_BUSY"):
                store.acquire_owner("parent")
            time.sleep(1.25)
            token = store.acquire_owner("parent")
            self.assertEqual(token.generation, child_generation + 1)
            stale = OwnerToken("child", child_generation, revision)
            with self.assertRaisesRegex(PersistenceError, "OWNER_FENCED"):
                store.commit(StateBatch({"k": 1}), 0, "late", stale)
            store.close()


class LaunchTests(unittest.IsolatedAsyncioTestCase):
    def release(self, *, durable):
        registered = Registry()
        registered.register_schema("ints", INTEGER_MAP)
        registered.register_operator(name="increment", version="1", method=method,
                                     input_schema="ints", output_schema="ints")
        if durable:
            return compile_release(registered, [flow()], provider_capabilities=SQLiteStateStore.capabilities)
        return compile_release(registered, [flow()], defaults=EPHEMERAL)

    async def test_launch_without_configuration_defaults_to_memory(self):
        runtime = ScheduledRuntime.launch(self.release(durable=False))
        async with runtime:
            self.assertTrue(runtime.commands.protocol_test)
            accepted = await runtime.submit("example", {"n": 1}, request_id="accept")
            result = await runtime.wait(accepted["execution_id"], timeout=2)
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertEqual(result["output"]["data"], {"n": 3})
        runtime.commands.coordinator.close()

    async def test_launch_with_sqlite_is_durable_and_survives_reopen(self):
        release = self.release(durable=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.db")
            provider = create_provider("sqlite", {"path": path})
            runtime = ScheduledRuntime.launch(release, persistence=provider)
            async with runtime:
                self.assertFalse(runtime.commands.protocol_test)
                accepted = await runtime.submit("example", {"n": 1}, request_id="accept")
                result = await runtime.wait(accepted["execution_id"], timeout=5)
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["output"]["data"], {"n": 3})
                receipt = provider.state.get_commit("accept")
                self.assertEqual(receipt.status, "COMMITTED")
                self.assertTrue(receipt.durable)
            execution_id = accepted["execution_id"]
            runtime.commands.coordinator.close()
            provider.close()
            reopened = create_provider("sqlite", {"path": path})
            coordinator = Coordinator(reopened.state, durable=True)
            commands = ExecutionCommands(coordinator, release, binding=reopened.binding, protocol_test=False)
            state = commands.query(execution_id)
            self.assertEqual(state["status"], "SUCCEEDED")
            self.assertEqual(state["output"]["data"], {"n": 3})
            coordinator.close()
            reopened.close()

    def test_launch_rejects_unusable_provider_objects(self):
        class Bare:
            pass
        with self.assertRaisesRegex(PersistenceError, "PROVIDER_PROTOCOL"):
            ScheduledRuntime.launch(self.release(durable=False), persistence=Bare())


class DecouplingGuardTests(unittest.TestCase):
    """Execution depends on the persistence port only; never on concrete stores."""

    EXECUTION_MODULES = ("runtime.py", "scheduling.py", "worker.py")
    CONCRETE_PATTERN = re.compile(r"persistence\.(memory|sqlite)|from \.(memory|sqlite) import")
    EXECUTION_PATTERN = re.compile(r"from \.(runtime|scheduling|worker|coordinator)\b|"
                                   r"import microflow\.(runtime|scheduling|worker|coordinator)\b")

    def test_execution_modules_never_import_concrete_stores(self):
        base = Path(__file__).resolve().parent.parent / "src" / "microflow"
        for name in self.EXECUTION_MODULES:
            text = (base / name).read_text(encoding="utf-8")
            self.assertIsNone(self.CONCRETE_PATTERN.search(text), name)

    def test_persistence_modules_never_import_execution_modules(self):
        base = Path(__file__).resolve().parent.parent / "src" / "microflow" / "persistence"
        for name in ("__init__.py", "protocol.py", "memory.py", "sqlite.py"):
            text = (base / name).read_text(encoding="utf-8")
            self.assertIsNone(self.EXECUTION_PATTERN.search(text), name)
