"""编排管理平台控制面后端（独立服务 :8200，独立账号体系与独立存储 orch_control）。

信封协议 {code,data,message,trace_id} 与业务平台网关一致。业务容器经
X-Service-Token 调用 /container/* 端点（注册上报 / debug I-O 上报）。
"""
import json
import os
import secrets
import uuid

from fastapi import FastAPI, Request

from . import db
from . import catalog
from . import lifecycle
from . import experiments
from . import configcenter
from . import alerting
from .web import envelope, err, guard, require, require_service_token

app = FastAPI(title="Orchestrator Control Plane", docs_url=None, redoc_url=None)


async def _ingest_container_operators(env: str, operators: list[dict]) -> int:
    """业务容器算子注册上报 → 目录登记（source=container:{env}）。"""
    pool = await db.pool()
    count = 0
    for op in operators[:500]:
        name = str(op.get("name") or "").strip()
        if not name:
            continue
        version = str(op.get("version") or "v1.0.0")
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT source_env FROM operators WHERE name = $1", name)
            if row is None:
                await conn.execute(
                    "INSERT INTO operators (name, display_name, domain, description, source, "
                    "source_env, current_version, created_by) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    name, str(op.get("display_name") or name), str(op.get("domain") or "custom"),
                    str(op.get("description") or ""), f"container:{env}", env,
                    version, f"container:{env}")
                count += 1
            await conn.execute(
                "INSERT INTO operator_versions (operator_name, version, code, entry_function, "
                "changelog, created_by) VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (operator_name, version) DO NOTHING",
                name, version, str(op.get("code") or ""),
                str(op.get("entry_function") or "action_entry"),
                f"容器注册上报（{env}）", f"container:{env}")
    return count


async def _ingest_debug_io(body: dict) -> int:
    """业务容器 debug 模式逐算子 I/O 上报 → 持久化（E2E 门禁数据源）。

    兼容两种负载：顶层 scenario/version/env + records；或字段在每条记录内。
    """
    pool = await db.pool()
    records = body.get("records") or []
    accepted = 0
    async with pool.acquire() as conn:
        for r in records[:200]:
            scenario_code = str(r.get("scenario_code") or body.get("scenario_code") or "")
            version = str(r.get("version") or body.get("version") or "")
            env = str(r.get("env") or body.get("env") or "")
            await conn.execute(
                "INSERT INTO debug_io (scenario_code, version, env, node_id, inputs, outputs, "
                "status, duration_ms) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8)",
                scenario_code, version, env, str(r.get("node_id") or ""),
                json.dumps(r.get("inputs"), ensure_ascii=False) if r.get("inputs") is not None else None,
                json.dumps(r.get("outputs"), ensure_ascii=False) if r.get("outputs") is not None else None,
                str(r.get("status") or ""), float(r.get("duration_ms") or 0))
            accepted += 1
    return accepted


@app.post("/api/container/register-operators")
async def container_register_operators(request: Request):
    try:
        require_service_token(request)
    except PermissionError as exc:
        return err(403, str(exc))
    body = await request.json()
    env = str(body.get("env") or "")
    if not env:
        return err(400, "缺少 env")
    accepted = await _ingest_container_operators(env, body.get("operators") or [])
    return envelope({"env": env, "accepted": accepted})


@app.post("/api/container/report-node-io")
async def container_report_node_io(request: Request):
    try:
        require_service_token(request)
    except PermissionError as exc:
        return err(403, str(exc))
    body = await request.json()
    accepted = await _ingest_debug_io(body)
    # 告警求值挂点：debug I/O 上报后同步评估规则（最小闭环不做后台定时器）。
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    records = [{**r, "reported_at": now_iso} for r in (body.get("records") or [])[:200]
               if r.get("scenario_code") or body.get("scenario_code")]
    evaluated = 0
    if records:
        evaluated = await alerting.process(await db.pool(), records)
    return envelope({"accepted": accepted, "alerts_fired": evaluated})


@app.get("/api/envs")
@guard
async def envs_list(request: Request):
    await require(request, "orchestration:read")
    pool = await db.pool()
    rows = await pool.fetch("SELECT env, base_url FROM env_containers ORDER BY env")
    return {"envs": [dict(r) for r in rows]}


