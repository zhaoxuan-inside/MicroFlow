"""生命周期：阶段下发（不可跳过）、测试门禁与记录、debug 收集查询、场景执行转发、审批。

T12 对齐切片：config_hash 使用 SHA-256 规范化 JSON（跨进程稳定，不再用内置
hash）；下发同时记录 env_current 每环境生效版本指针，并可选携带平台图 →
MicroFlow flow 定义的转换摘要（flow_digest，需宿主环境安装 microflow）。
"""
import asyncio
import hashlib
import json
import urllib.request

from fastapi import Request

from . import db
from .web import require, guard

STAGES = ["dev", "test", "staging", "online"]


def _prev_stage(env: str) -> str | None:
    i = STAGES.index(env) if env in STAGES else -1
    return STAGES[i - 1] if i > 0 else None


def config_content_hash(value) -> str:
    """平台侧内容寻址：规范化 JSON（sort_keys + 紧凑分隔符）的 SHA-256。

    与 MicroFlow4Python 的 microflow-canonical-v1 类型化树不同构——平台哈希
    的契约对象是"画布图 JSON 本身"，语义在服务端文档与测试中固定。
    """
    def tree(item):
        if isinstance(item, dict):
            return {key: tree(item[key]) for key in sorted(item)}
        if isinstance(item, list):
            return [tree(entry) for entry in item]
        return item

    canonical = json.dumps(tree(value), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def flow_digest_of(graph) -> str | None:
    """平台画布图 → MicroFlow flow 骨架转换摘要；宿主未装 microflow 时如实返回 None。"""
    try:
        from microflow.platform_graph import convert_canvas_graph
    except ImportError:
        return None
    try:
        from microflow.platform_graph import canvas_digest
        converted = convert_canvas_graph(graph, str(graph.get("entry_node") or "flow"))
        return canvas_digest(converted["flow"])
    except Exception:  # noqa: BLE001 - 转换失败不是下发失败，缺 flow_digest 如实留空
        return None


async def _env_container(conn, env: str) -> dict:
    row = await conn.fetchrow(
        "SELECT env, base_url, token FROM env_containers WHERE env = $1", env)
    if row is None:
        raise ValueError(f"环境 {env} 未注册业务容器")
    return dict(row)


async def _http_post_json(url: str, payload: dict, token: str, timeout_s: float = 8.0) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Service-Token": token})

    def _do():
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode() or "{}")

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do)


async def _record_test(conn, subject_kind: str, subject_code: str, version: str,
                       env: str, status: str, inputs, output, error: str, ran_by: str) -> None:
    await conn.execute(
        "INSERT INTO tests (subject_kind, subject_code, version, env, status, inputs, output, error, ran_by) "
        "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)",
        subject_kind, subject_code, version, env, status,
        json.dumps(inputs, ensure_ascii=False) if inputs is not None else None,
        json.dumps(output, ensure_ascii=False) if output is not None else None,
        error, ran_by)


