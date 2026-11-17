from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest

from microflow.compiler import compile_release
from microflow.errors import ContractError, MicroFlowError
from microflow.persistence.sqlite import SQLiteArtifactStore, SQLiteStateStore
from microflow.registry import discover
from microflow.releases import build_candidate, load_release, publish
from microflow.runtime import LocalRuntime
from microflow.values import freeze
from tests.test_compiler import EPHEMERAL, registry, flow


class CandidateTests(unittest.TestCase):
    def test_complete_candidate_is_independent_and_verified(self):
        release = compile_release(registry(), [flow()], defaults=EPHEMERAL)
        candidate = build_candidate(release)
        self.assertEqual(candidate.verify().release_id, release.release_id)
        self.assertTrue(candidate.sources)
        with self.assertRaises(TypeError):
            candidate.sources["new.py"] = b""

    def test_missing_and_corrupt_artifacts_are_rejected(self):
        candidate = build_candidate(compile_release(registry(), [flow()], defaults=EPHEMERAL))
        for sources in ({}, {path: b"corrupted" for path in candidate.sources}):
            with self.assertRaises(ContractError):
                replace(candidate, sources=freeze(sources)).verify()
        with self.assertRaises(ContractError):
            replace(candidate, release_id="wrong").verify()

    def test_source_changes_after_registration_are_not_silently_published(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operators.py"
            path.write_text('def register(registry):\n    pass\n')
            registered = discover([path])
            path.write_text('def register(registry):\n    pass\n# changed\n')
            with self.assertRaises(ContractError) as caught:
                compile_release(registered, [], defaults=EPHEMERAL)
            self.assertEqual(caught.exception.diagnostic.error_code, "SOURCE_CHANGED")


def operator_module() -> str:
    from tests.test_compiler import INTEGER_MAP
    return (
        f"SCHEMA = {json.dumps(INTEGER_MAP)}\n"
        "def increment(input, output, context, metrix, debug, log):\n"
        "    output.set('n', input['n'] + 1)\n"
        "    return True\n"
        "def register(registry):\n"
        "    registry.register_schema('ints', SCHEMA)\n"
        "    registry.register_operator(name='increment', version='1', method=increment,"
        " input_schema='ints', output_schema='ints')\n"
    )


EXAMPLE_FLOW = {"id": "example", "input_schema": "ints", "output_schema": "ints",
                "nodes": {"first": {"operator": "increment@1",
                                    "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
                "outputs": {"n": {"from": "nodes.first.output.data.n", "required": True}}}


class PublicationTests(unittest.TestCase):
    """T12 slice: content-addressed publish + reload by release_id."""

    def setUp(self):
        self._dirs = []
        self._stores = []
        self._workspace = tempfile.TemporaryDirectory()
        self._dirs.append(self._workspace)
        self._source = Path(self._workspace.name) / "ops.py"
        self._source.write_text(operator_module(), encoding="utf-8")

    def _release(self):
        release = compile_release(discover([self._source]), [EXAMPLE_FLOW], defaults=EPHEMERAL)
        return release

    def _artifacts(self):
        tmp = tempfile.TemporaryDirectory()
        self._dirs.append(tmp)
        store = SQLiteStateStore(str(Path(tmp.name) / "state.db"), binding_revision="publication")
        self._stores.append(store)
        return store, SQLiteArtifactStore(store)

    def tearDown(self):
        for store in self._stores:
            store.close()
        for tmp in self._dirs:
            tmp.cleanup()

    def test_publish_load_round_trip_preserves_identity_and_behavior(self):
        release = self._release()
        store, artifacts = self._artifacts()
        published = publish(release, artifacts)
        self.assertEqual(published, release.release_id)
        self.assertTrue(artifacts.verify(release.release_id))
        reloaded = load_release(release.release_id, artifacts)
        self.assertEqual(reloaded.release_id, release.release_id)
        original = LocalRuntime(release).run("example", {"n": 1})
        loaded = LocalRuntime(reloaded).run("example", {"n": 1})
        self.assertEqual(loaded.output["data"], original.output["data"])
        # Publish is idempotent by digest; republishing the reload stores nothing new.
        self.assertEqual(publish(reloaded, artifacts), release.release_id)

    def test_load_rejects_missing_drifted_and_malformed_snapshots(self):
        release = self._release()
        store, artifacts = self._artifacts()
        with self.assertRaises(MicroFlowError) as caught:
            load_release(release.release_id, artifacts)
        self.assertEqual(caught.exception.diagnostic.error_code, "MISSING_ARTIFACT")
        publish(release, artifacts)
        with self.assertRaises(MicroFlowError) as caught:
            load_release("f" * 64, artifacts)
        self.assertEqual(caught.exception.diagnostic.error_code, "MISSING_ARTIFACT")
        for bad in ("", "xyz", "A" * 64, "0x1234"):
            with self.subTest(identity=bad):
                with self.assertRaises(ContractError) as caught:
                    load_release(bad, artifacts)
                self.assertEqual(caught.exception.diagnostic.error_code, "INVALID_RELEASE")
        # Source drift after publication is refused, never silently accepted.
        original_bytes = self._source.read_bytes()
        try:
            self._source.write_text(original_bytes.decode("utf-8") + "\n# drifted\n", encoding="utf-8")
            with self.assertRaises(ContractError) as caught:
                load_release(release.release_id, artifacts)
            self.assertEqual(caught.exception.diagnostic.error_code, "SOURCE_CHANGED")
        finally:
            self._source.write_bytes(original_bytes)
        load_release(release.release_id, artifacts)  # restored bytes load again

    def test_corrupted_manifest_is_rejected_by_digest_check(self):
        release = self._release()
        store, artifacts = self._artifacts()
        db_path = Path(self._dirs[-1].name) / "state.db"
        publish(release, artifacts)
        import sqlite3
        with sqlite3.connect(db_path) as connection:
            connection.execute("UPDATE artifacts SET content = ? WHERE digest = ?",
                               (b'{"protocol": "microflow-release-v1"}', release.release_id))
        with self.assertRaises(MicroFlowError) as caught:
            load_release(release.release_id, artifacts)
        self.assertIn(caught.exception.diagnostic.error_code,
                      {"MANIFEST_DIGEST_MISMATCH", "INVALID_RELEASE"})
