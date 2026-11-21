"""场景处理器：auth / governance / observability / bizops 的参考实现。

处理器签名 (db, user, payload, context) -> data。所有治理写路径过审计。
"""
import json
from datetime import date, timedelta
from typing import Any

from .database import HostDatabase
from .scenarios import PERMISSION_CATALOG
from .security import hash_password, verify_password


def _require(payload: dict, key: str) -> Any:
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"missing required field: {key}")
    return value


def _row_dict(row) -> dict:
    return dict(row)


# ---- auth ----


def auth_login(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    name = _require(payload, "username")
    password = _require(payload, "password")
    row = db.query_one("SELECT * FROM users WHERE name = ?", (name,))
    if row is None or not verify_password(password, row["password_hash"], row["password_salt"]):
        raise PermissionError("invalid credentials")
    token, expires_at = db.create_session(row["id"])
    return {"token": token, "expires_at": expires_at, "user": {"id": row["id"], "name": row["name"]}}


def auth_session(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    if user is None:
        raise PermissionError("no valid session")
    return {"user": {"id": user["id"], "name": user["name"]}}


# ---- scope ----


def platform_scope_my(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    if user is None:
        raise PermissionError("no valid session")
    user_id = user["id"]
    tenants = db.query(
        "SELECT t.id, t.name, m.role_id, r.name AS role_name, r.permissions FROM memberships m"
        " JOIN tenants t ON t.id = m.tenant_id LEFT JOIN roles r ON r.id = m.role_id"
        " WHERE m.user_id = ? ORDER BY t.id", (user_id,))
    projects = db.query(
        "SELECT p.id, p.tenant_id, p.name, pm.role_id, r.name AS role_name FROM project_members pm"
        " JOIN projects p ON p.id = pm.project_id LEFT JOIN roles r ON r.id = pm.role_id"
        " WHERE pm.user_id = ? ORDER BY p.id", (user_id,))
    envs = db.query(
        "SELECT e.project_id, e.key FROM envs e JOIN project_members pm ON pm.project_id = e.project_id"
        " WHERE pm.user_id = ? ORDER BY e.project_id, e.key", (user_id,))
    return {
        "user": {"id": user_id, "name": user["name"]},
        "tenants": [_row_dict(t) for t in tenants],
        "projects": [_row_dict(p) for p in projects],
        "envs": [_row_dict(e) for e in envs],
    }


# ---- 治理 ----


def platform_tenants_list(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    return {"tenants": [_row_dict(r) for r in db.query("SELECT id, name, created_at FROM tenants ORDER BY id")]}


def platform_tenants_create(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    name = _require(payload, "name")
    with db.transaction() as conn:
        cursor = conn.execute("INSERT INTO tenants (name, created_at) VALUES (?, datetime('now'))", (name,))
        tenant_id = cursor.lastrowid
        # 创建者自动入租（owner_role_id 可选）；治理面最自然的成员起点。
        conn.execute("INSERT INTO memberships (user_id, tenant_id, role_id) VALUES (?,?,?)",
                     (user["id"], tenant_id, payload.get("owner_role_id")))
    db.audit_append(user["name"], "tenant.create", f"tenant:{tenant_id}", name)
    return {"tenant": _row_dict(db.query_one("SELECT id, name, created_at FROM tenants WHERE id = ?", (tenant_id,)))}


def platform_projects_list(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    tenant_id = payload.get("tenant_id")
    if tenant_id is None:
        rows = db.query("SELECT id, tenant_id, name, created_at FROM projects ORDER BY id")
    else:
        rows = db.query("SELECT id, tenant_id, name, created_at FROM projects WHERE tenant_id = ? ORDER BY id",
                        (tenant_id,))
    return {"projects": [_row_dict(r) for r in rows]}


def platform_projects_create(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    tenant_id = _require(payload, "tenant_id")
    name = _require(payload, "name")
    with db.transaction() as conn:
        cursor = conn.execute("INSERT INTO projects (tenant_id, name, created_at) VALUES (?,?, datetime('now'))",
                              (tenant_id, name))
        project_id = cursor.lastrowid
        if payload.get("role_id") is not None:
            conn.execute("INSERT INTO project_members (user_id, project_id, role_id) VALUES (?,?,?)",
                         (user["id"], project_id, payload["role_id"]))
        for key in payload.get("envs") or ("dev", "test", "staging", "online"):
            conn.execute("INSERT INTO envs (project_id, key) VALUES (?,?)", (project_id, str(key)))
    db.audit_append(user["name"], "project.create", f"project:{project_id}", name)
    return {"project": _row_dict(db.query_one("SELECT id, tenant_id, name, created_at FROM projects WHERE id = ?",
                                              (project_id,)))}


def platform_projects_update(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    project_id = _require(payload, "project_id")
    name = _require(payload, "name")
    db.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
    db.audit_append(user["name"], "project.update", f"project:{project_id}", name)
    return {"project": _row_dict(db.query_one("SELECT id, tenant_id, name, created_at FROM projects WHERE id = ?",
                                              (project_id,)))}


def platform_users_list(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    return {"users": [_row_dict(r) for r in
                      db.query("SELECT id, name, created_at FROM users ORDER BY id")]}


def platform_users_create(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    name = _require(payload, "username")
    password = _require(payload, "password")
    digest, salt = hash_password(password)
    with db.transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO users (name, password_hash, password_salt, created_at)"
            " VALUES (?,?,?, datetime('now'))", (name, digest, salt))
        user_id = cursor.lastrowid
    db.audit_append(user["name"], "user.create", f"user:{user_id}", name)
    return {"user": _row_dict(db.query_one("SELECT id, name, created_at FROM users WHERE id = ?", (user_id,)))}


def platform_roles_list(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    rows = db.query("SELECT id, name, permissions FROM roles ORDER BY id")
    return {"roles": [{"id": r["id"], "name": r["name"], "permissions": json.loads(r["permissions"])}
                      for r in rows]}


def platform_roles_create(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    name = _require(payload, "name")
    permissions = _require(payload, "permissions")
    catalog = {entry["permission"] for entry in PERMISSION_CATALOG}
    unknown = set(permissions) - catalog
    if unknown:
        raise ValueError(f"unknown permissions: {sorted(unknown)}")
    with db.transaction() as conn:
        cursor = conn.execute("INSERT INTO roles (name, permissions) VALUES (?,?)",
                              (name, json.dumps(sorted(permissions), ensure_ascii=True, sort_keys=True)))
        role_id = cursor.lastrowid
    db.audit_append(user["name"], "role.create", f"role:{role_id}", name)
    return {"role": {"id": role_id, "name": name, "permissions": sorted(permissions)}}


def platform_permissions_list(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    return {"permissions": [dict(entry) for entry in PERMISSION_CATALOG]}


def platform_envs_list(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    project_id = _require(payload, "project_id")
    return {"envs": [_row_dict(r) for r in
                     db.query("SELECT project_id, key FROM envs WHERE project_id = ? ORDER BY key", (project_id,))]}


def platform_envs_create(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    project_id = _require(payload, "project_id")
    key = _require(payload, "key")
    db.execute("INSERT INTO envs (project_id, key) VALUES (?,?)", (project_id, key))
    db.audit_append(user["name"], "env.create", f"project:{project_id}/env:{key}")
    return {"env": {"project_id": project_id, "key": key}}


def platform_audit_list(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    limit = min(int(payload.get("limit", 100)), 1000)
    offset = max(int(payload.get("offset", 0)), 0)
    rows = db.query("SELECT seq, at, actor, action, target, detail FROM audit"
                    " ORDER BY seq DESC LIMIT ? OFFSET ?", (limit, offset))
    return {"audit": [_row_dict(r) for r in rows], "limit": limit, "offset": offset}


# ---- 运维 / 运营 ----


def ops_runs_list(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    limit = min(int(payload.get("limit", 100)), 1000)
    offset = max(int(payload.get("offset", 0)), 0)
    clauses, params = [], []
    for key in ("scenario", "status", "env_key"):
        if payload.get(key):
            clauses.append(f"{key} = ?")
            params.append(payload[key])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.query(f"SELECT seq, at, scenario, status, duration_ms, actor, tenant_id, project_id, env_key"
                    f" FROM runs {where} ORDER BY seq DESC LIMIT ? OFFSET ?",
                    (*params, limit, offset))
    total = db.query_one(f"SELECT COUNT(*) AS n FROM runs {where}", tuple(params))["n"]
    return {"runs": [_row_dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def ops_runs_detail(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    seq = _require(payload, "seq")
    row = db.query_one("SELECT * FROM runs WHERE seq = ?", (seq,))
    if row is None:
        raise LookupError(f"run {seq} not found")
    return {"run": _row_dict(row)}


def ops_metrics(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    row = db.query_one("SELECT COUNT(*) AS total,"
                       " SUM(CASE WHEN status = 'SUCCEEDED' THEN 1 ELSE 0 END) AS succeeded"
                       " FROM runs")
    durations = [r["duration_ms"] for r in db.query(
        "SELECT duration_ms FROM runs ORDER BY duration_ms")]
    p95 = durations[min(len(durations) - 1, int(round(0.95 * (len(durations) - 1))))] if durations else None
    total, succeeded = row["total"], row["succeeded"]
    return {"total": total, "succeeded": succeeded,
            "success_rate": round(succeeded / total, 6) if total else None,
            "p95_ms": p95, "method": "read-time aggregation over real run records (读时聚合，不预存时序)"}


def _client_key(envelope_payload: dict, user) -> str | None:
    if isinstance(envelope_payload, dict):
        for key in ("anonymous_id", "user_id", "identity"):
            if isinstance(envelope_payload.get(key), str) and envelope_payload[key]:
                return f"{key}:{envelope_payload[key]}"
    if user is not None:
        return f"session:{user['name']}"
    return None


def bizops_overview(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    counts = {
        "tenants": db.query_one("SELECT COUNT(*) AS n FROM tenants")["n"],
        "projects": db.query_one("SELECT COUNT(*) AS n FROM projects")["n"],
        "users": db.query_one("SELECT COUNT(*) AS n FROM users")["n"],
        "runs": db.query_one("SELECT COUNT(*) AS n FROM runs")["n"],
        "telemetry_events": db.query_one("SELECT COUNT(*) AS n FROM telemetry")["n"],
    }
    return {"entities": counts, "note": "实体计数 + 真实记录计数；样本量即全量，无抽样美化"}


def bizops_trend(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    days = min(int(payload.get("days", 14)), 90)
    rows = db.query(
        "SELECT substr(at, 1, 10) AS day, event, COUNT(*) AS n FROM telemetry"
        " WHERE event = 'ops.page.viewed' GROUP BY day, event ORDER BY day DESC LIMIT ?",
        (days,))
    runs = db.query(
        "SELECT substr(at, 1, 10) AS day, COUNT(*) AS n FROM runs GROUP BY day ORDER BY day DESC LIMIT ?",
        (days,))
    return {"telemetry_by_day": [_row_dict(r) for r in rows],
            "runs_by_day": [_row_dict(r) for r in runs]}


def bizops_funnel(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps or not all(isinstance(s, str) and s for s in steps):
        raise ValueError("steps must be a nonempty list of event names")
    keys: dict[str, None] = {}
    for event in steps:
        for row in db.query("SELECT payload FROM telemetry WHERE event = ? ORDER BY seq", (event,)):
            key = _client_key(json.loads(row["payload"] or "{}"), user)
            if key is not None:
                keys.setdefault(key, None)
    sample = len(keys)
    counts = []
    for event in steps:
        distinct = set()
        for row in db.query("SELECT payload FROM telemetry WHERE event = ?", (event,)):
            key = _client_key(json.loads(row["payload"] or "{}"), user)
            if key is not None:
                distinct.add(key)
        counts.append({"event": event, "clients": len(distinct)})
    return {"steps": counts, "sample_clients": sample,
            "note": "足迹去重口径（非严格时序归因），样本量如实披露——漏斗时序归因随 T15 落地"}


def bizops_retention(db: HostDatabase, user, payload: dict, context: dict) -> dict:
    rows = db.query("SELECT substr(at, 1, 10) AS day, payload FROM telemetry"
                    " WHERE event = 'ops.page.viewed' ORDER BY at")
    first_seen: dict[str, str] = {}
    seen_days: dict[str, set[str]] = {}
    for row in rows:
        key = _client_key(json.loads(row["payload"] or "{}"), user)
        if key is None:
            continue
        first_seen.setdefault(key, row["day"])
        seen_days.setdefault(key, set()).add(row["day"])
    cohort: dict[str, dict[str, int]] = {}
    for key, start in first_seen.items():
        cohort.setdefault(start, {"clients": 0, "d1": 0, "d7": 0})
        cohort[start]["clients"] += 1
        start_date = date.fromisoformat(start)
        for offset, field in ((1, "d1"), (7, "d7")):
            target = (start_date + timedelta(days=offset)).isoformat()
            if target in seen_days[key]:
                cohort[start][field] += 1
    return {"cohorts": cohort,
            "note": "D1/D7 按首访日的回访客户端计数；无身份足迹的客户端不参与（样本量随 cohorts 如实呈现）"}