async def do_deploy(pool, deployed_by: str, code: str, version: str, env: str) -> dict:
    """阶段下发核心（守卫 + 推送 + 记录），供控制面路由与审批执行复用。"""
    if env not in STAGES:
        raise ValueError(f"非法环境：{env}（可用：{'/'.join(STAGES)}）")
    version_row = await pool.fetchrow(
        "SELECT graph, enable_saga FROM scenario_versions WHERE scenario_code = $1 AND version = $2",
        code, version)
    if version_row is None:
        raise KeyError(f"场景版本不存在：{code}@{version}")
    stage_index = STAGES.index(env)
    prev_stage = STAGES[stage_index - 1] if stage_index > 0 else None

    # 守卫 1：阶段顺序不可跳过
    if prev_stage is not None:
        prev_deployed = await pool.fetchval(
            "SELECT 1 FROM deployments WHERE asset_kind='scenario' AND asset_code = $1 "
            "AND version = $2 AND env = $3 LIMIT 1",
            code, version, prev_stage)
        if prev_deployed is None:
            raise ValueError(f"版本 {version} 尚未下发到 {prev_stage} 环境，"
                             f"不可跳过阶段直接下发到 {env}（流程：{' → '.join(STAGES)}）")

    # 守卫 2：E2E 门禁——当前阶段须有 debug 上报的真实执行 SUCCESS 记录
    if prev_stage is not None:
        e2e = await pool.fetchval(
            "SELECT 1 FROM debug_io WHERE scenario_code = $1 AND version = $2 AND env = $3 "
            "AND status = 'SUCCESS' LIMIT 1",
            code, version, prev_stage)
        if e2e is None:
            raise ValueError(f"版本 {version} 在 {prev_stage} 环境尚无 debug 上报的端到端执行记录，"
                             f"不可下发到 {env}（开启 debug 模式完成真实场景执行后重试）")

    graph = version_row["graph"] if not isinstance(version_row["graph"], str) \
        else json.loads(version_row["graph"])
    container = await _env_container(pool, env)
    config_hash = config_content_hash(graph)
    digest = flow_digest_of(graph)
    try:
        await _http_post_json(
            f"{container['base_url']}/container/configs",
            {"scenario_code": code, "version": version, "graph": graph,
             "enable_saga_compensation": bool(version_row["enable_saga"]),
             "config_hash": config_hash},
            container["token"])
    except Exception as exc:  # noqa: BLE001
        return {"deployed": False, "env": env, "error": f"下发失败：{exc}"}
    await pool.execute(
        "INSERT INTO deployments (asset_kind, asset_code, version, env, config_hash, flow_digest, deployed_by) "
        "VALUES ('scenario', $1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
        code, version, env, config_hash, digest, deployed_by)
    await pool.execute(
        "INSERT INTO env_current (asset_kind, asset_code, env, version, config_hash, flow_digest, deployed_by, updated_at) "
        "VALUES ('scenario', $1, $2, $3, $4, $5, $6, now()) "
        "ON CONFLICT (asset_kind, asset_code, env) DO UPDATE SET "
        "version = $3, config_hash = $4, flow_digest = $5, deployed_by = $6, updated_at = now()",
        code, env, version, config_hash, digest, deployed_by)
    return {"deployed": True, "env": env, "version": version,
            "config_hash": config_hash, "flow_digest": digest}


scenario_routes = {}
operators_routes = {}
approval_routes = {}


