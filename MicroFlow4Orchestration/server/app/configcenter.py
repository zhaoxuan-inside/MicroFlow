"""配置中心：命名空间 → 配置项 → 版本历史 → 灰度发布（百分比分桶 + 白名单直通）。

灰度解析（resolve）是纯函数；数据库承载配置项登记、版本历史与生效指针，
与编排平台的发布审批体系相互独立。
"""
import hashlib
import json

from fastapi import Request

from . import db
from .web import require, guard

VERSION_STATUSES = ("DRAFT", "PUBLISHED", "ROLLED_BACK")


# ---------------------------------------------------------------------------
# 纯决策逻辑
# ---------------------------------------------------------------------------
def gray_selected(uid: str, gray: dict) -> bool:
    """灰度命中判定（纯）：白名单直通，否则 sha256(gray:uid) 分桶与百分比对齐。"""
    if not isinstance(gray, dict) or not gray:
        return False
    whitelist = gray.get("whitelist") or []
    if uid in whitelist:
        return True
    percent = max(int(gray.get("percent") or 0), 0)
    if percent <= 0:
        return False
    digest = hashlib.sha256(f"gray:{uid}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100 < percent


def validate_gray(gray) -> dict:
    if gray is None:
        return {}
    if not isinstance(gray, dict):
        raise ValueError("gray 必须是对象")
    unknown = set(gray) - {"percent", "whitelist"}
    if unknown:
        raise ValueError(f"gray 含未知字段：{sorted(unknown)}")
    percent = max(int(gray.get("percent") or 0), 0)
    if percent > 100:
        raise ValueError("gray.percent 不能超过 100")
    whitelist = gray.get("whitelist") or []
    if not isinstance(whitelist, list) or any(type(item) is not str for item in whitelist):
        raise ValueError("gray.whitelist 必须是字符串数组")
    return {"percent": percent, "whitelist": whitelist}


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
routes = {}


@guard
async def namespaces_list(request: Request) -> dict:
    await require(request, "configcenter:read")
    pool = await db.pool()
    rows = await pool.fetch(
        "SELECT code, name, description, created_by, created_at FROM config_namespaces "
        "ORDER BY code LIMIT 200")
    items = await pool.fetch(
        "SELECT namespace_code, count(*) AS items FROM config_items GROUP BY namespace_code")
    counts = {r["namespace_code"]: r["items"] for r in items}
    return {"namespaces": [{**dict(r), "items": counts.get(r["code"], 0)} for r in rows]}


routes["namespaces_list"] = namespaces_list


@guard
async def namespaces_create(request: Request) -> dict:
    user = await require(request, "configcenter:write")
    body = await request.json()
    code = str(body.get("code") or "").strip()
    if not code or any(c in code for c in " /\\@"):
        raise ValueError("命名空间 code 必须是非空且不含空白与路径分隔符的标识")
    pool = await db.pool()
    exists = await pool.fetchval("SELECT 1 FROM config_namespaces WHERE code = $1", code)
    if exists:
        raise ValueError(f"命名空间已存在：{code}")
    await pool.execute(
        "INSERT INTO config_namespaces (code, name, description, created_by) VALUES ($1, $2, $3, $4)",
        code, str(body.get("name") or code), str(body.get("description") or ""), user["email"])
    return {"code": code}


routes["namespaces_create"] = namespaces_create


@guard
async def items_list(request: Request) -> dict:
    await require(request, "configcenter:read")
    namespace = request.path_params["namespace"]
    pool = await db.pool()
    rows = await pool.fetch(
        "SELECT key, value_type, description, gray, current_version, created_by, updated_at "
        "FROM config_items WHERE namespace_code = $1 ORDER BY key LIMIT 500", namespace)
    return {"items": [{**dict(r), "gray": json.loads(r["gray"])} for r in rows]}


routes["items_list"] = items_list


@guard
async def items_create(request: Request) -> dict:
    user = await require(request, "configcenter:write")
    namespace = request.path_params["namespace"]
    body = await request.json()
    key = str(body.get("key") or "").strip()
    if not key or any(c in key for c in " /\\@"):
        raise ValueError("配置项 key 必须是非空且不含空白与路径分隔符的标识")
    pool = await db.pool()
    exists = await pool.fetchval(
        "SELECT 1 FROM config_namespaces WHERE code = $1", namespace)
    if exists is None:
        raise KeyError(f"命名空间不存在：{namespace}")
    item = await pool.fetchval(
        "SELECT 1 FROM config_items WHERE namespace_code = $1 AND key = $2", namespace, key)
    if item:
        raise ValueError(f"配置项已存在：{key}")
    await pool.execute(
        "INSERT INTO config_items (namespace_code, key, value_type, description, gray, created_by) "
        "VALUES ($1, $2, $3, $4, '{}'::jsonb, $5)",
        namespace, key, str(body.get("value_type") or "json"),
        str(body.get("description") or ""), user["email"])
    return {"namespace": namespace, "key": key}


routes["items_create"] = items_create


@guard
async def items_version_save(request: Request) -> dict:
    """保存新草稿版本；值必须 JSON 可序列化且经 validate_value 校验。"""
    user = await require(request, "configcenter:write")
    namespace = request.path_params["namespace"]
    key = request.path_params["key"]
    body = await request.json()
    pool = await db.pool()
    item = await pool.fetchrow(
        "SELECT 1 FROM config_items WHERE namespace_code = $1 AND key = $2", namespace, key)
    if item is None:
        raise KeyError(f"配置项不存在：{namespace}/{key}")
    value = body.get("value")
    try:
        from microflow.values import validate_value
    except ImportError:
        def validate_value(item):  # 宿主未装 microflow：退化为 JSON 序列化检查
            json.dumps(item, ensure_ascii=True)
            return
    try:
        validate_value(value)
    except Exception as exc:  # noqa: BLE001 - 值契约非法即拒绝，不做静默修正
        raise ValueError(f"配置值非法：{exc}") from exc
    latest = await pool.fetchval(
        "SELECT max(version::integer) FROM config_versions WHERE namespace_code = $1 AND key = $2",
        namespace, key)
    version = str(int(latest or 0) + 1)
    await pool.execute(
        "INSERT INTO config_versions (namespace_code, key, version, value, status, note, created_by) "
        "VALUES ($1, $2, $3, $4::jsonb, 'DRAFT', $5, $6)",
        namespace, key, version, json.dumps(value, ensure_ascii=False),
        str(body.get("note") or ""), user["email"])
    return {"namespace": namespace, "key": key, "version": version, "status": "DRAFT"}


routes["items_version_save"] = items_version_save


@guard
async def items_history(request: Request) -> dict:
    await require(request, "configcenter:read")
    namespace = request.path_params["namespace"]
    key = request.path_params["key"]
    pool = await db.pool()
    rows = await pool.fetch(
        "SELECT version, value, status, note, published_by, published_at, created_by, created_at "
        "FROM config_versions WHERE namespace_code = $1 AND key = $2 ORDER BY version::integer DESC "
        "LIMIT 200", namespace, key)
    return {"history": [{**dict(r), "value": json.loads(r["value"])} for r in rows]}


routes["items_history"] = items_history


@guard
async def items_publish(request: Request) -> dict:
    """发布：把某草稿版本标为 PUBLISHED 并拨 current_version 指针 + 更新灰度配置。"""
    user = await require(request, "configcenter:write")
    namespace = request.path_params["namespace"]
    key = request.path_params["key"]
    body = await request.json()
    version = str(body.get("version") or "")
    pool = await db.pool()
    row = await pool.fetchrow(
        "SELECT status FROM config_versions WHERE namespace_code = $1 AND key = $2 AND version = $3",
        namespace, key, version)
    if row is None:
        raise KeyError(f"配置版本不存在：{namespace}/{key}@{version}")
    gray = validate_gray(body.get("gray") if body.get("gray") is not None else
                         json.loads((await pool.fetchval(
                             "SELECT gray FROM config_items WHERE namespace_code = $1 AND key = $2",
                             namespace, key)) or "{}"))
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE config_versions SET status = 'PUBLISHED' WHERE namespace_code = $1 "
                               "AND key = $2 AND version = $3", namespace, key, version)
            await conn.execute(
                "UPDATE config_items SET current_version = $3, gray = $4::jsonb, updated_at = now() "
                "WHERE namespace_code = $1 AND key = $2",
                namespace, key, version, json.dumps(gray, ensure_ascii=False))
    return {"namespace": namespace, "key": key, "version": version, "gray": gray}