@app.get("/api/debug-io")
@guard
async def debug_io_query(request: Request):
    await require(request, "orchestration:read")
    pool = await db.pool()
    q = dict(request.query_params)
    rows = await pool.fetch(
        "SELECT scenario_code, version, env, node_id, inputs, outputs, status, duration_ms, "
        "reported_at::text AS reported_at "
        "FROM debug_io WHERE ($1::text IS NULL OR scenario_code = $1) "
        "AND ($2::text IS NULL OR env = $2) ORDER BY reported_at DESC LIMIT $3",
        q.get("scenario_code") or None, q.get("env") or None,
        min(int(q.get("limit") or 100), 500))
    return {"records": [
        {**dict(r), "inputs": json.loads(r["inputs"]) if r["inputs"] else None,
         "outputs": json.loads(r["outputs"]) if r["outputs"] else None}
        for r in rows]}


# ---------------------------------------------------------------------------
# 账号（独立账号体系）
# ---------------------------------------------------------------------------
@app.post("/api/auth/login")
@guard
async def auth_login(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    pool = await db.pool()
    row = await pool.fetchrow(
        "SELECT id, email, nickname, password_hash, role FROM users WHERE email = $1", email)
    if row is None or not db.verify_password(password, row["password_hash"]):
        raise ValueError("邮箱或密码错误")
    token = secrets.token_urlsafe(32)
    from datetime import datetime, timedelta, timezone
    expires = datetime.now(timezone.utc) + timedelta(hours=72)
    await pool.execute(
        "INSERT INTO sessions (token, user_id, email, nickname, role, expires_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        token, row["id"], row["email"], row["nickname"], row["role"], expires)
    return {"token": token, "email": row["email"], "nickname": row["nickname"], "role": row["role"]}


@app.post("/api/auth/register")
@guard
async def auth_register(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    nickname = str(body.get("nickname") or email.split("@")[0])
    if "@" not in email or len(password) < 8:
        raise ValueError("邮箱非法或密码少于 8 位")
    pool = await db.pool()
    exists = await pool.fetchval("SELECT 1 FROM users WHERE email = $1", email)
    if exists:
        raise ValueError("邮箱已被注册")
    await pool.execute(
        "INSERT INTO users (email, nickname, password_hash, role) VALUES ($1, $2, $3, 'viewer')",
        email, nickname, db.hash_password(password))
    return {"email": email}


@app.get("/api/auth/me")
@guard
async def auth_me(request: Request):
    from .web import ROLE_PERMS
    user = await require(request, "orchestration:read")
    return {"user_id": user["user_id"], "email": user["email"], "nickname": user["nickname"],
            "role": user["role"], "permissions": sorted(ROLE_PERMS.get(user["role"], set()))}


# ---------------------------------------------------------------------------
# 目录与生命周期路由挂载（catalog/lifecycle 模块提供处理函数）
# ---------------------------------------------------------------------------
def _mount(method: str, path: str, handler) -> None:
    """注册目录/生命周期路由：handler 已在模块层经 guard 包装，不再二次包装。"""
    if method == "GET":
        app.get(path)(handler)
    elif method == "POST":
        app.post(path)(handler)
    elif method == "DELETE":
        app.delete(path)(handler)


# 算子
_mount("GET", "/api/operators", catalog.operators_routes["list"])
_mount("POST", "/api/operators/create", catalog.operators_routes["create"])
_mount("GET", "/api/operators/{name}", catalog.operators_routes["detail"])
_mount("POST", "/api/operators/{name}/versions", catalog.operators_routes["save_version"])
_mount("POST", "/api/operators/{name}/publish", catalog.operators_routes["publish"])
_mount("POST", "/api/operators/{name}/test", lifecycle.operators_routes["test_run"])
_mount("GET", "/api/operators/{name}/references", catalog.operators_routes["references"])
_mount("POST", "/api/operators/{name}/copy", catalog.operators_routes["copy"])
_mount("DELETE", "/api/operators/{name}", catalog.operators_routes["delete"])
_mount("GET", "/api/operators/{name}/tests", lifecycle.operators_routes["tests_query"])
_mount("POST", "/api/operators/{name}/lock", catalog.operator_lock_routes["acquire"])
_mount("DELETE", "/api/operators/{name}/lock", catalog.operator_lock_routes["release"])
_mount("GET", "/api/operators/{name}/lock", catalog.operator_lock_routes["status"])
_mount("POST", "/api/subgraphs/{code}/lock", catalog.subgraph_lock_routes["acquire"])
_mount("DELETE", "/api/subgraphs/{code}/lock", catalog.subgraph_lock_routes["release"])
_mount("POST", "/api/scenarios/{code}/lock", catalog.scenario_lock_routes["acquire"])
_mount("DELETE", "/api/scenarios/{code}/lock", catalog.scenario_lock_routes["release"])

# 子图
_mount("GET", "/api/subgraphs", catalog.subgraph_routes["list"])
_mount("POST", "/api/subgraphs/create", catalog.subgraph_routes["create"])
_mount("GET", "/api/subgraphs/{code}", catalog.subgraph_routes["detail"])
_mount("POST", "/api/subgraphs/{code}/versions", catalog.subgraph_routes["save_version"])
_mount("POST", "/api/subgraphs/{code}/copy", catalog.subgraph_routes["copy"])
_mount("DELETE", "/api/subgraphs/{code}", catalog.subgraph_routes["delete"])

# 场景
_mount("GET", "/api/scenarios", catalog.scenario_routes["list"])
_mount("POST", "/api/scenarios/create", catalog.scenario_routes["create"])
_mount("GET", "/api/scenarios/{code}", catalog.scenario_routes["detail"])
_mount("POST", "/api/scenarios/{code}/versions", catalog.scenario_routes["save_version"])
_mount("POST", "/api/scenarios/{code}/deploy", lifecycle.scenario_routes["deploy"])
_mount("GET", "/api/scenarios/{code}/deployments", lifecycle.scenario_routes["deployments"])
_mount("POST", "/api/scenarios/{code}/execute", lifecycle.scenario_routes["execute"])
_mount("GET", "/api/scenarios/{code}/tests", lifecycle.scenario_routes["tests_query"])
_mount("DELETE", "/api/scenarios/{code}", catalog.scenario_routes["delete"])

# 发布审批（第二人确认制）
_mount("GET", "/api/approvals", lifecycle.approval_routes["list"])
_mount("POST", "/api/approvals/request", lifecycle.approval_routes["request"])
_mount("POST", "/api/approvals/decide", lifecycle.approval_routes["decide"])

# 回滚与版本 diff（T12 对齐：env_current 指针 + SHA-256 内容寻址）
_mount("POST", "/api/scenarios/{code}/rollback", lifecycle.scenario_routes["rollback"])
_mount("GET", "/api/scenarios/{code}/version-diff", lifecycle.scenario_routes["version_diff"])

# A/B 实验域（控制面自有实现）
_mount("GET", "/api/experiments", experiments.routes["list"])
_mount("POST", "/api/experiments/create", experiments.routes["create"])
_mount("GET", "/api/experiments/{key}", experiments.routes["detail"])
_mount("POST", "/api/experiments/{key}/update", experiments.routes["update"])
_mount("POST", "/api/experiments/{key}/status", experiments.routes["status"])
_mount("DELETE", "/api/experiments/{key}", experiments.routes["delete"])
_mount("POST", "/api/experiments/{key}/assign", experiments.routes["assign"])
_mount("GET", "/api/experiments/{key}/readout", experiments.routes["readout"])

# 配置中心（命名空间/配置项/版本/灰度）
_mount("GET", "/api/configcenter/namespaces", configcenter.routes["namespaces_list"])
_mount("POST", "/api/configcenter/namespaces/create", configcenter.routes["namespaces_create"])
_mount("GET", "/api/configcenter/namespaces/{namespace}/items", configcenter.routes["items_list"])
_mount("POST", "/api/configcenter/namespaces/{namespace}/items/create", configcenter.routes["items_create"])
_mount("POST", "/api/configcenter/namespaces/{namespace}/items/{key}/versions",
       configcenter.routes["items_version_save"])
_mount("GET", "/api/configcenter/namespaces/{namespace}/items/{key}/history",
       configcenter.routes["items_history"])
_mount("POST", "/api/configcenter/namespaces/{namespace}/items/{key}/publish",
       configcenter.routes["items_publish"])
_mount("POST", "/api/configcenter/namespaces/{namespace}/items/{key}/rollback",
       configcenter.routes["items_rollback"])
_mount("GET", "/api/configcenter/namespaces/{namespace}/items/{key}/resolve",
       configcenter.routes["items_resolve"])

# 告警（控制面承载；列表/确认/规则）
_mount("GET", "/api/alerts", alerting.routes["list"])
_mount("POST", "/api/alerts/{alert_id}/ack", alerting.routes["ack"])
_mount("GET", "/api/alerts/rules", alerting.routes["rules_list"])
_mount("POST", "/api/alerts/rules", alerting.routes["rules_save"])
_mount("DELETE", "/api/alerts/rules/{rule_id}", alerting.routes["rules_delete"])


@app.on_event("startup")
async def _startup() -> None:
    bootstrap = await db.init_schema()
    if bootstrap.get("bootstrap_admin_password"):
        print(f"[orch-control] 内置管理员 {bootstrap['bootstrap_admin_email']} "
              f"初始密码：{bootstrap['bootstrap_admin_password']}（请立即妥善保存）")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await db.close_pool()
