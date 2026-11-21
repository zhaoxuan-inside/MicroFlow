"""宿主契约测试套件：信封、身份信任边界、RBAC、遥测过载、聚合诚实性、托管与 scaffold。"""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from host import HostDatabase, PERMISSION_CATALOG, SCENARIO_PERMISSIONS, create_app
from host.cli import bootstrap, scaffold


class HostTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = HostDatabase(self.root / "host.sqlite3")
        self.app = create_app(self.db)
        self.client = TestClient(self.app)
        # 管理员：admin 角色持全目录权限
        digest_salt = __import__("host.security", fromlist=["hash_password"]).hash_password("admin-pw")
        self.db.execute("INSERT INTO users (name, password_hash, password_salt, created_at)"
                        " VALUES ('root', ?, ?, datetime('now'))", digest_salt)
        self.db.execute("INSERT INTO roles (name, permissions) VALUES ('admin', ?)",
                        (json.dumps(sorted({p["permission"] for p in PERMISSION_CATALOG})),))
        self.db.execute("INSERT INTO platform_roles (user_id, role_id) SELECT u.id, r.id FROM users u, roles r"
                        " WHERE u.name = 'root' AND r.name = 'admin'")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def login(self, username="root", password="admin-pw") -> str:
        response = self.client.post("/api/v1/dispatch", json={
            "scenario": "auth.login", "payload": {"username": username, "password": password}})
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]["token"]

    def dispatch(self, scenario: str, payload: dict | None = None, token: str | None = None,
                 context_user_id: str | None = None) -> dict:
        context: dict = {}
        if token:
            context["token"] = token
        if context_user_id:
            context["user_id"] = context_user_id
        body = {"scenario": scenario, "payload": payload or {}, "context": context}
        return self.client.post("/api/v1/dispatch", json=body)


class EnvelopeContractTests(HostTestBase):
    def test_envelope_shape_and_trace_id(self):
        response = self.client.post("/api/v1/dispatch", json={
            "scenario": "auth.login", "payload": {"username": "root", "password": "admin-pw"}})
        self.assertEqual(response.status_code, 200)
        envelope = response.json()
        self.assertEqual(set(envelope), {"code", "data", "message", "trace_id"})
        self.assertEqual(envelope["code"], 0)
        self.assertTrue(envelope["trace_id"])
        self.assertIn("token", envelope["data"])

    def test_unknown_scenario_is_404_envelope(self):
        response = self.dispatch("nope.thing")
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(response.json()["code"], 0)

    def test_malformed_request_is_400(self):
        response = self.client.post("/api/v1/dispatch", json={"payload": {}})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/v1/dispatch", content=b"not-json",
                                    headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 400)

    def test_delegated_scenarios_honestly_refuse(self):
        token = self.login()
        for scenario in ("orchestration.catalog.list", "experiment.list", "configcenter.resolve"):
            response = self.dispatch(scenario, token=token)
            self.assertEqual(response.status_code, 501)
            self.assertIn("delegated", response.json()["message"])

    def test_every_catalog_permission_maps_to_a_declared_scenario_or_catalog(self):
        # 权限点目录与场景映射互相咬合：目录里每个权限要么被场景引用，要么就是目录自身展示。
        referenced = {p for p in SCENARIO_PERMISSIONS.values() if p}
        catalog = {p["permission"] for p in PERMISSION_CATALOG}
        self.assertLessEqual(referenced, catalog)


class IdentityTrustTests(HostTestBase):
    def test_context_user_id_is_not_trusted(self):
        # 无令牌但伪造 context.user_id：权限场景必须 403（身份只来自令牌）。
        response = self.dispatch("platform.users.list", context_user_id="1")
        self.assertEqual(response.status_code, 403)

    def test_bearer_header_and_context_token_both_work(self):
        token = self.login()
        header = self.client.post("/api/v1/dispatch", json={"scenario": "auth.session", "payload": {}},
                                  headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(header.json()["data"]["user"]["name"], "root")
        inline = self.dispatch("auth.session", token=token)
        self.assertEqual(inline.json()["data"]["user"]["name"], "root")

    def test_wrong_password_rejected(self):
        response = self.dispatch("auth.login", {"username": "root", "password": "wrong"})
        self.assertEqual(response.status_code, 403)


class RbacTests(HostTestBase):
    def test_admin_passes_and_unprivileged_fails(self):
        token = self.login()
        response = self.dispatch("platform.users.list", token=token)
        self.assertEqual(response.status_code, 200)
        # 新用户无权限
        self.dispatch("platform.users.create", {"username": "alice", "password": "pw-alice"}, token=token)
        alice_login = self.dispatch("auth.login", {"username": "alice", "password": "pw-alice"})
        alice_token = alice_login.json()["data"]["token"]
        response = self.dispatch("platform.users.list", token=alice_token)
        self.assertEqual(response.status_code, 403)
        self.assertIn("platform:user_manage", response.json()["message"])

    def test_role_create_rejects_unknown_permissions(self):
        token = self.login()
        response = self.dispatch("platform.roles.create",
                                 {"name": "broken", "permissions": ["not:a:permission"]}, token=token)
        self.assertEqual(response.status_code, 422)

    def test_permissions_list_is_anonymous_reachable_catalog(self):
        response = self.dispatch("platform.permissions.list")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["permissions"]), len(PERMISSION_CATALOG))


