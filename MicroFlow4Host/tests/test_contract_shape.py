"""字段契约守卫（host-contract.fields.json v1）。

两道咬合：
1. 场景集双向一致——JSON 里每个场景在宿主有处理器与权限映射，宿主每个场景都在 JSON 里；
2. data 键形状精确——抽样场景经真实 dispatch 调用，返回的 data 键集合必须与声明完全一致。
   宿主改形状或 JSON 漂移，这里立刻红灯（Ops/Bizops 那三处静默错位正是这样漏掉的）。
"""
import json
import unittest
from pathlib import Path

from host.app import SCENARIOS
from host.scenarios import SCENARIO_PERMISSIONS

from test_host import HostTestBase
from test_registry_scenarios import _batch, _report

CONTRACT = Path(__file__).resolve().parents[2] / "MicroFlow4Kit" / "host-contract.fields.json"


def _load():
    value = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert value["protocol"] == "microflow-host-fields-v1"
    return value


class ContractFileTests(unittest.TestCase):
    def setUp(self):
        self.contract = _load()

    def test_scenarios_match_the_host_bidirectionally(self):
        declared = set(self.contract["scenarios"])
        self.assertEqual(declared, set(SCENARIOS))
        self.assertEqual(declared, set(SCENARIO_PERMISSIONS))

    def test_external_and_delegated_do_not_shadow_the_contract(self):
        declared = set(self.contract["scenarios"])
        self.assertFalse(set(self.contract["externalScenarios"]) & declared)
        for name in self.contract["externalScenarios"]:
            for prefix in self.contract["delegatedPrefixes"]:
                self.assertFalse(name.startswith(prefix), name)

    def test_every_scenario_declares_typed_payload_and_data(self):
        vocabulary = set(self.contract["types"])
        for name, spec in self.contract["scenarios"].items():
            for section in ("payload", "data"):
                self.assertIsInstance(spec[section], dict, f"{name}.{section}")
                for field, kind in spec[section].items():
                    self.assertIn(kind.rstrip("?"), vocabulary, f"{name}.{section}.{field}:{kind}")


class DataShapeContractTests(HostTestBase):
    """经真实 dispatch 断言 data 键集合与契约声明完全一致（抽样覆盖漂移史场景）。"""

    def _data_keys(self, scenario, payload):
        token = self.login()
        response = self.dispatch(scenario, payload, token=token)
        self.assertEqual(response.status_code, 200, response.json())
        return set(response.json()["data"])

    def test_read_faces_match_the_declared_shapes(self):
        contract = _load()["scenarios"]
        self.login()                       # 至少产生一条 runs 记录，供 detail 取 seq
        first_run = self.db.query_one("SELECT seq FROM runs ORDER BY seq")["seq"]
        cases = {
            "ops.runs.list": {},
            "ops.runs.detail": {"seq": first_run},
            "ops.metrics": {},
            "ops.events.list": {},
            "platform.audit.list": {},
            "bizops.overview": {},
            "bizops.trend": {"days": 7},
            "bizops.funnel": {"steps": ["auth.login"]},
            "bizops.retention": {"days": 7},
            "auth.session": {},
        }
        for scenario, payload in cases.items():
            with self.subTest(scenario=scenario):
                self.assertEqual(self._data_keys(scenario, payload),
                                 set(contract[scenario]["data"]), scenario)

    def test_registry_faces_match_the_declared_shapes(self):
        contract = _load()["scenarios"]
        token = self.login()
        report = _report()
        batch = _batch()
        publish = self.dispatch("registry.publish", {
            "namespace": report["namespace"], "group": report["group"],
            "digest": report["digest"], "contentDigest": report["digest"], "report": report}, token=token)
        self.assertEqual(publish.status_code, 200, publish.json())
        self.assertEqual(set(publish.json()["data"]), set(contract["registry.publish"]["data"]))

        stream = self.dispatch("registry.stream", {
            "namespace": batch["namespace"], "group": batch["group"],
            "contentDigest": batch["contentDigest"], "count": batch["count"],
            "batch": batch}, token=token)
        self.assertEqual(stream.status_code, 200, stream.json())
        self.assertEqual(set(stream.json()["data"]), set(contract["registry.stream"]["data"]))


if __name__ == "__main__":
    unittest.main()