routes["items_publish"] = items_publish


@guard
async def items_rollback(request: Request) -> dict:
    """回滚：目标历史版本重新发布（指针拨回；历史不篡改，拨动即追加语义）。"""
    user = await require(request, "configcenter:write")
    namespace = request.path_params["namespace"]
    key = request.path_params["key"]
    body = await request.json()
    version = str(body.get("version") or "")
    pool = await db.pool()
    row = await pool.fetchrow(
        "SELECT status FROM config_versions WHERE namespace_code = $1 AND key = $2 AND version = $3",
        namespace, key, version)
    if row is None:
        raise KeyError(f"配置版本不存在：{namespace}/{key}@{version}")
    current = await pool.fetchval(
        "SELECT current_version FROM config_items WHERE namespace_code = $1 AND key = $2",
        namespace, key)
    if current == version:
        raise ValueError(f"当前生效版本已是 {version}，无需回滚")
    gray_raw = await pool.fetchval(
        "SELECT gray FROM config_items WHERE namespace_code = $1 AND key = $2", namespace, key)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE config_versions SET status = 'PUBLISHED', published_by = $4, "
                               "published_at = now() WHERE namespace_code = $1 AND key = $2 AND version = $3",
                               namespace, key, version, user["email"])
            await conn.execute(
                "UPDATE config_items SET current_version = $3, updated_at = now() "
                "WHERE namespace_code = $1 AND key = $2", namespace, key, version)
    return {"namespace": namespace, "key": key, "version": version,
            "rolled_back_from": current, "gray": json.loads(gray_raw or "{}")}


routes["items_rollback"] = items_rollback


@guard
async def items_resolve(request: Request) -> dict:
    """灰度解析：uid 命中灰度返回候选版本，否则返回稳定版本（current_version）。"""
    await require(request, "configcenter:read")
    namespace = request.path_params["namespace"]
    key = request.path_params["key"]
    q = dict(request.query_params)
    uid = str(q.get("uid") or "").strip()
    if not uid:
        raise ValueError("uid 不能为空")
    pool = await db.pool()
    row = await pool.fetchrow(
        "SELECT current_version, gray FROM config_items WHERE namespace_code = $1 AND key = $2",
        namespace, key)
    if row is None:
        raise KeyError(f"配置项不存在：{namespace}/{key}")
    gray = json.loads(row["gray"] or "{}")
    if gray_selected(uid, gray):
        gray_version = max((int(item["version"]) for item in
                            (await pool.fetch(
                                "SELECT version FROM config_versions WHERE namespace_code = $1 "
                                "AND key = $2 AND status = 'PUBLISHED'", namespace, key))
                            if str(item["version"]).isdigit()), default=0)
        return {"uid": uid, "version": str(gray_version) or row["current_version"],
                "channel": "gray", "gray": gray}
    return {"uid": uid, "version": row["current_version"], "channel": "stable", "gray": gray}


routes["items_resolve"] = items_resolve
