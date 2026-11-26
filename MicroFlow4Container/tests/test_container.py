"""容器适配器验收：下发校验、耐久执行、全链投递、debug 上行、算子注册、HTTP 令牌。"""
import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock



from . import fixtures
from .stub import dispatch_stub
from microflow_container import ContainerRuntime, build_services, records_to_node_io
from microflow_container.http import create_app
from microflow_container.runtime import config_content_hash

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


class ContainerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = fixtures.write_project(self.root / "proj")
        self.store_dir = self.root / "data"

    def runtime(self, **kwargs) -> ContainerRuntime:
        return ContainerRuntime(project_path=self.project, store_path=self.store_dir / "s.sqlite3",
                                env="dev", binding_id="container-dev", **kwargs)

    # A33 下发：hash 校验 + 骨架如实转换
    def test_receive_config_verifies_hash_and_records_the_skeleton(self):
        runtime = self.runtime()
        payload = {"scenario_code": "SC_INC", "version": "v1",
                   "graph": fixtures.CANVAS_GRAPH,
                   "config_hash": config_content_hash(fixtures.CANVAS_GRAPH)}
        accepted = runtime.receive_config(payload)
        self.assertTrue(accepted["accepted"])
        self.assertTrue(accepted["flow_digest"])          # canvas → flow 骨架摘要（真转换）
        self.assertEqual(accepted["skeleton_diagnostics"], 2)  # 无 schema 声明的 advisory

        tampered = dict(payload, config_hash="0" * 64)
        with self.assertRaisesRegex(ValueError, "config_hash mismatch"):
            runtime.receive_config(tampered)

    # A34 执行：先配置后执行；真耐久路径产生意图
    def test_execute_scenario_requires_config_and_runs_durably(self):
        runtime = self.runtime()
        with self.assertRaises(LookupError):
            run(runtime.execute_scenario("SC_INC", {"n": 1}))
        runtime.receive_config({"scenario_code": "SC_INC", "version": "v1",
                                "graph": fixtures.CANVAS_GRAPH, "config_hash": ""})
        result = run(runtime.execute_scenario("SC_INC", {"n": 1}))
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(dict(result["final_output"]), {"n": 2})
        self.assertEqual(result["version"], "v1")
        self.assertTrue(result["records"])
        pending = runtime.coordinator.pending_events()
        self.assertGreaterEqual(len(pending), 3)          # accept/claim/complete 各一
        self.assertTrue(all(intent["delivery"] == "PENDING" for intent in pending))

    # A35 全链闭环：执行 → 意图 → 泵 → HTTP → 宿主 → 翻账归零
    def test_full_loop_delivers_intents_to_the_host_and_acks(self):
        with dispatch_stub() as server:
            services = build_services(
                project_path=self.project, store_dir=self.store_dir, env="dev",
                binding_id="container-dev", host_endpoint=server.endpoint,
                host_token="secret", control_url="http://127.0.0.1:9",   # 控制面不可达：如实记录
                control_token="none", namespace="demo", group="dev",
                pump_interval=0.05, stream_interval=0.05)
            services.start()
            self.assertFalse(services.announced["ok"])     # 上行失败不阻塞启动
            runtime = services.runtime
            runtime.receive_config({"scenario_code": "SC_INC", "version": "v1",
                                    "graph": fixtures.CANVAS_GRAPH, "config_hash": ""})
            result = run(services.execute_scenario("SC_INC", {"n": 5}))
            self.assertEqual(result["status"], "SUCCEEDED")
            deadline = time.monotonic() + 5.0
            while runtime.coordinator.pending_events() and time.monotonic() < deadline:
                time.sleep(0.02)
            services.stop()
            requests = len(server.requests)
        self.assertEqual(runtime.coordinator.pending_events(), ())
        self.assertGreaterEqual(services.pump.stats()["acked"], 3)
        self.assertGreaterEqual(requests, 1)
        frames = [frame for request in server.requests
                  for frame in request["body"]["payload"]["batch"]["frames"]]
        self.assertTrue(all(frame["kind"] in ("runtime_record", "event_intent") for frame in frames))

    # A36 debug 上行：生命周期记录 → 控制面行；inputs/outputs 如实为 None
    def test_debug_uplink_maps_records_to_node_io_honestly(self):
        runtime = self.runtime()
        runtime.receive_config({"scenario_code": "SC_INC", "version": "v1",
                                "graph": fixtures.CANVAS_GRAPH, "config_hash": ""})
        result = run(runtime.execute_scenario("SC_INC", {"n": 3}))
        rows = records_to_node_io(result["records"], scenario_code="SC_INC", version="v1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["scenario_code"], "SC_INC")
        self.assertEqual(rows[0]["node_id"], "increment")
        self.assertEqual(rows[0]["status"], "SUCCEEDED")
        self.assertGreaterEqual(rows[0]["duration_ms"], 0)
        self.assertIsNone(rows[0]["inputs"])
        self.assertIsNone(rows[0]["outputs"])

    # A37 算子注册：违反内核契约的代码如实回滚；合规代码重建 release 并可试跑
    def test_register_operator_rejects_violations_and_accepts_scaffold_shape(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(ValueError, "kernel contract"):
            runtime.register_operator({"name": "broken", "code": "x = 1\n", "version": "1"})
        self.assertFalse((self.root / "proj" / "pushed" / "broken.py").exists())
        self.assertEqual(runtime.operator_catalog["increment"]["ref"], "increment@1")  # 原目录未损

        doubled = (fixtures.MODULE.replace("input[\"n\"] + 1", "input[\"n\"] * 2")
                   .replace("increment", "double").replace("adds one", "doubles")
                   .replace('"ints"', '"ints2"'))
        outcome = runtime.register_operator({"name": "double", "code": doubled, "version": "2"})
        self.assertEqual(outcome["registered"], "double")
        result = run(runtime.execute_operator("double", {"n": 21}))
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(dict(result["final_output"]), {"n": 42})

    def test_execute_operator_rejects_unknown_and_bad_inputs(self):
        runtime = self.runtime()
        with self.assertRaises(LookupError):
            run(runtime.execute_operator("missing", {"n": 1}))
        result = run(runtime.execute_operator("increment", {"n": 1}))
        self.assertEqual(result["status"], "SUCCEEDED")

    # A38 HTTP 面：X-Service-Token 全拒绝未配置/未携带；业务失败不 500 假成功
    def test_http_layer_enforces_service_token(self):
        services = build_services(
            project_path=self.project, store_dir=self.store_dir, env="dev",
            binding_id="container-dev", host_endpoint="http://127.0.0.1:9/x",
            host_token="secret", control_url="http://127.0.0.1:9",
            control_token="none", namespace="demo", group="dev")
        with mock.patch.dict(os.environ, {"MF_CONTAINER_SERVICE_TOKEN": "svc-token"}):
            client = TestClient(create_app(services))
            self.assertEqual(client.post("/container/configs", json={}).status_code, 403)
            self.assertEqual(
                client.post("/container/configs", json={
                    "scenario_code": "SC_INC", "version": "v1",
                    "graph": fixtures.CANVAS_GRAPH,
                    "config_hash": config_content_hash(fixtures.CANVAS_GRAPH)},
                    headers={"X-Service-Token": "svc-token"}).status_code, 200)
            response = client.post("/container/execute/scenario", json={
                "scenario_code": "SC_INC", "inputs": {"n": 1}},
                headers={"X-Service-Token": "svc-token"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "SUCCEEDED")
            self.assertEqual(dict(response.json()["final_output"]), {"n": 2})
            missing = client.post("/container/execute/scenario", json={
                "scenario_code": "SC_NONE", "inputs": {}},
                headers={"X-Service-Token": "svc-token"})
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(client.get("/healthz").json()["release_id"], services.runtime.release_id)


if __name__ == "__main__":
    unittest.main()
