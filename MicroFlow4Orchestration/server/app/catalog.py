"""目录：算子/子图/场景 CRUD、版本（自动版本号）、引用计数、删除守卫、复制。"""
import re

from fastapi import Request

from . import db
from . import locks
from .web import require, guard

_VERSION_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def _derive_version(existing: list[str]) -> str:
    """最高语义版本 patch+1；无语义版本时 v1.0.{n+1}。"""
    nums = [tuple(int(x) for x in m.groups()) for v in existing if (m := _VERSION_RE.match(v))]
    if nums:
        maj, mi, pa = max(nums)
        return f"v{maj}.{mi}.{pa + 1}"
    return f"v1.0.{len(existing) + 1}"


async def next_version(conn, table: str, code_col: str, code_val: str, *,
                       status_col: str | None = None,
                       deploy_kind: str | None = None) -> str:
    """自动版本号：最新版本仍是可编辑草稿（未下发/未发布）→ 就地覆盖；
    否则基于最高语义版本 patch+1 派生新版本（永不动已发布版本）。"""
    select = f"SELECT version{', ' + status_col if status_col else ''} FROM {table} WHERE {code_col} = $1"
    rows = await conn.fetch(select, code_val)
    versions = [r["version"] for r in rows]
    if not versions:
        return "v1.0.0"
    latest = max(versions, key=lambda v: (tuple(int(x) for x in m.groups())
                                          if (m := _VERSION_RE.match(v)) else (0, 0, -1)))
    latest_row = next((r for r in rows if r["version"] == latest), None)
    if deploy_kind is not None:
        deployed = await conn.fetchval(
            "SELECT 1 FROM deployments WHERE asset_kind = $1 AND asset_code = $2 "
            "AND version = $3 LIMIT 1",
            deploy_kind, code_val, latest)
        if deployed is None:
            return latest  # 未下发过：仍为草稿，就地覆盖
    if status_col is not None and latest_row is not None and latest_row[status_col] == "PUBLISHED":
        return _derive_version(versions)  # 已发布版本不可编辑，派生新草稿
    return latest  # 未发布的最新版本：就地覆盖


async def _scan_operator_references(conn, operator_name: str) -> list[str]:
    """扫描子图/场景版本 graph，返回引用该算子的 '子图 code@version' / '场景 code@version' 清单。"""
    refs: list[str] = []
    for row in await conn.fetch("SELECT subgraph_code, version, graph FROM subgraph_versions"):
        graph = row["graph"] if not isinstance(row["graph"], str) else _load_json(row["graph"])
        for node in (graph or {}).get("nodes") or []:
            if node.get("operator") == operator_name:
                refs.append(f"子图 {row['subgraph_code']}@{row['version']}")
                break
    for row in await conn.fetch("SELECT scenario_code, version, graph FROM scenario_versions"):
        graph = row["graph"] if not isinstance(row["graph"], str) else _load_json(row["graph"])
        for node in (graph or {}).get("nodes") or []:
            if node.get("operator") == operator_name:
                refs.append(f"场景 {row['scenario_code']}@{row['version']}")
                break
    return refs


async def _scan_subgraph_references(conn, subgraph_code: str) -> list[str]:
    refs: list[str] = []
    for row in await conn.fetch("SELECT scenario_code, version, graph FROM scenario_versions"):
        graph = row["graph"] if not isinstance(row["graph"], str) else _load_json(row["graph"])
        for node in (graph or {}).get("nodes") or []:
            if node.get("subgraph") == subgraph_code:
                refs.append(f"场景 {row['scenario_code']}@{row['version']}")
                break
    return refs


def _load_json(raw):
    import json
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw


operators_routes = {}


@guard
async def operators_list(request: Request) -> dict:
    await require(request, "orchestration:read")
    pool = await db.pool()
    rows = await pool.fetch(
        "SELECT o.name, o.display_name, o.domain, o.description, o.source, o.source_env, "
        "o.current_version, o.updated_at, "
        "COALESCE(v.unit_test, 'untested') AS unit_test "
        "FROM operators o LEFT JOIN operator_versions v "
        "ON v.operator_name = o.name AND v.version = o.current_version ORDER BY o.name")
    out = []
    for r in rows:
        refs = await _scan_operator_references(pool, r["name"])
        lock = await locks.status_of(pool, "operator", r["name"])
        out.append({**dict(r), "referenced_count": len(refs), "referenced_by": refs,
                    "in_use": bool(refs), "lock_status": lock})
    return {"operators": out, "total": len(out)}


