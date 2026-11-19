"""告警最小闭环（控制面承载，对应 HOST_CONTRACT 路线的 T14 切片）。

规则求值是纯函数（evaluate_rules）：输入规则与已按窗口筛过的运行记录，
输出应开/刷新的告警事件；去重（同 rule+scope 未 ack 不重复开）、ack、
可选 webhook 通知（投递尝试有界记录）由数据库与路由层承载。
求值挂点：容器 debug I/O 上报与场景执行响应之后同步执行——最小闭环
不引入后台定时器。
"""
import asyncio
import json
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Request

from . import db
from .web import require, guard

RULE_KINDS = ("consecutive_failures", "error_rate")


# ---------------------------------------------------------------------------
# 纯求值逻辑（无 I/O）
# ---------------------------------------------------------------------------
def _within_window(record: dict, now: datetime, window_minutes: int) -> bool:
    raw = record.get("reported_at")
    if not raw:
        return True
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment >= now - timedelta(minutes=window_minutes)


def evaluate_rules(rules: list[dict], records: list[dict], *, now: datetime | None = None) -> list[dict]:
    """输入规则与运行记录（含 reported_at/status/scenario_code），输出待开/刷新告警。

    返回元素：{rule, scope_key, message, severity, detail}。调用方负责按
    (rule_id, scope_key) 去重与落库；records 顺序不限，函数内部按时间排序。
    """
    moment = now or datetime.now(timezone.utc)
    ordered = sorted(records, key=lambda r: str(r.get("reported_at") or ""))
    fired = []
    for rule in rules or []:
        if not rule.get("enabled", True) or rule.get("kind") not in RULE_KINDS:
            continue
        target = str(rule.get("target") or "*")
        scoped = [r for r in ordered if target in ("*", r.get("scenario_code"))]
        scope_key = f"scenario:{target}"
        threshold = float(rule.get("threshold") or 0)
        window = max(int(rule.get("window_minutes") or 60), 1)
        windowed = [r for r in scoped if _within_window(r, moment, window)]
        breached, message, detail = False, "", {}
        if rule["kind"] == "consecutive_failures":
            trail = 0
            for record in reversed(windowed):
                if (record.get("status") or "") == "SUCCESS":
                    break
                trail += 1
            breached = trail >= threshold and threshold > 0
            message = f"连续 {trail} 次非 SUCCESS（阈值 {int(threshold)}）"
            detail = {"trail": trail, "threshold": int(threshold)}
        else:  # error_rate
            total = len(windowed)
            failed = sum(1 for record in windowed if (record.get("status") or "") != "SUCCESS")
            rate = (failed / total * 100) if total else 0.0
            breached = total > 0 and rate >= threshold and threshold > 0
            message = f"窗口 {window} 分钟错误率 {rate:.1f}%（阈值 {threshold:.1f}%，{failed}/{total}）"
            detail = {"rate": round(rate, 2), "threshold": threshold, "failed": failed, "total": total}
        if breached:
            fired.append({"rule": dict(rule), "scope_key": scope_key, "message": message,
                          "severity": "critical" if rule["kind"] == "consecutive_failures" else "warning",
                          "detail": detail})
    return fired


def _webhook_payload(event: dict) -> dict:
    return {"type": "microflow.alert", "rule": event["rule"].get("name"),
            "scope_key": event["scope_key"], "message": event["message"],
            "severity": event["severity"], "detail": event["detail"]}


async def _post_webhook(url: str, payload: dict) -> dict:
    def _do():
        request = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    loop = asyncio.get_running_loop()
    try:
        status = await asyncio.wait_for(loop.run_in_executor(None, _do), timeout=8)
        return {"url": url, "ok": True, "status": status, "at": db.now()}
    except Exception as exc:  # noqa: BLE001 - 通知失败如实记录，不吞事件
        return {"url": url, "ok": False, "error": str(exc)[:200], "at": db.now()}


