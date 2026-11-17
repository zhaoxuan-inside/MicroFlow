"""A/B 实验域：确定性分桶决策（纯逻辑）+ 生命周期路由。

分桶与选样的语义是纯函数（bucket/pick_variant/decide），数据库只承载
实验登记与分派记录——测试无需 PostgreSQL 即可覆盖核心语义。
"""
import hashlib
import json

from fastapi import Request

from . import db
from .web import require, guard

STATUSES = ("DRAFT", "RUNNING", "STOPPED", "ARCHIVED")


# ---------------------------------------------------------------------------
# 纯决策逻辑（无 I/O；与 UI/存储解耦，供单元测试直接覆盖）
# ---------------------------------------------------------------------------
def bucket(experiment_key: str, uid: str) -> int:
    """确定性分桶：sha256(key:uid) 前 8 位十六进制 mod 100，稳定且可复算。"""
    digest = hashlib.sha256(f"{experiment_key}:{uid}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def pick_variant(value: int, variants: list[dict]) -> str:
    """按权重选样：value % total 落入累计权重区间；权重和 <= 0 时取首个。"""
    usable = [(str(v.get("key") or ""), max(int(v.get("weight") or 0), 0)) for v in variants]
    usable = [(key, weight) for key, weight in usable if key]
    if not usable:
        return ""
    total = sum(weight for _, weight in usable)
    if total <= 0:
        return usable[0][0]
    point = value % total
    for key, weight in sorted(usable):
        if point < weight:
            return key
        point -= weight
    return usable[-1][0]


def decide(experiment: dict, uid: str) -> dict:
    """分流决策（纯）：停止/停用只停新曝光；历史分派记录保持冻结。"""
    status = experiment.get("status")
    traffic = max(int(experiment.get("traffic_percent") or 0), 0)
    if status != "RUNNING":
        return {"in_experiment": False, "variant": "", "reason": f"status:{status}"}
    if traffic <= 0:
        return {"in_experiment": False, "variant": "", "reason": "traffic:zero"}
    value = bucket(str(experiment.get("key")), str(uid))
    if value >= traffic:
        return {"in_experiment": False, "variant": "", "reason": f"traffic:not_selected({value}>={traffic})"}
    variant = pick_variant(value, experiment.get("variants") or [])
    if not variant:
        return {"in_experiment": False, "variant": "", "reason": "variants:empty"}
    return {"in_experiment": True, "variant": variant, "reason": f"bucket:{value}<{traffic}"}


def _norm_variants(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("variants 必须是 [{key, weight}] 数组")
    seen = set()
    result = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("key") or "").strip():
            raise ValueError("variants 元素必须有非空 key")
        key = str(item["key"]).strip()
        if key in seen:
            raise ValueError(f"variants 重复：{key}")
        seen.add(key)
        weight = int(item.get("weight") or 0)
        result.append({"key": key, "weight": max(weight, 0)})
    if not result:
        raise ValueError("variants 不能为空")
    return result


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
routes = {}


@guard
async def experiments_list(request: Request) -> dict:
    await require(request, "experiment:read")
    pool = await db.pool()
    q = dict(request.query_params)
    rows = await pool.fetch(
        "SELECT key, display_name, description, status, traffic_percent, variants, env_key, "
        "created_by, created_at, updated_at FROM experiments "
        "WHERE ($1::text IS NULL OR status = $1) ORDER BY created_at DESC LIMIT 200",
        q.get("status") or None)
    return {"experiments": [{**dict(r), "variants": json.loads(r["variants"])} for r in rows]}


routes["list"] = experiments_list


@guard
async def experiments_detail(request: Request) -> dict:
    await require(request, "experiment:read")
    key = request.path_params["key"]
    pool = await db.pool()
    row = await pool.fetchrow(
        "SELECT key, display_name, description, status, traffic_percent, variants, env_key, "
        "created_by, created_at, updated_at FROM experiments WHERE key = $1", key)
    if row is None:
        raise KeyError(f"实验不存在：{key}")
    distribution = await pool.fetch(
        "SELECT variant, count(*) AS assigned FROM experiment_assignments "
        "WHERE experiment_key = $1 GROUP BY variant ORDER BY variant", key)
    return {**dict(row), "variants": json.loads(row["variants"]),
            "readout": {"variants": [dict(r) for r in distribution]}}


routes["detail"] = experiments_detail


@guard
async def experiments_create(request: Request) -> dict:
    user = await require(request, "experiment:manage")
    body = await request.json()
    key = str(body.get("key") or "").strip()
    if not key or any(c in key for c in " /\\@"):
        raise ValueError("key 必须是非空且不含空白与路径分隔符的标识")
    variants = _norm_variants(body.get("variants") or [])
    pool = await db.pool()
    exists = await pool.fetchval("SELECT 1 FROM experiments WHERE key = $1", key)
    if exists:
        raise ValueError(f"实验 key 已存在：{key}")
    await pool.execute(
        "INSERT INTO experiments (key, display_name, description, status, traffic_percent, "
        "variants, env_key, created_by) VALUES ($1, $2, $3, 'DRAFT', $4, $5::jsonb, $6, $7)",
        key, str(body.get("display_name") or key), str(body.get("description") or ""),
        max(int(body.get("traffic_percent") or 0), 0), json.dumps(variants, ensure_ascii=False),
        str(body.get("env_key") or "dev"), user["email"])
    return {"key": key, "status": "DRAFT"}


routes["create"] = experiments_create


@guard
async def experiments_update(request: Request) -> dict:
    user = await require(request, "experiment:manage")
    key = request.path_params["key"]
    body = await request.json()
    pool = await db.pool()
    row = await pool.fetchrow("SELECT status FROM experiments WHERE key = $1", key)
    if row is None:
        raise KeyError(f"实验不存在：{key}")
    if row["status"] in ("ARCHIVED",):
        raise ValueError("已归档实验不可修改")
    updates, params = [], []
    for field, column, cast in (("display_name", "display_name", str), ("description", "description", str),
                                ("env_key", "env_key", str)):
        if body.get(field) is not None:
            updates.append(f"{column} = ${len(params) + 1}")
            params.append(cast(body[field]))
    if body.get("variants") is not None:
        if row["status"] == "RUNNING":
            raise ValueError("运行中实验不可修改变体（只可调权重外的配置则先停止）")
        updates.append(f"variants = ${len(params) + 1}::jsonb")
        params.append(json.dumps(_norm_variants(body["variants"]), ensure_ascii=False))
    if body.get("traffic_percent") is not None:
        percent = max(int(body["traffic_percent"]), 0)
        if percent > 100:
            raise ValueError("traffic_percent 不能超过 100")
        updates.append(f"traffic_percent = ${len(params) + 1}")
        params.append(percent)
    if not updates:
        raise ValueError("没有可更新字段")
    params.append(key)
    await pool.execute(
        f"UPDATE experiments SET {', '.join(updates)}, updated_at = now() WHERE key = ${len(params)}",
        *params)
    return {"key": key, "updated": True}


routes["update"] = experiments_update


@guard
async def experiments_status(request: Request) -> dict:
    user = await require(request, "experiment:manage")
    key = request.path_params["key"]
    body = await request.json()
    status = str(body.get("status") or "")
    if status not in STATUSES:
        raise ValueError(f"status 必须是 {'/'.join(STATUSES)}")
    pool = await db.pool()
    row = await pool.fetchrow("SELECT status FROM experiments WHERE key = $1", key)
    if row is None:
        raise KeyError(f"实验不存在：{key}")
    if row["status"] == "ARCHIVED":
        raise ValueError("已归档实验不可再变更状态")
    if row["status"] == "RUNNING" and status == "DRAFT":
        raise ValueError("RUNNING 不可回退为 DRAFT（用 STOPPED 停止）")
    await pool.execute(
        "UPDATE experiments SET status = $2, updated_at = now() WHERE key = $1", key, status)
    return {"key": key, "status": status}


routes["status"] = experiments_status


@guard
async def experiments_delete(request: Request) -> dict:
    user = await require(request, "experiment:manage")
    key = request.path_params["key"]
    pool = await db.pool()
    row = await pool.fetchval("DELETE FROM experiments WHERE key = $1 AND status <> 'RUNNING' RETURNING 1", key)
    if row is None:
        raise ValueError("实验不存在或仍在运行（先停止再删除）")
    return {"key": key, "deleted": True}


routes["delete"] = experiments_delete


@guard
async def experiments_assign(request: Request) -> dict:
    user = await require(request, "experiment:read")
    key = request.path_params["key"]
    body = await request.json()
    uid = str(body.get("uid") or "").strip()
    if not uid:
        raise ValueError("uid 不能为空")
    pool = await db.pool()
    row = await pool.fetchrow(
        "SELECT key, status, traffic_percent, variants FROM experiments WHERE key = $1", key)
    if row is None:
        raise KeyError(f"实验不存在：{key}")
    decision = decide({**dict(row), "variants": json.loads(row["variants"])}, uid)
    await pool.execute(
        "INSERT INTO experiment_assignments (experiment_key, uid, variant, reason) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (experiment_key, uid) DO NOTHING",
        key, uid, decision["variant"], decision["reason"])
    return {**decision, "key": key, "uid": uid}


routes["assign"] = experiments_assign


@guard
async def experiments_readout(request: Request) -> dict:
    """读出：真实分派分布（去重人数），无结果的指标如实留空。"""
    await require(request, "experiment:read")
    key = request.path_params["key"]
    pool = await db.pool()
    row = await pool.fetchrow("SELECT key, status FROM experiments WHERE key = $1", key)
    if row is None:
        raise KeyError(f"实验不存在：{key}")
    distribution = await pool.fetch(
        "SELECT variant, count(*) AS assigned FROM experiment_assignments "
        "WHERE experiment_key = $1 GROUP BY variant ORDER BY variant", key)
    total = sum(r["assigned"] for r in distribution)
    variants = [{"variant": r["variant"], "assigned": r["assigned"],
                 "share": round(r["assigned"] / total, 4) if total else 0.0}
                for r in distribution]
    return {"key": key, "status": row["status"], "total": total, "variants": variants,
            "note": "分派为真实记录；结果指标（转化等）由业务方 outcome 上报后接入"}


routes["readout"] = experiments_readout