operators_routes["list"] = operators_list


@guard
async def operators_create(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    body = await request.json()
    name = str(body.get("name") or "").strip()
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.]{1,63}", name):
        raise ValueError("算子名非法：字母开头，仅字母/数字/下划线/点号，长度 2-64")
    pool = await db.pool()
    exists = await pool.fetchval("SELECT 1 FROM operators WHERE name = $1", name)
    if exists:
        raise ValueError(f"算子名已存在：{name}")
    display_name = str(body.get("display_name") or name)
    domain = str(body.get("domain") or "custom")
    description = str(body.get("description") or "")
    code = str(body.get("code") or "")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO operators (name, display_name, domain, description, source, source_env, "
                "current_version, created_by) VALUES ($1, $2, $3, $4, 'platform', '', 'v1.0.0', $5)",
                name, display_name, domain, description, user["email"])
            await conn.execute(
                "INSERT INTO operator_versions (operator_name, version, code, changelog, created_by) "
                "VALUES ($1, 'v1.0.0', $2, '初始版本', $3)",
                name, code, user["email"])
    return {"name": name, "version": "v1.0.0"}


operators_routes["create"] = operators_create


@guard
async def operators_detail(request: Request) -> dict:
    await require(request, "orchestration:read")
    name = request.path_params["name"]
    pool = await db.pool()
    op = await pool.fetchrow(
        "SELECT * FROM operators WHERE name = $1", name)
    if op is None:
        raise KeyError(f"算子不存在：{name}")
    versions = await pool.fetch(
        "SELECT version, code, entry_function, changelog, status, unit_test, created_by, created_at "
        "FROM operator_versions WHERE operator_name = $1 ORDER BY created_at DESC",
        name)
    refs = await _scan_operator_references(pool, name)
    deployments = await pool.fetch(
        "SELECT version, env, deployed_at FROM deployments "
        "WHERE asset_kind='operator' AND asset_code = $1 ORDER BY deployed_at DESC", name)
    return {**dict(op), "referenced_by": refs, "referenced_count": len(refs),
            "versions": [dict(v) for v in versions],
            "deployments": [dict(d) for d in deployments]}


operators_routes["detail"] = operators_detail