@guard
async def scenario_deploy(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    body = await request.json()
    version = str(body.get("version") or "")
    env = str(body.get("env") or "")
    pool = await db.pool()
    result = await do_deploy(pool, user["email"], code, version, env)
    return {**result, "code": code}


scenario_routes["deploy"] = scenario_deploy


@guard
async def scenario_deployments(request: Request) -> dict:
    await require(request, "orchestration:read")
    code = request.path_params["code"]
    pool = await db.pool()
    rows = await pool.fetch(
        "SELECT version, env, config_hash, flow_digest, deployed_by, deployed_at FROM deployments "
        "WHERE asset_kind='scenario' AND asset_code = $1 ORDER BY deployed_at DESC", code)
    current = await pool.fetch(
        "SELECT env, version, config_hash, flow_digest, updated_at FROM env_current "
        "WHERE asset_kind='scenario' AND asset_code = $1", code)
    return {"deployments": [dict(r) for r in rows],
            "current": {r["env"]: dict(r) for r in current}}


scenario_routes["deployments"] = scenario_deployments


@guard
async def scenario_rollback(request: Request) -> dict:
    """回滚 = 对旧版本重新执行阶段下发（do_deploy 守卫照常生效）。

    env_current 记录每环境生效版本：回滚把指针拨回目标版本，deployments
    账本保留追加日志（谁在何时从哪个版本回拨）。
    """
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    body = await request.json()
    version = str(body.get("version") or "")
    env = str(body.get("env") or "")
    if env not in STAGES:
        raise ValueError(f"非法环境：{env}")
    pool = await db.pool()
    exists = await pool.fetchval(
        "SELECT 1 FROM scenario_versions WHERE scenario_code = $1 AND version = $2", code, version)
    if exists is None:
        raise KeyError(f"场景版本不存在：{code}@{version}")
    current = await pool.fetchval(
        "SELECT version FROM env_current WHERE asset_kind='scenario' AND asset_code = $1 AND env = $2",
        code, env)
    if current == version:
        raise ValueError(f"{env} 环境当前生效版本已是 {version}，无需回滚")
    result = await do_deploy(pool, user["email"], code, version, env)
    if result.get("deployed"):
        result["rolled_back_from"] = current
    return {**result, "code": code, "env": env}


scenario_routes["rollback"] = scenario_rollback


@guard
async def scenario_version_diff(request: Request) -> dict:
    """部署 diff 数据源：两版本画布图 + 内容寻址摘要（不再依赖宿主 dag.list）。"""
    await require(request, "orchestration:read")
    code = request.path_params["code"]
    q = dict(request.query_params)
    left, right = str(q.get("left") or ""), str(q.get("right") or "")
    if not left or not right:
        raise ValueError("需要 left 与 right 两个版本号")
    pool = await db.pool()
    async def load(version: str) -> dict:
        row = await pool.fetchrow(
            "SELECT version, graph, enable_saga, changelog, created_by, created_at "
            "FROM scenario_versions WHERE scenario_code = $1 AND version = $2", code, version)
        if row is None:
            raise KeyError(f"场景版本不存在：{code}@{version}")
        graph = row["graph"] if not isinstance(row["graph"], str) else json.loads(row["graph"])
        return {"version": row["version"], "graph": graph, "enable_saga": row["enable_saga"],
                "changelog": row["changelog"], "created_by": row["created_by"],
                "created_at": row["created_at"], "config_hash": config_content_hash(graph),
                "flow_digest": flow_digest_of(graph)}
    return {"left": await load(left), "right": await load(right)}


scenario_routes["version_diff"] = scenario_version_diff


@guard
async def scenario_execute(request: Request) -> dict:
    """场景执行转发：控制面按环境转发到对应业务容器执行（真实业务数据路径）。"""
    user = await require(request, "page:orchestrate")
    code = request.path_params["code"]
    body = await request.json()
    env = str(body.get("env") or "dev")
    if env not in STAGES:
        raise ValueError(f"非法环境：{env}")
    pool = await db.pool()
    container = await _env_container(pool, env)
    # E2E 语义＝真实业务数据 + debug 开启：先确保目标容器 debug 打开，
    # 否则逐算子 I/O 不会上报，推进门禁将失去依据。
    try:
        await _http_post_json(
            f"{container['base_url']}/container/debug",
            {"enabled": True}, container["token"], timeout_s=10.0)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"开启 {env} 环境容器 debug 模式失败：{exc}") from exc
    try:
        result = await _http_post_json(
            f"{container['base_url']}/container/execute/scenario",
            {"scenario_code": code, "inputs": body.get("inputs") or {}, "env": env},
            container["token"], timeout_s=30.0)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"调用 {env} 环境业务容器执行失败：{exc}") from exc
    if result.get("status"):
        async with pool.acquire() as conn:
            await _record_test(conn, "scenario", code,
                               str(result.get("version") or body.get("version") or ""),
                               env, "passed" if result.get("status") == "SUCCESS" else "failed",
                               body.get("inputs") or {}, result.get("final_output"),
                               str(result.get("error_message") or ""), user["email"])
        # 告警求值挂点：场景执行结果（真实业务数据路径）。
        from datetime import datetime, timezone
        from . import alerting
        await alerting.process(pool, [{
            "scenario_code": code, "env": env, "node_id": "",
            "status": str(result.get("status") or ""),
            "reported_at": datetime.now(timezone.utc).isoformat()}])
    return result


scenario_routes["execute"] = scenario_execute


@guard
async def operator_test_run(request: Request) -> dict:
    """算子单元测试：算子代码注册进对应环境容器 → 容器执行 → 结果入测试记录。"""
    user = await require(request, "page:orchestrate")
    name = request.path_params["name"]
    body = await request.json()
    version = str(body.get("version") or "")
    env = str(body.get("env") or "dev")
    inputs = body.get("inputs") or {}
    if env not in STAGES:
        raise ValueError(f"非法环境：{env}")
    pool = await db.pool()
    version_row = await pool.fetchrow(
        "SELECT code, entry_function FROM operator_versions WHERE operator_name = $1 AND version = $2",
        name, version)
    if version_row is None:
        raise KeyError(f"算子版本不存在：{name}@{version}")
    container = await _env_container(pool, env)
    try:
        await _http_post_json(
            f"{container['base_url']}/container/operators/register",
            {"name": name, "code": version_row["code"],
             "entry_function": version_row["entry_function"], "version": version},
            container["token"])
        result = await _http_post_json(
            f"{container['base_url']}/container/operators/execute",
            {"name": name, "inputs": inputs},
            container["token"])
    except Exception as exc:  # noqa: BLE001
        result = {"status": "FAILED", "error": str(exc), "output": None, "duration_ms": 0}
    raw_status = result.get("status") or "FAILED"
    status = "passed" if raw_status in ("passed", "SUCCESS") else "failed"
    async with pool.acquire() as conn:
        await _record_test(conn, "operator", name, version, env, status,
                           inputs, result.get("output"), str(result.get("error") or ""),
                           user["email"])
        await conn.execute(
            "UPDATE operator_versions SET unit_test = $3 WHERE operator_name = $1 AND version = $2",
            name, version, status)
    return {"status": status, "env": env, "output": result.get("output"),
            "duration_ms": result.get("duration_ms"), "error": result.get("error")}


