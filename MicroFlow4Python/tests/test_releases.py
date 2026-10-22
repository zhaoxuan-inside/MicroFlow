from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from microflow.compiler import compile_release
from microflow.errors import ContractError
from microflow.registry import discover
from microflow.releases import build_candidate
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