class GovernanceTests(HostTestBase):
    def test_lifecycle_with_audit(self):
        token = self.login()
        self.dispatch("platform.tenants.create", {"name": "acme"}, token=token)
        self.dispatch("platform.projects.create", {"tenant_id": 1, "name": "web"}, token=token)
        response = self.dispatch("platform.scope.my", token=token)
        self.assertEqual(response.json()["data"]["tenants"][0]["name"], "acme")
        response = self.dispatch("platform.envs.list", {"project_id": 1}, token=token)
        self.assertEqual([e["key"] for e in response.json()["data"]["envs"]],
                         ["dev", "online", "staging", "test"])
        response = self.dispatch("platform.audit.list", token=token)
        actions = [a["action"] for a in response.json()["data"]["audit"]]
        self.assertIn("tenant.create", actions)
        self.assertIn("project.create", actions)

    def test_missing_required_field_is_422(self):
        token = self.login()
        response = self.dispatch("platform.tenants.create", {}, token=token)
        self.assertEqual(response.status_code, 422)


class TelemetryAndAggregationTests(HostTestBase):
    def _ingest(self, events: list[dict], expect: int):
        response = self.client.post("/api/v1/telemetry", json={"events": events})
        self.assertEqual(response.status_code, expect)
        return response

    def test_telemetry_ingest_and_metrics(self):
        self._ingest([{"event": "ops.page.viewed", "timestamp": "2026-11-21T00:00:00Z",
                       "release_id": "r1", "environment": "online", "locale": "zh-CN",
                       "payload": {"anonymous_id": "a1"}}], 201)
        # 无效事件不落库、逐条计数如实拒绝（accepted=0 / rejected=1）。
        invalid = self._ingest([{"event": "", "timestamp": "2026-11-21T00:00:01Z"}], 201)
        self.assertEqual(invalid.json()["data"], {"accepted": 0, "rejected": 1})
        response = self.dispatch("bizops.overview")
        self.assertEqual(response.status_code, 403)  # bizops 需要权限
        token = self.login()
        overview = self.dispatch("bizops.overview", token=token).json()["data"]
        self.assertEqual(overview["entities"]["telemetry_events"], 1)

    def test_overload_is_explicitly_rejected(self):
        from host.app import TELEMETRY_MAX_PENDING
        token_field = "payload"
        events = [{"event": "ops.page.viewed", "timestamp": "2026-11-21T00:00:00Z",
                   "payload": {token_field: {"anonymous_id": f"a{i}"}}} for i in range(100)]
        rounds = TELEMETRY_MAX_PENDING // 100
        for _ in range(rounds):
            self._ingest(events, 201)
        self._ingest(events[:10], 429)

    def test_funnel_and_retention_disclose_sample(self):
        self._ingest([
            {"event": "ops.page.viewed", "timestamp": "2026-11-20T00:00:00Z", "payload": {"anonymous_id": "a1"}},
            {"event": "ops.feature.used", "timestamp": "2026-11-20T00:01:00Z", "payload": {"anonymous_id": "a1"}},
            {"event": "ops.page.viewed", "timestamp": "2026-11-20T00:02:00Z", "payload": {"anonymous_id": "a2"}},
            {"event": "ops.page.viewed", "timestamp": "2026-11-21T00:00:00Z", "payload": {"anonymous_id": "a1"}},
        ], 201)
        token = self.login()
        funnel = self.dispatch("bizops.funnel",
                               {"steps": ["ops.page.viewed", "ops.feature.used"]}, token=token).json()["data"]
        self.assertEqual([s["clients"] for s in funnel["steps"]], [2, 1])
        self.assertEqual(funnel["sample_clients"], 2)
        self.assertIn("非严格时序", funnel["note"])
        retention = self.dispatch("bizops.retention", token=token).json()["data"]
        cohort = retention["cohorts"]["2026-11-20"]
        self.assertEqual(cohort["clients"], 2)
        self.assertEqual(cohort["d1"], 1)  # a1 在 11-21 回访

    def test_runs_recorded_and_metrics_read_time(self):
        token = self.login()
        self.dispatch("platform.permissions.list", token=token)
        metrics = self.dispatch("ops.metrics", token=token).json()["data"]
        self.assertEqual(metrics["total"], 2)  # login + permissions.list
        runs = self.dispatch("ops.runs.list", {"scenario": "auth.login"}, token=token).json()["data"]
        self.assertEqual(runs["runs"][0]["scenario"], "auth.login")
        detail = self.dispatch("ops.runs.detail", {"seq": runs["runs"][0]["seq"]}, token=token)
        self.assertEqual(detail.json()["data"]["run"]["scenario"], "auth.login")


