"""宿主网关装配：dispatch 单端点 + 遥测接收 + SPA 静态托管。

协议（HOST_CONTRACT.md）：POST 单分发端点 `/api/v1/dispatch`，载荷
`{scenario, version, payload, context:{token, tenant_id?, project_id?, env_key?}}`，
信封 `{code, data, message, trace_id}`（200 为成功）；身份来自 `Authorization: Bearer`
或 `context.token`，`context.user_id` 不被信任。遥测接收端口：有界容量，过载显式
拒绝（TELEMETRY_OVERLOAD），不静默降级。
"""
import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .database import HostDatabase
from .handlers import (auth_login, auth_session, bizops_funnel, bizops_overview, bizops_retention,
                       bizops_trend, ops_metrics, ops_runs_detail, ops_runs_list,
                       platform_audit_list, platform_envs_create, platform_envs_list,
                       platform_permissions_list, platform_projects_create, platform_projects_list,
                       platform_projects_update, platform_roles_create, platform_roles_list,
                       platform_scope_my, platform_tenants_create, platform_tenants_list,
                       platform_users_create, platform_users_list)
from .scenarios import DELEGATED_SCENARIOS_PREFIXES, SCENARIO_PERMISSIONS

SCENARIOS = {
    "auth.login": auth_login,
    "auth.session": auth_session,
    "platform.scope.my": platform_scope_my,
    "platform.tenants.list": platform_tenants_list,
    "platform.tenants.create": platform_tenants_create,
    "platform.projects.list": platform_projects_list,
    "platform.projects.create": platform_projects_create,
    "platform.projects.update": platform_projects_update,
    "platform.users.list": platform_users_list,
    "platform.users.create": platform_users_create,
    "platform.roles.list": platform_roles_list,
    "platform.roles.create": platform_roles_create,
    "platform.permissions.list": platform_permissions_list,
    "platform.envs.list": platform_envs_list,
    "platform.envs.create": platform_envs_create,
    "platform.audit.list": platform_audit_list,
    "ops.runs.list": ops_runs_list,
    "ops.runs.detail": ops_runs_detail,
    "ops.metrics": ops_metrics,
    "bizops.overview": bizops_overview,
    "bizops.trend": bizops_trend,
    "bizops.funnel": bizops_funnel,
    "bizops.retention": bizops_retention,
}

TELEMETRY_MAX_PENDING = 10_000
TELEMETRY_MAX_BATCH = 100


def envelope(code: int, data=None, message: str = "ok") -> dict:
    return {"code": code, "data": data, "message": message, "trace_id": uuid.uuid4().hex}


def _error(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code if code >= 400 else 400, content=envelope(code, None, message))


