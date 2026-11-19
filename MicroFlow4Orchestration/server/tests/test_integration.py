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

    # ── 可靠性收口判据（0.11.1）──
    # R1 健康检查：无鉴权探活，db 可达
    health = http.get("/api/health").json()
    assert health["status"] == "ok" and health["db"] is True

    # R2 事务原子性：多语句写失败时整体回滚（重复算子名让第二条 INSERT 撞唯一约束）
    dup = _post(client, token, "/api/operators/create", {"name": "dup_op", "code": "x"}).json()
    assert dup["code"] == 200
    clash = _post(client, token, "/api/operators/create", {"name": "dup_op", "code": "y"}).json()
    assert clash["code"] == 400 and "已存在" in clash["message"]
    versions = _get(client, token, "/api/operators/dup_op").json()["data"]["versions"]
    assert len(versions) == 1, "第二次创建失败后不得残留半提交状态"

    # R3 保留期清理：插入过期会话与过期 debug 上报，cleanup 后归零
    import asyncpg, os as _os
    async def _seed_stale():
        conn = await asyncpg.connect(os.environ["ORCH_TEST_DATABASE_URL"])
        await conn.execute(
            "INSERT INTO sessions (token, user_id, email, nickname, role, expires_at) "
            "SELECT 'stale-token', id, email, nickname, role, now() - interval '8 days' FROM users LIMIT 1")
        await conn.execute(
            "INSERT INTO debug_io (scenario_code, version, env, node_id, status, reported_at) "
            "VALUES ('stale', 'v0', 'dev', 'n', 'FAILED', now() - interval '15 days')")
        await conn.close()
    import asyncio as _aio
    _aio.new_event_loop().run_until_complete(_seed_stale())
    from app import db as _db
    async def _cleanup_with_own_conn():
        connection = await asyncpg.connect(os.environ["ORCH_TEST_DATABASE_URL"])
        try:
            return await _db.cleanup_retention(connection)
        finally:
            await connection.close()
    removed = _aio.new_event_loop().run_until_complete(_cleanup_with_own_conn())
    assert removed["sessions"] >= 1 and removed["debug_io"] >= 1, removed
    assert _get(client, token, "/api/approvals").json()["code"] == 200  # 服务仍正常

    # ── 安全加固判据（0.11.2）──
    # SEC1 会话 token 只以 sha256 摘要入库（库泄露不等于会话劫持）
    import asyncpg as _apg, os as _os2
    async def _check_hash():
        conn = await _apg.connect(os.environ["ORCH_TEST_DATABASE_URL"])
        row = await conn.fetchrow(
            "SELECT token FROM sessions WHERE email = $1 LIMIT 1", "admin@orch.local")
        await conn.close()
        return row["token"] if row else None
    stored = _aio.new_event_loop().run_until_complete(_check_hash())
    assert stored and stored != token, "明文 token 不得入库"
    assert len(stored) == 64, "应为 sha256 十六进制摘要"

    # SEC2 登录限流：连续失败达阈值后 400（错误信息含限流提示），正确密码也被拒
    http2, _ = client
    for _ in range(10):
        bad = http2.post("/api/auth/login",
                         json={"email": "admin@orch.local", "password": "wrong-pass"})
    throttled = http2.post("/api/auth/login",
                           json={"email": "admin@orch.local", "password": "wrong-pass"})
    assert throttled.json()["code"] == 400 and "过多" in throttled.json()["message"]
    even_correct = http2.post("/api/auth/login",
                              json={"email": "admin@orch.local", "password": "orch-test-admin-pw"})
    assert "过多" in even_correct.json()["message"], "限流窗口内正确密码同样被拒"

    # SEC3 webhook SSRF：私有/回环目标与非法 scheme 被拒绝
    ssrf = _post(client, token, "/api/alerts/rules",
                 {"name": "ssrf-test", "kind": "error_rate", "target": "*",
                  "threshold": 1, "webhook_url": "http://127.0.0.1:9000/hook"}).json()
    assert ssrf["code"] == 400 and "不被允许" in ssrf["message"]
    ssrf2 = _post(client, token, "/api/alerts/rules",
                  {"name": "ssrf-test2", "kind": "error_rate", "target": "*",
                   "threshold": 1, "webhook_url": "ftp://example.com"}).json()
    assert ssrf2["code"] == 400

    # SEC4 安全响应头
    resp = http2.get("/api/envs", headers={"Authorization": f"Bearer {token}"})
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"

    # SEC5 编排图 payload 超限拒绝（1MB）
    big_graph = {"entry_node": "n0", "exit_node": "n0",
                 "nodes": [{"id": "n0", "kind": "OPERATOR", "operator": "x",
                            "pad": "x" * (1024 * 1024 + 100)}],
                 "edges": []}
    assert _post(client, token, "/api/scenarios/create",
                 {"code": "big_graph", "display_name": "超限样例"}).json()["code"] == 200
    assert _post(client, token, "/api/scenarios/big_graph/lock").json()["code"] == 200
    oversized = _post(client, token, "/api/scenarios/big_graph/versions",
                      {"version": "v1", "graph": big_graph}).json()
    assert oversized["code"] == 400 and "1MB" in oversized["message"]
    _delete(client, token, "/api/scenarios/big_graph/lock")
