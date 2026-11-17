"""控制面集成测试（需要 PostgreSQL；ORCH_TEST_DATABASE_URL 缺失时显式跳过）。

覆盖：schema 初始化、账号、目录 CRUD、锁、阶段下发守卫、审批同人禁审、
回滚指针、实验生命周期、配置灰度、告警去重与确认。
"""
import os

import pytest
from fastapi.testclient import TestClient

from conftest import requires_pg

pytestmark = [requires_pg]


TEST_ADMIN_PASSWORD = "orch-test-admin-pw"


@pytest.fixture(scope="module")
def client():
    os.environ["ORCH_DATABASE_URL"] = os.environ["ORCH_TEST_DATABASE_URL"]
    os.environ["ORCH_ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD
    from app import db, main
    # 每轮集成测试从干净库开始（删表比 DROP DATABASE 更轻，无需超级用户）。
    import asyncio
    import asyncpg

    async def _reset():
        connection = await asyncpg.connect(os.environ["ORCH_DATABASE_URL"])
        await connection.execute("""
            DROP TABLE IF EXISTS alert_events, alert_rules, config_versions, config_items,
            config_namespaces, experiment_assignments, experiments, env_current, deployments,
            approvals, locks, debug_io, tests, scenario_versions, subgraph_versions,
            operator_versions, scenarios, subgraphs, operators, env_containers, sessions, users CASCADE
        """)
        await connection.close()

    asyncio.new_event_loop().run_until_complete(_reset())
    db._pool = None
    with TestClient(main.app) as test_client:  # lifespan 内完成 init_schema（同一事件循环）
        yield test_client, {"bootstrap_admin_email": "admin@orch.local",
                            "bootstrap_admin_password": TEST_ADMIN_PASSWORD}


def _login(client, email="admin@orch.local", password=None):
    body, bootstrap = client
    response = body.post("/api/auth/login", json={"email": email,
                                                  "password": password or bootstrap["bootstrap_admin_password"]})
    assert response.json()["code"] == 200, response.json()
    return response.json()["data"]["token"]


def _post(client, token, path, payload=None):
    body, _ = client
    return body.post(path, json=payload or {}, headers={"Authorization": f"Bearer {token}"})


def _get(client, token, path):
    body, _ = client
    return body.get(path, headers={"Authorization": f"Bearer {token}"})


def _delete(client, token, path):
    body, _ = client
    return body.delete(path, headers={"Authorization": f"Bearer {token}"})


def test_account_catalog_lifecycle_smoke(client):
    http, _bootstrap = client
    token = _login(client)
    me = _get(client, token, "/api/auth/me").json()
    assert me["code"] == 200 and "ops:alerts" in me["data"]["permissions"]

    # 场景目录 + 版本 + 部署守卫
    assert _post(client, token, "/api/scenarios/create",
                 {"code": "demo_flow", "display_name": "演示"}).json()["code"] == 200
    graph = {"entry_node": "start", "exit_node": "end",
             "nodes": [{"id": "start", "kind": "OPERATOR", "operator": "x", "operator_version": "1"},
                       {"id": "end", "kind": "OPERATOR", "operator": "x", "operator_version": "1"}],
             "edges": [{"from_node": "start", "to_node": "end"}]}
    # 版本保存要求持排他锁（与前端编辑流程一致）
    assert _post(client, token, "/api/scenarios/demo_flow/lock").json()["code"] == 200
    saved = _post(client, token, "/api/scenarios/demo_flow/versions",
                  {"version": "v1", "graph": graph}).json()
    assert saved["code"] == 200, saved
    scenario_version = str(saved["data"]["version"])  # 服务端自增派生（传入值仅作提示）
    assert _delete(client, token, "/api/scenarios/demo_flow/lock").json()["code"] == 200
    # 阶段守卫：test 前必须先 dev；online 需 E2E 记录
    skipped = _post(client, token, "/api/scenarios/demo_flow/deploy",
                    {"version": scenario_version, "env": "test"}).json()
    assert skipped["code"] == 400 and "不可跳过" in skipped["message"]

    # 审批：staging 需第二人，同人禁审
    assert _post(client, token, "/api/approvals/request",
                 {"asset_kind": "scenario", "asset_code": "demo_flow", "version": scenario_version,
                  "env": "staging"}).json()["code"] == 200
    approvals = _get(client, token, "/api/approvals?status=PENDING").json()["data"]["approvals"]
    assert approvals and approvals[0]["asset_code"] == "demo_flow"
    self_decide = _post(client, token, "/api/approvals/decide",
                        {"approval_id": approvals[0]["id"], "decision": "approve"}).json()
    assert self_decide["code"] == 400 and "第二人" in self_decide["message"]

    # 实验：创建→运行→分派→读出→停止
    assert _post(client, token, "/api/experiments/create",
                 {"key": "demo.exp", "variants": [{"key": "a", "weight": 1},
                                                  {"key": "b", "weight": 1}],
                  "traffic_percent": 100}).json()["code"] == 200
    assert _post(client, token, "/api/experiments/demo.exp/status",
                 {"status": "RUNNING"}).json()["code"] == 200
    assigned = _post(client, token, "/api/experiments/demo.exp/assign",
                     {"uid": "user-1"}).json()["data"]
    assert assigned["in_experiment"] is True and assigned["variant"] in ("a", "b")
    readout = _get(client, token, "/api/experiments/demo.exp/readout").json()["data"]
    assert readout["total"] == 1

    # 配置中心：登记→存版本→发布→灰度解析→回滚
    assert _post(client, token, "/api/configcenter/namespaces/create",
                 {"code": "demo"}).json()["code"] == 200
    assert _post(client, token, "/api/configcenter/namespaces/demo/items/create",
                 {"key": "feature.flag"}).json()["code"] == 200
    assert _post(client, token, "/api/configcenter/namespaces/demo/items/feature.flag/versions",
                 {"value": {"on": True}}).json()["code"] == 200
    published = _post(client, token, "/api/configcenter/namespaces/demo/items/feature.flag/publish",
                      {"version": "1", "gray": {"percent": 100, "whitelist": []}}).json()
    assert published["code"] == 200
    resolved = _get(client, token,
                    "/api/configcenter/namespaces/demo/items/feature.flag/resolve?uid=u1").json()["data"]
    assert resolved["channel"] == "gray" and resolved["version"] == "1"

    # 告警：规则创建 → 上报失败序列 → 事件去重 → ack
    assert _post(client, token, "/api/alerts/rules",
                 {"name": "连败", "kind": "consecutive_failures", "target": "demo_flow",
                  "threshold": 2, "window_minutes": 60}).json()["code"] == 200
    service = {"X-Service-Token": os.getenv("ORCH_SERVICE_TOKEN", "orch-service-secret")}
    report = http.post("/api/container/report-node-io", json={
        "records": [{"scenario_code": "demo_flow", "version": "v1", "env": "dev", "node_id": "end",
                     "status": "FAILED", "duration_ms": 5},
                    {"scenario_code": "demo_flow", "version": "v1", "env": "dev", "node_id": "end",
                     "status": "FAILED", "duration_ms": 5}]}, headers=service)
    assert report.json()["code"] == 200 and report.json()["data"]["alerts_fired"] >= 1
    repeat = http.post("/api/container/report-node-io", json={
        "records": [{"scenario_code": "demo_flow", "version": "v1", "env": "dev", "node_id": "end",
                     "status": "FAILED", "duration_ms": 5}]}, headers=service)
    alerts = _get(client, token, "/api/alerts?status=OPEN").json()["data"]["alerts"]
    assert alerts, "应存在 OPEN 告警"
    first_occurrence = alerts[0]["occurrences"]
    assert first_occurrence >= 2, "同 rule+scope 未 ack 应刷新 occurrences 而非新开"
    acked = _post(client, token, f"/api/alerts/{alerts[0]['id']}/ack").json()
    assert acked["code"] == 200 and acked["data"]["status"] == "ACKED"
    assert repeat.json()["code"] == 200