@guard
async def operators_save_version(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    name = request.path_params["name"]
    body = await request.json()
    code = str(body.get("code") or "")
    entry_function = str(body.get("entry_function") or "action_entry")
    changelog = str(body.get("changelog") or "更新算子脚本")
    if not code.strip():
        raise ValueError("算子脚本不能为空")
    pool = await db.pool()
    exists = await pool.fetchval("SELECT 1 FROM operators WHERE name = $1", name)
    if not exists:
        raise KeyError(f"算子不存在：{name}")
    await locks.require(pool, "operator", name, user["email"])
    async with pool.acquire() as conn:
        async with conn.transaction():
            version = await next_version(conn, "operator_versions", "operator_name", name,
                                         status_col="status")
            await conn.execute(
                "INSERT INTO operator_versions (operator_name, version, code, entry_function, "
                "changelog, created_by) VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (operator_name, version) DO UPDATE SET code = $3, "
                "entry_function = $4, changelog = $5, status = 'DRAFT', unit_test = NULL",
                name, version, code, entry_function, changelog, user["email"])
            await conn.execute(
                "UPDATE operators SET current_version = $2, updated_at = now() WHERE name = $1",
                name, version)
    return {"name": name, "version": version, "changelog": changelog}


operators_routes["save_version"] = operators_save_version


@guard
async def operators_publish(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    name = request.path_params["name"]
    body = await request.json()
    version = str(body.get("version") or "")
    pool = await db.pool()
    row = await pool.fetchrow(
        "SELECT unit_test, code, entry_function FROM operator_versions "
        "WHERE operator_name = $1 AND version = $2", name, version)
    if row is None:
        raise KeyError(f"版本不存在：{name}@{version}")
    await locks.require(pool, "operator", name, user["email"])
    if row["unit_test"] != "passed":
        raise ValueError(f"算子 {name}@{version} 未通过单元测试，禁止发布（先在详情页完成测试）")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE operator_versions SET status = 'PUBLISHED' WHERE operator_name = $1 AND version = $2",
                name, version)
            await conn.execute(
                "UPDATE operator_versions SET status = 'SUPERSEDED' "
                "WHERE operator_name = $1 AND version <> $2 AND status = 'PUBLISHED'", name, version)
            await conn.execute(
                "UPDATE operators SET current_version = $2, updated_at = now() WHERE name = $1",
                name, version)
    # 发布 = 下发算子代码到全部环境容器（注册进各容器算子池）
    from .lifecycle import deployer
    results = await deployer.push_operator_to_all_envs(
        {"name": name, "code": row["code"], "entry_function": row["entry_function"],
         "version": version})
    return {"name": name, "version": version, "push_results": results}


operators_routes["publish"] = operators_publish


@guard
async def operators_delete(request: Request) -> dict:
    await require(request, "orchestration:write")
    name = request.path_params["name"]
    pool = await db.pool()
    refs = await _scan_operator_references(pool, name)
    if refs:
        raise ValueError(f"算子 {name} 仍被引用：{'、'.join(refs[:5])}——请先下线或重新编排这些版本")
    await pool.execute("DELETE FROM operators WHERE name = $1", name)
    return {"name": name, "deleted": True}


operators_routes["delete"] = operators_delete


@guard
async def operators_copy(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    name = request.path_params["name"]
    body = await request.json()
    new_name = str(body.get("new_name") or "").strip()
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.]{1,63}", new_name):
        raise ValueError("新算子名非法")
    pool = await db.pool()
    src = await pool.fetchrow("SELECT * FROM operators WHERE name = $1", name)
    if src is None:
        raise KeyError(f"算子不存在：{name}")
    dup = await pool.fetchval("SELECT 1 FROM operators WHERE name = $1", new_name)
    if dup:
        raise ValueError(f"算子名已存在：{new_name}")
    latest = await pool.fetchrow(
        "SELECT code, entry_function, description FROM operator_versions "
        "WHERE operator_name = $1 ORDER BY created_at DESC LIMIT 1", name)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO operators (name, display_name, domain, description, source, source_env, "
                "current_version, created_by) VALUES ($1, $2, $3, $4, 'platform', '', 'v1.0.0', $5)",
                new_name, f"{src['display_name']}_copy" if src["display_name"] else new_name,
                src["domain"], f"复制自 {name}", user["email"])
            await conn.execute(
                "INSERT INTO operator_versions (operator_name, version, code, entry_function, "
                "changelog, created_by) VALUES ($1, 'v1.0.0', $2, $3, $4, $5)",
                new_name, latest["code"] if latest else "",
                latest["entry_function"] if latest else "action_entry",
                f"复制自 {name}", user["email"])
    return {"name": new_name, "copied_from": name}


operators_routes["copy"] = operators_copy


@guard
async def operators_references(request: Request) -> dict:
    await require(request, "orchestration:read")
    name = request.path_params["name"]
    pool = await db.pool()
    refs = await _scan_operator_references(pool, name)
    return {"referenced_by": refs, "referenced_count": len(refs)}


operators_routes["references"] = operators_references


# ---------------------------------------------------------------------------
# 子图
# ---------------------------------------------------------------------------
subgraph_routes = {}


@guard
async def subgraphs_list(request: Request) -> dict:
    await require(request, "orchestration:read")
    pool = await db.pool()
    rows = await pool.fetch("SELECT * FROM subgraphs ORDER BY code")
    out = []
    for r in rows:
        refs = await _scan_subgraph_references(pool, r["code"])
        out.append({**dict(r), "referenced_count": len(refs), "referenced_by": refs,
                    "in_use": bool(refs)})
    return {"subgraphs": out, "total": len(out)}


subgraph_routes["list"] = subgraphs_list


@guard
async def subgraphs_create(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    body = await request.json()
    code = str(body.get("code") or "").strip()
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{2,63}", code):
        raise ValueError("子图编码非法：字母开头，3-64 位字母/数字/下划线/横线")
    pool = await db.pool()
    exists = await pool.fetchval("SELECT 1 FROM subgraphs WHERE code = $1", code)
    if exists:
        raise ValueError(f"子图编码已存在：{code}")
    empty_graph = {"entry_node": "", "exit_node": "", "nodes": [], "edges": []}
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO subgraphs (code, display_name, description, current_version, created_by) "
                "VALUES ($1, $2, $3, 'v1.0.0', $4)",
                code, str(body.get("display_name") or code), str(body.get("description") or ""), user["email"])
            await conn.execute(
                "INSERT INTO subgraph_versions (subgraph_code, version, graph, changelog, created_by) "
                "VALUES ($1, 'v1.0.0', $2::jsonb, '初始版本', $3)",
                code, _dump(empty_graph), user["email"])
    return {"code": code, "version": "v1.0.0"}


subgraph_routes["create"] = subgraphs_create


@guard
async def subgraphs_detail(request: Request) -> dict:
    await require(request, "orchestration:read")
    code = request.path_params["code"]
    pool = await db.pool()
    row = await pool.fetchrow("SELECT * FROM subgraphs WHERE code = $1", code)
    if row is None:
        raise KeyError(f"子图不存在：{code}")
    versions = await pool.fetch(
        "SELECT version, graph, changelog, created_by, created_at FROM subgraph_versions "
        "WHERE subgraph_code = $1 ORDER BY created_at DESC", code)
    refs = await _scan_subgraph_references(pool, code)
    return {**dict(row), "referenced_by": refs, "referenced_count": len(refs),
            "versions": [{**dict(v), "graph": _load_json(v["graph"])} for v in versions]}


subgraph_routes["detail"] = subgraphs_detail


@guard
async def subgraphs_save_version(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    body = await request.json()
    graph = body.get("graph")
    if not graph or not (graph.get("nodes") or []):
        raise ValueError("画布至少需要一个节点")
    changelog = str(body.get("changelog") or "更新编排")
    pool = await db.pool()
    exists = await pool.fetchval("SELECT 1 FROM subgraphs WHERE code = $1", code)
    if not exists:
        raise KeyError(f"子图不存在：{code}")
    await locks.require(pool, "subgraph", code, user["email"])
    async with pool.acquire() as conn:
        async with conn.transaction():
            version = await next_version(conn, "subgraph_versions", "subgraph_code", code,
                                         deploy_kind=None)
            await conn.execute(
                "INSERT INTO subgraph_versions (subgraph_code, version, graph, changelog, created_by) "
                "VALUES ($1, $2, $3::jsonb, $4, $5) "
                "ON CONFLICT (subgraph_code, version) DO UPDATE SET graph = $3::jsonb, changelog = $4",
                code, version, _dump(graph), changelog, user["email"])
            await conn.execute(
                "UPDATE subgraphs SET current_version = $2, updated_at = now() WHERE code = $1",
                code, version)
    return {"code": code, "version": version}


subgraph_routes["save_version"] = subgraphs_save_version


@guard
async def subgraphs_delete(request: Request) -> dict:
    await require(request, "orchestration:write")
    code = request.path_params["code"]
    pool = await db.pool()
    refs = await _scan_subgraph_references(pool, code)
    if refs:
        raise ValueError(f"子图 {code} 仍被引用：{'、'.join(refs[:5])}——请先下线或重新编排这些场景版本")
    await pool.execute("DELETE FROM subgraphs WHERE code = $1", code)
    return {"code": code, "deleted": True}


subgraph_routes["delete"] = subgraphs_delete


@guard
async def subgraphs_copy(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    body = await request.json()
    new_code = str(body.get("new_code") or "").strip()
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{2,63}", new_code):
        raise ValueError("新子图编码非法")
    pool = await db.pool()
    src = await pool.fetchrow("SELECT * FROM subgraphs WHERE code = $1", code)
    if src is None:
        raise KeyError(f"子图不存在：{code}")
    dup = await pool.fetchval("SELECT 1 FROM subgraphs WHERE code = $1", new_code)
    if dup:
        raise ValueError(f"子图编码已存在：{new_code}")
    latest = await pool.fetchrow(
        "SELECT graph FROM subgraph_versions WHERE subgraph_code = $1 "
        "ORDER BY created_at DESC LIMIT 1", code)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO subgraphs (code, display_name, description, current_version, created_by) "
                "VALUES ($1, $2, $3, 'v1.0.0', $4)",
                new_code, f"{src['display_name']}_copy" if src["display_name"] else new_code,
                f"复制自 {code}", user["email"])
            await conn.execute(
                "INSERT INTO subgraph_versions (subgraph_code, version, graph, changelog, created_by) "
                "VALUES ($1, 'v1.0.0', $2::jsonb, $3, $4)",
                new_code, _dump(latest["graph"]) if latest else _dump({"entry_node": "", "exit_node": "", "nodes": [], "edges": []}),
                f"复制自 {code}", user["email"])
    return {"code": new_code, "copied_from": code}


subgraph_routes["copy"] = subgraphs_copy


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------
scenario_routes = {}


@guard
async def scenarios_list(request: Request) -> dict:
    await require(request, "orchestration:read")
    pool = await db.pool()
    rows = await pool.fetch("SELECT * FROM scenarios ORDER BY code")
    out = []
    for r in rows:
        deploy_envs = await pool.fetch(
            "SELECT DISTINCT env FROM deployments WHERE asset_kind='scenario' "
            "AND asset_code = $1", r["code"])
        out.append({**dict(r), "deployed_envs": sorted(d["env"] for d in deploy_envs)})
    return {"scenarios": out, "total": len(out)}


scenario_routes["list"] = scenarios_list


@guard
async def scenarios_create(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    body = await request.json()
    code = str(body.get("code") or "").strip()
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{2,63}", code):
        raise ValueError("场景编码非法：字母开头，3-64 位字母/数字/下划线/横线")
    pool = await db.pool()
    exists = await pool.fetchval("SELECT 1 FROM scenarios WHERE code = $1", code)
    if exists:
        raise ValueError(f"场景编码已存在：{code}")
    empty_graph = {"entry_node": "", "exit_node": "", "nodes": [], "edges": []}
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO scenarios (code, display_name, description, current_version, created_by) "
                "VALUES ($1, $2, $3, 'v1.0.0', $4)",
                code, str(body.get("display_name") or code), str(body.get("description") or ""), user["email"])
            await conn.execute(
                "INSERT INTO scenario_versions (scenario_code, version, graph, enable_saga, changelog, created_by) "
                "VALUES ($1, 'v1.0.0', $2::jsonb, TRUE, '初始版本', $3)",
                code, _dump(empty_graph), user["email"])
    return {"code": code, "version": "v1.0.0"}


scenario_routes["create"] = scenarios_create


@guard
async def scenarios_detail(request: Request) -> dict:
    await require(request, "orchestration:read")
    code = request.path_params["code"]
    pool = await db.pool()
    row = await pool.fetchrow("SELECT * FROM scenarios WHERE code = $1", code)
    if row is None:
        raise KeyError(f"场景不存在：{code}")
    versions = await pool.fetch(
        "SELECT version, graph, enable_saga, changelog, created_by, created_at FROM scenario_versions "
        "WHERE scenario_code = $1 ORDER BY created_at DESC", code)
    deploy_envs = await pool.fetch(
        "SELECT DISTINCT version, env FROM deployments WHERE asset_kind='scenario' AND asset_code = $1",
        code)
    deployments = {}
    for d in deploy_envs:
        deployments.setdefault(d["version"], []).append(d["env"])
    return {**dict(row), "deployments": deployments,
            "versions": [{**dict(v), "graph": _load_json(v["graph"])} for v in versions]}


scenario_routes["detail"] = scenarios_detail


@guard
async def scenarios_save_version(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    body = await request.json()
    graph = body.get("graph")
    if not graph or not (graph.get("nodes") or []):
        raise ValueError("画布至少需要一个节点")
    enable_saga = bool(body.get("enable_saga", True))
    changelog = str(body.get("changelog") or "更新编排")
    pool = await db.pool()
    exists = await pool.fetchval("SELECT 1 FROM scenarios WHERE code = $1", code)
    if not exists:
        raise KeyError(f"场景不存在：{code}")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await locks.require(conn, "scenario", code, user["email"])
            version = await next_version(conn, "scenario_versions", "scenario_code", code,
                                         deploy_kind="scenario")
            await conn.execute(
                "INSERT INTO scenario_versions (scenario_code, version, graph, enable_saga, changelog, created_by) "
                "VALUES ($1, $2, $3::jsonb, $4, $5, $6) "
                "ON CONFLICT (scenario_code, version) DO UPDATE SET graph = $3::jsonb, "
                "enable_saga = $4, changelog = $5",
                code, version, _dump(graph), enable_saga, changelog, user["email"])
            await conn.execute(
                "UPDATE scenarios SET current_version = $2, updated_at = now() WHERE code = $1",
                code, version)
    return {"code": code, "version": version}


scenario_routes["save_version"] = scenarios_save_version


@guard
async def scenarios_delete(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    pool = await db.pool()
    deployed = await pool.fetchval(
        "SELECT 1 FROM deployments WHERE asset_kind='scenario' AND asset_code = $1 "
        "AND env = 'online' LIMIT 1", code)
    if deployed:
        raise ValueError("场景已下发到生产环境；请先完成生产下线流程再删除")
    await pool.execute("DELETE FROM scenarios WHERE code = $1", code)
    return {"code": code, "deleted": True}


scenario_routes["delete"] = scenarios_delete


def _dump(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)




operator_lock_routes = {}


@guard
async def operator_lock_acquire(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    name = request.path_params["name"]
    pool = await db.pool()
    async with pool.acquire() as conn:
        return await locks.acquire(conn, "operator", name, user["email"])


operator_lock_routes["acquire"] = operator_lock_acquire


@guard
async def operator_lock_release(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    name = request.path_params["name"]
    pool = await db.pool()
    async with pool.acquire() as conn:
        released = await locks.release(conn, "operator", name, user["email"])
    return {"released": released}


@guard
async def operator_lock_release(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    name = request.path_params["name"]
    pool = await db.pool()
    async with pool.acquire() as conn:
        released = await locks.release(conn, "operator", name, user["email"])
    return {"released": released}


operator_lock_routes["release"] = operator_lock_release


subgraph_lock_routes = {}
scenario_lock_routes = {}


@guard
async def subgraph_lock_acquire(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    pool = await db.pool()
    async with pool.acquire() as conn:
        return await locks.acquire(conn, "subgraph", code, user["email"])


subgraph_lock_routes["acquire"] = subgraph_lock_acquire


@guard
async def subgraph_lock_release(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    pool = await db.pool()
    async with pool.acquire() as conn:
        released = await locks.release(conn, "subgraph", code, user["email"])
    return {"released": released}


subgraph_lock_routes["release"] = subgraph_lock_release


@guard
async def scenario_lock_acquire(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    pool = await db.pool()
    async with pool.acquire() as conn:
        return await locks.acquire(conn, "scenario", code, user["email"])


scenario_lock_routes["acquire"] = scenario_lock_acquire


@guard
async def scenario_lock_release(request: Request) -> dict:
    user = await require(request, "orchestration:write")
    code = request.path_params["code"]
    pool = await db.pool()
    async with pool.acquire() as conn:
        released = await locks.release(conn, "scenario", code, user["email"])
    return {"released": released}


scenario_lock_routes["release"] = scenario_lock_release


@guard
async def operator_lock_status(request: Request) -> dict | None:
    await require(request, "orchestration:read")
    name = request.path_params["name"]
    pool = await db.pool()
    async with pool.acquire() as conn:
        return await locks.status_of(conn, "operator", name)


operator_lock_routes["status"] = operator_lock_status