operators_routes["test_run"] = operator_test_run


@guard
async def tests_query(request: Request) -> dict:
    await require(request, "orchestration:read")
    pool = await db.pool()
    q = dict(request.query_params)
    rows = await pool.fetch(
        "SELECT subject_kind, subject_code, version, env, status, inputs, output, error, ran_by, ran_at "
        "FROM tests WHERE ($1::text IS NULL OR subject_kind = $1) "
        "AND ($2::text IS NULL OR subject_code = $2) "
        "ORDER BY ran_at DESC LIMIT $3",
        q.get("subject_kind") or None, q.get("subject_code") or None,
        min(int(q.get("limit") or 50), 200))
    return {"tests": [
        {**dict(r), "inputs": json.loads(r["inputs"]) if r["inputs"] else None,
         "output": json.loads(r["output"]) if r["output"] else None}
        for r in rows]}


operators_routes["tests_query"] = tests_query
scenario_routes["tests_query"] = tests_query


# ---------------------------------------------------------------------------
# 发布审批（第二人确认制：staging/online 下发须审批；同人不可自审）
# ---------------------------------------------------------------------------
approval_routes = {}


@guard
async def approvals_list(request: Request) -> dict:
    await require(request, "orchestration:read")
    pool = await db.pool()
    q = dict(request.query_params)
    rows = await pool.fetch(
        "SELECT id, asset_kind, asset_code, version, env, status, note, requested_by, approver, "
        "created_at, decided_at FROM approvals WHERE ($1::text IS NULL OR status = $1) "
        "ORDER BY created_at DESC LIMIT 200",
        q.get("status") or None)
    return {"approvals": [dict(r) for r in rows], "total": len(rows)}


approval_routes["list"] = approvals_list


@guard
async def approvals_request(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    body = await request.json()
    asset_kind = str(body.get("asset_kind") or "scenario")
    asset_code = str(body.get("asset_code") or "")
    version = str(body.get("version") or "")
    env = str(body.get("env") or "")
    if asset_kind != "scenario" or env not in ("staging", "online"):
        raise ValueError("审批仅适用于场景向 staging/online 的阶段下发")
    pool = await db.pool()
    dup = await pool.fetchval(
        "SELECT 1 FROM approvals WHERE asset_kind=$1 AND asset_code=$2 AND version=$3 "
        "AND env=$4 AND status='PENDING' AND requested_by=$5 LIMIT 1",
        asset_kind, asset_code, version, env, user["email"])
    if dup:
        raise ValueError("同一版本的同阶段审批单已存在（等待审批）")
    await pool.execute(
        "INSERT INTO approvals (asset_kind, asset_code, version, env, note, requested_by) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        asset_kind, asset_code, version, env,
        str(body.get("note") or ""), user["email"])
    return {"requested": True, "asset_code": asset_code, "version": version, "env": env}


approval_routes["request"] = approvals_request


@guard
async def approvals_decide(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    body = await request.json()
    approval_id = str(body.get("approval_id") or "")
    decision = str(body.get("decision") or "")
    if decision not in ("approve", "reject"):
        raise ValueError("decision 必须是 approve 或 reject")
    pool = await db.pool()
    row = await pool.fetchrow("SELECT * FROM approvals WHERE id = $1", approval_id)
    if row is None:
        raise KeyError("审批单不存在")
    if row["status"] != "PENDING":
        raise ValueError(f"审批单已处理（{row['status']}）")
    if row["requested_by"] == user["email"]:
        raise ValueError("审批人不能与发起人相同（第二人确认制）")
    if decision == "reject":
        await pool.execute(
            "UPDATE approvals SET status='REJECTED', approver=$2, decided_at=now() WHERE id=$1",
            user["email"], approval_id)
        return {"approved": False, "approval_id": approval_id}
    result = await do_deploy(pool, user["email"], row["asset_code"], row["version"], row["env"])
    await pool.execute(
        "UPDATE approvals SET status='APPROVED', approver=$2, decided_at=now() WHERE id=$1",
        user["email"], approval_id)
    return {"approved": True, "result": result}


approval_routes["decide"] = approvals_decide