class HostGateway:
    """参考实现网关。编排/实验/配置中心场景由编排控制面承载，宿主按契约代理（未接线时如实拒绝）。"""

    def __init__(self, db: HostDatabase, apps_dir: Path | None = None,
                 delegated_target: str | None = None):
        self.db = db
        self.apps_dir = Path(apps_dir) if apps_dir else None
        self.delegated_target = delegated_target

    # ---- 身份与权限 ----

    def _resolve_user(self, request: Request, context: dict):
        token = None
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization[len("Bearer "):].strip()
        if not token and isinstance(context.get("token"), str):
            token = context["token"]
        if not token:
            return None
        return self.db.session_user(token)

    def _has_permission(self, user, permission: str) -> bool:
        if user is None:
            return False
        roles = self.db.query(
            "SELECT r.permissions FROM platform_roles pr JOIN roles r ON r.id = pr.role_id"
            " WHERE pr.user_id = ?"
            " UNION SELECT r.permissions FROM roles r"
            " LEFT JOIN memberships m ON m.role_id = r.id WHERE m.user_id = ?"
            " UNION SELECT r.permissions FROM roles r"
            " LEFT JOIN project_members pm ON pm.role_id = r.id WHERE pm.user_id = ?",
            (user["id"], user["id"], user["id"]))
        import json as _json
        for row in roles:
            if permission in _json.loads(row["permissions"]):
                return True
        return False

    # ---- dispatch ----

    async def dispatch(self, request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error(400, "request body must be JSON")
        if not isinstance(body, dict):
            return _error(400, "request body must be a JSON object")
        scenario = body.get("scenario")
        payload = body.get("payload") or {}
        context = body.get("context") or {}
        if not isinstance(scenario, str) or not scenario:
            return _error(400, "scenario is required")
        if not isinstance(payload, dict) or not isinstance(context, dict):
            return _error(400, "payload and context must be objects")

        user = self._resolve_user(request, context)
        # context.user_id 不被信任（契约原文）：身份只来自会话令牌。

        for prefix in DELEGATED_SCENARIOS_PREFIXES:
            if scenario.startswith(prefix):
                if self.delegated_target is None:
                    return _error(501, f"scenario {scenario!r} is delegated to the orchestration control plane;"
                                       " this host has no delegated target wired (honest refusal)")
                return _error(501, "delegation wiring is a host extension point (not part of the reference implementation)")

        if scenario not in SCENARIO_PERMISSIONS:
            return _error(404, f"unknown scenario {scenario!r}")
        required = SCENARIO_PERMISSIONS[scenario]
        if required is not None and not self._has_permission(user, required):
            return _error(403, f"scenario {scenario!r} requires permission {required!r}")

        handler = SCENARIOS[scenario]
        started = time.monotonic()
        status = "SUCCEEDED"
        try:
            try:
                data = handler(self.db, user, payload, context)
            except PermissionError as exc:
                status = "FAILED"
                return _error(403, str(exc))
            except LookupError as exc:
                status = "FAILED"
                return _error(404, str(exc))
            except (ValueError, KeyError) as exc:
                status = "FAILED"
                return _error(422, str(exc))
            return JSONResponse(status_code=200, content=envelope(0, data))
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            self.db.execute(
                "INSERT INTO runs (at, scenario, status, duration_ms, actor, tenant_id, project_id, env_key)"
                " VALUES (datetime('now'),?,?,?,?,?,?,?)",
                (scenario, status, duration_ms,
                 user["name"] if user is not None else None,
                 context.get("tenant_id"), context.get("project_id"), context.get("env_key")))

    # ---- 遥测接收 ----

    async def telemetry_ingest(self, request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return _error(400, "request body must be JSON")
        events = body.get("events") if isinstance(body, dict) else None
        if not isinstance(events, list) or not events:
            return _error(400, "events must be a nonempty array")
        if len(events) > TELEMETRY_MAX_BATCH:
            return _error(422, f"batch exceeds {TELEMETRY_MAX_BATCH} events")
        pending = self.db.query_one("SELECT COUNT(*) AS n FROM telemetry")["n"]
        if pending + len(events) > TELEMETRY_MAX_PENDING:
            return _error(429, f"telemetry backlog is full ({pending} pending); retry later (过载显式拒绝)")
        accepted = 0
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("event"), str) or not event["event"]:
                continue
            if not isinstance(event.get("timestamp"), str) or not event["timestamp"]:
                continue
            self.db.execute(
                "INSERT INTO telemetry (at, received_at, event, release_id, environment,"
                " page_definition_id, page_instance_id, locale, payload) VALUES (?,?,?,?,?,?,?,?,?)",
                (event["timestamp"], time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), event["event"],
                 str(event.get("release_id") or ""), str(event.get("environment") or ""),
                 str(event.get("page_definition_id") or ""), str(event.get("page_instance_id") or ""),
                 str(event.get("locale") or ""), json.dumps(event.get("payload") or {}, ensure_ascii=True,
                                                            sort_keys=True)))
            accepted += 1
        return JSONResponse(status_code=201, content=envelope(0, {"accepted": accepted, "rejected": len(events) - accepted}))

    # ---- 静态托管 ----

    def spa_app(self, name: str, index_path: Path):
        def handler(path: str = ""):
            if not index_path.is_file():
                return _error(404, f"app {name!r} is not deployed on this host (build output missing)")
            relative = path.strip("/")
            target = (index_path.parent / relative).resolve() if relative else index_path
            if not str(target).startswith(str(index_path.parent.resolve())):
                return _error(404, "not found")
            if target.is_file():
                return FileResponse(target)
            return FileResponse(index_path)
        return handler


def create_app(db: HostDatabase, apps_dir: Path | None = None) -> FastAPI:
    gateway = HostGateway(db, apps_dir)
    app = FastAPI(title="MicroFlow Host Reference", version="0.1.0")

    @app.post("/api/v1/dispatch")
    async def dispatch(request: Request) -> JSONResponse:
        return await gateway.dispatch(request)

    @app.post("/api/v1/telemetry")
    async def telemetry(request: Request) -> JSONResponse:
        return await gateway.telemetry_ingest(request)

    @app.get("/api/v1/health")
    def health() -> JSONResponse:
        return JSONResponse(content=envelope(0, {"status": "ok"}))

    if apps_dir is not None:
        root = Path(apps_dir)

        @app.get("/apps/{name}/{path:path}", include_in_schema=False)
        async def spa(name: str, path: str = ""):
            if name not in ("ops", "bizops", "orchestration"):
                return _error(404, "not found")
            return gateway.spa_app(name, root / name / "index.html")(path)

    return app