async def process(pool, records: list[dict]) -> int:
    """求值 → 去重落库（OPEN 刷新 last_seen/occurrences）→ 有界 webhook 尝试。

    求值基于 DB 窗口历史与本批上报的合并视图：连续失败/错误率的语义对象是
    "该场景在窗口内的全部运行记录"，而不是调用方恰好传入的那一批。
    """
    rules = [dict(r) for r in await pool.fetch("SELECT * FROM alert_rules WHERE enabled")]
    if not rules:
        return 0
    max_window = max(int(rule.get("window_minutes") or 60) for rule in rules)
    since = datetime.now(timezone.utc) - timedelta(minutes=max_window)
    rows = await pool.fetch(
        "SELECT scenario_code, env, node_id, status, reported_at FROM debug_io "
        "WHERE reported_at >= $1 ORDER BY reported_at ASC LIMIT 2000", since)
    history = []
    seen = set()
    for row in rows:
        item = dict(row)
        item["reported_at"] = item["reported_at"].isoformat()
        history.append(item)
        seen.add((item["scenario_code"], item["node_id"], item["status"], item["reported_at"]))
    merged = history + [record for record in records
                        if (record.get("scenario_code"), record.get("node_id"),
                            record.get("status"), str(record.get("reported_at"))) not in seen]
    fired = evaluate_rules(rules, merged)
    delivered = 0
    for event in fired:
        rule_id = event["rule"]["id"]
        existing = await pool.fetchrow(
            "SELECT id, occurrences, detail FROM alert_events WHERE rule_id = $1 AND scope_key = $2 "
            "AND status = 'OPEN'", rule_id, event["scope_key"])
        prior_delivery = []
        if existing is None:
            await pool.execute(
                "INSERT INTO alert_events (rule_id, scope_key, message, severity, detail) "
                "VALUES ($1, $2, $3, $4, $5::jsonb)",
                rule_id, event["scope_key"], event["message"], event["severity"],
                json.dumps(event["detail"], ensure_ascii=False))
            delivered += 1
        else:
            await pool.execute(
                "UPDATE alert_events SET occurrences = $2, last_seen_at = now(), message = $3 "
                "WHERE id = $1",
                existing["id"], existing["occurrences"] + 1, event["message"])
            delivered += 1
            try:
                prior = json.loads(existing["detail"]) if isinstance(existing["detail"], str) \
                    else (existing["detail"] or {})
                prior_delivery = prior.get("delivery") if isinstance(prior, dict) else []
            except ValueError:
                prior_delivery = []
            prior_delivery = prior_delivery if isinstance(prior_delivery, list) else []
        webhook_url = str(event["rule"].get("webhook_url") or "")
        if webhook_url:
            # 0.11.1 非阻塞：通知投递（最长 8s）与落库放后台任务，上报/执行响应
            # 不被通知拖慢；任务异常兜底记录，绝不外泄。
            async def _deliver(rule_id=rule_id, scope_key=event["scope_key"],
                               url=webhook_url, payload=_webhook_payload(event),
                               attempts=prior_delivery[-4:]):
                try:
                    attempts.append(await _post_webhook(url, payload))
                    detail = {**event["detail"], "delivery": attempts}
                    await pool.execute(
                        "UPDATE alert_events SET detail = $2::jsonb WHERE rule_id = $1 "
                        "AND scope_key = $3 AND status = 'OPEN'",
                        rule_id, json.dumps(detail, ensure_ascii=False), scope_key)
                except Exception as exc:  # noqa: BLE001 - 通知失败不外泄
                    print(f"[alerting] webhook 投递异常（已隔离）：{type(exc).__name__}: {exc}")

            asyncio.create_task(_deliver())
    return delivered


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
routes = {}


