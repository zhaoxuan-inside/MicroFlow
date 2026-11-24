"""A11: the diagnostic catalog and the source of raised codes must match exactly."""
import re
import unittest
from pathlib import Path

from microflow_registry.codes import DIAGNOSTICS, PROTOCOL, describe_diagnostics

SOURCE = Path(__file__).resolve().parent.parent / "src" / "microflow_registry"
RAISED = re.compile(r'RegistryError\(\s*"([A-Z][A-Z_]*)"')


class CatalogGuardTests(unittest.TestCase):
    def test_guard_every_raised_code_is_registered(self):
        raised = set()
        for path in sorted(SOURCE.rglob("*.py")):
            raised.update(RAISED.findall(path.read_text(encoding="utf-8")))
        self.assertEqual(raised, set(DIAGNOSTICS),
                         "raised codes and the diagnostic catalog must match exactly")

    def test_catalog_projection_is_sorted_and_stable(self):
        described = describe_diagnostics()
        self.assertEqual(described["protocol"], PROTOCOL)
        codes = [entry["code"] for entry in described["diagnostics"]]
        self.assertEqual(codes, sorted(codes))
        self.assertEqual(described["count"], len(codes))


if __name__ == "__main__":
    unittest.main()
