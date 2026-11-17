"""控制面目录排他锁：持锁者才可保存版本/发布；他人（即使有写权限）禁改。"""
from datetime import datetime, timedelta, timezone

TTL_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def acquire(conn, asset_kind: str, asset_code: str, holder: str) -> dict:
    """获取/续期排他锁：同人幂等续期；他人持锁报 LockConflict（PermissionError 403）。"""
    row = await conn.fetchrow(
        "SELECT holder, expires_at FROM locks WHERE asset_kind = $1 AND asset_code = $2",
        asset_kind, asset_code)
    if row is not None and row["holder"] != holder and row["expires_at"] > _now():
        remaining = int((row["expires_at"] - _now()).total_seconds())
        raise PermissionError(
            f"LOCKED:{asset_kind}:{asset_code}:当前由 {row['holder']} 持锁（剩余 {remaining}s）")
    expires = _now() + timedelta(minutes=TTL_MINUTES)
    await conn.execute(
        "INSERT INTO locks (asset_kind, asset_code, holder, expires_at) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (asset_kind, asset_code) DO UPDATE SET holder = $3, expires_at = $4",
        asset_kind, asset_code, holder, expires)
    return {"asset_kind": asset_kind, "asset_code": asset_code, "holder": holder,
            "ttl_minutes": TTL_MINUTES}


async def release(conn, asset_kind: str, asset_code: str, holder: str) -> bool:
    row = await conn.fetchrow(
        "SELECT holder FROM locks WHERE asset_kind = $1 AND asset_code = $2",
        asset_kind, asset_code)
    if row is None or row["holder"] != holder:
        return False
    await conn.execute(
        "DELETE FROM locks WHERE asset_kind = $1 AND asset_code = $2", asset_kind, asset_code)
    return True


async def require(conn, asset_kind: str, asset_code: str, holder: str) -> None:
    """写操作前置校验：必须持有效锁（防止绕过锁定直接修改）。"""
    row = await conn.fetchrow(
        "SELECT holder, expires_at FROM locks WHERE asset_kind = $1 AND asset_code = $2",
        asset_kind, asset_code)
    if row is None or row["holder"] != holder or row["expires_at"] <= _now():
        raise PermissionError(
            f"LOCKED:{asset_kind}:{asset_code}:修改前需先获取该资产的排他编辑锁"
            f"（当前持锁人：{row['holder'] if row else '无'}）")


async def status_of(conn, asset_kind: str, asset_code: str) -> dict | None:
    row = await conn.fetchrow(
        "SELECT holder, expires_at FROM locks WHERE asset_kind = $1 AND asset_code = $2",
        asset_kind, asset_code)
    if row is None or row["expires_at"] <= _now():
        return None
    return {"holder": row["holder"],
            "remaining_minutes": max(1, int((row["expires_at"] - _now()).total_seconds() // 60))}