class ExtensionPointTests(HostTestBase):
    """宿主产品扩展点：extra_scenarios 与通用 /apps 托管（PersonnelHub 等承载应用）。"""

    def test_extra_scenario_goes_through_same_envelope_auth_and_permission(self):
        def echo(db, user, payload, context):
            return {"echo": payload["what"], "actor": user["name"] if user else None}

        app = create_app(self.db, extra_scenarios={
            "personnel.employees.list": {"handler": echo, "permission": "project:manage"},
            "personnel.hello": {"handler": echo, "permission": None},
        })
        client = TestClient(app)
        # 匿名可达场景（permission None）——无需令牌
        ok = client.post("/api/v1/dispatch", json={"scenario": "personnel.hello", "payload": {"what": "x"}})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["data"]["echo"], "x")
        # 权限场景：匿名 403；管理员（持 project:manage）通过
        denied = client.post("/api/v1/dispatch", json={"scenario": "personnel.employees.list", "payload": {}})
        self.assertEqual(denied.status_code, 403)
        token = self.login()
        allowed = client.post("/api/v1/dispatch",
                              json={"scenario": "personnel.employees.list", "payload": {"what": "y"},
                                    "context": {"token": token}})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["data"]["actor"], "root")

    def test_generic_apps_hosting_serves_any_deployed_subdir(self):
        apps = self.root / "apps"
        (apps / "personnel").mkdir(parents=True)
        (apps / "personnel" / "index.html").write_text("<html>personnel</html>", encoding="utf-8")
        (apps / ".." / "escape").mkdir(parents=True, exist_ok=True)
        hosted = TestClient(create_app(self.db, apps_dir=apps))
        self.assertEqual(hosted.get("/apps/personnel/").text, "<html>personnel</html>")
        # 非法名字与未部署目录诚实 404
        self.assertEqual(hosted.get("/apps/Nope/").status_code, 404)
        self.assertEqual(hosted.get("/apps/absent/").status_code, 404)


class StaticAndScaffoldTests(HostTestBase):
    def test_spa_hosting_serves_build_output_or_honest_404(self):
        apps = self.root / "apps"
        (apps / "ops").mkdir(parents=True)
        (apps / "ops" / "index.html").write_text("<html>ops</html>", encoding="utf-8")
        hosted = TestClient(create_app(self.db, apps_dir=apps))
        self.assertEqual(hosted.get("/apps/ops/").text, "<html>ops</html>")
        missing = TestClient(create_app(self.db, apps_dir=apps))
        response = missing.get("/apps/bizops/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not deployed", response.json()["message"])

    def test_scaffold_never_overwrites(self):
        into = self.root / "skeleton"
        self.assertEqual(scaffold(into), 0)
        self.assertEqual(scaffold(into), 2)
        app_file = (into / "host_app.py").read_text(encoding="utf-8")
        self.assertIn("create_app(HostDatabase(STORE)", app_file)
        self.assertIn("[fill]", app_file)

    def test_bootstrap_prints_password_once(self):
        import io
        from contextlib import redirect_stdout
        store = self.root / "boot.sqlite3"
        out = io.StringIO()
        with redirect_stdout(out):
            code = bootstrap(store, "owner", None)
        self.assertEqual(code, 0)
        printed = json.loads(out.getvalue())
        self.assertTrue(printed["password"])
        self.assertEqual(bootstrap(store, "owner", None), 2)  # 幂等拒绝重建