@guard
async def alerts_list(request: Request) -> dict:
    await require(request, "ops:alerts")
    pool = await db.pool()
    q = dict(request.query_params)
    rows = await pool.fetch(
        "SELECT e.id, e.rule_id, r.name AS rule_name, r.kind AS rule_kind, e.scope_key, "
        "e.message, e.severity, e.status, e.occurrences, e.detail, e.first_seen_at, "
        "e.last_seen_at, e.acked_by, e.acked_at "
        "FROM alert_events e JOIN alert_rules r ON r.id = e.rule_id "
        "WHERE ($1::text IS NULL OR e.status = $1) ORDER BY e.last_seen_at DESC LIMIT $2",
        q.get("status") or None, min(int(q.get("limit") or 100), 500))
    return {"alerts": [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]}


routes["list"] = alerts_list


@guard
async def alerts_ack(request: Request) -> dict:
    user = await require(request, "ops:alerts")
    alert_id = request.path_params["alert_id"]
    pool = await db.pool()
    row = await pool.fetchrow("SELECT status FROM alert_events WHERE id = $1", alert_id)
    if row is None:
        raise KeyError("告警事件不存在")
    if row["status"] == "ACKED":
        raise ValueError("告警已确认")
    await pool.execute("UPDATE alert_events SET status = 'ACKED', acked_by = $2, acked_at = now() "
                       "WHERE id = $1", alert_id, user["email"])
    return {"id": alert_id, "status": "ACKED"}


routes["ack"] = alerts_ack


@guard
async def rules_list(request: Request) -> dict:
    await require(request, "ops:alerts")
    pool = await db.pool()
    rows = await pool.fetch(
        "SELECT id, name, kind, target, threshold, window_minutes, enabled, webhook_url, "
        "created_by, created_at FROM alert_rules ORDER BY created_at DESC")
    return {"rules": [dict(r) for r in rows]}


routes["rules_list"] = rules_list


@guard
async def rules_save(request: Request) -> dict:
    user = await require(request, "ops:alerts")
    body = await request.json()
    name = str(body.get("name") or "").strip()
    kind = str(body.get("kind") or "")
    if not name:
        raise ValueError("规则名不能为空")
    if kind not in RULE_KINDS:
        raise ValueError(f"kind 必须是 {'/'.join(RULE_KINDS)}")
    target = str(body.get("target") or "*").strip() or "*"
    threshold = float(body.get("threshold") or 0)
    if threshold <= 0:
        raise ValueError("threshold 必须为正数")
    window = max(int(body.get("window_minutes") or 60), 1)
    webhook_url = str(body.get("webhook_url") or "").strip()
    pool = await db.pool()
    rule_id = str(body.get("id") or "").strip()
    if rule_id:
        row = await pool.fetchrow("SELECT id FROM alert_rules WHERE id = $1", rule_id)
        if row is None:
            raise KeyError("规则不存在")
        await pool.execute(
            "UPDATE alert_rules SET name = $2, kind = $3, target = $4, threshold = $5, "
            "window_minutes = $6, enabled = $7, webhook_url = $8 WHERE id = $1",
            uuid.UUID(rule_id), name, kind, target, threshold, window,
            bool(body.get("enabled", True)), webhook_url)
    else:
        rule_id = str(await pool.fetchval(
            "INSERT INTO alert_rules (name, kind, target, threshold, window_minutes, enabled, "
            "webhook_url, created_by) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
            name, kind, target, threshold, window, bool(body.get("enabled", True)),
            webhook_url, user["email"]))
    return {"id": str(rule_id), "saved": True}


routes["rules_save"] = rules_save


@guard
async def rules_delete(request: Request) -> dict:
    await require(request, "ops:alerts")
    rule_id = request.path_params["rule_id"]
    pool = await db.pool()
    deleted = await pool.fetchval("DELETE FROM alert_rules WHERE id = $1 RETURNING 1",
                                  uuid.UUID(rule_id))
    if deleted is None:
        raise KeyError("规则不存在")
    return {"id": rule_id, "deleted": True}


routes["rules_delete"] = rules_delete
